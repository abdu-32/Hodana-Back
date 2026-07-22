"""
judging -- services

All cross-model orchestration and business rules for FR-HACK-004 and
FR-JUDGE-001..004 live here.
"""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.accounts.models import Account, RoleAssignment
from apps.core.models import AuditLogEntry
from apps.hackathons.models import ChallengeTrack, Hackathon
from apps.submissions.models import Submission

from .models import (
    JudgeInvitation,
    JudgingAssignment,
    JudgingCriterion,
    JudgingRound,
    RoundResult,
    Score,
)


class ConflictError(APIException):
    status_code = 409
    default_detail = "This action conflicts with the current judging state."
    default_code = "conflict"


def _get_round_or_404(round_id):
    try:
        return JudgingRound.objects.select_related(
            "hackathon", "hackathon__host_org", "track",
        ).get(id=round_id)
    except (JudgingRound.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_submission_or_404(submission_id):
    try:
        return Submission.objects.select_related("hackathon", "team").get(id=submission_id)
    except (Submission.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_criterion_or_404(criterion_id):
    try:
        return JudgingCriterion.objects.select_related("round").get(id=criterion_id)
    except (JudgingCriterion.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _is_organizer(*, actor, hackathon):
    return RoleAssignment.objects.filter(
        user=actor,
        role="organizer",
        scope_type="organization",
        scope_id=hackathon.host_org_id,
    ).exists()


def _is_sponsor_for_track(*, actor, track):
    return RoleAssignment.objects.filter(
        user=actor,
        role="sponsor",
        scope_type="organization",
        scope_id=track.sponsor_org_id,
    ).exists() or RoleAssignment.objects.filter(
        user=actor,
        role="sponsor",
        scope_type="track",
        scope_id=track.id,
    ).exists()


def _require_round_manager(*, actor, round):
    if _is_organizer(actor=actor, hackathon=round.hackathon):
        return
    if round.track_id and _is_sponsor_for_track(actor=actor, track=round.track):
        return
    raise PermissionDenied("You do not manage this judging round.")


def _require_organizer(*, actor, hackathon):
    if not _is_organizer(actor=actor, hackathon=hackathon):
        raise PermissionDenied("Only the hackathon Organizer can perform this action.")


def _has_accepted_judge_invitation(*, user, round):
    return JudgeInvitation.objects.filter(
        round=round, email__iexact=user.email, status="accepted",
    ).exists()


def _require_assigned_judge(*, actor, round, submission):
    assignment = JudgingAssignment.objects.filter(
        round=round, submission=submission, judge_user=actor,
    ).first()
    if not assignment:
        raise PermissionDenied("You are not assigned to judge this submission.")
    return assignment


def _submission_in_round(*, submission, round):
    if submission.hackathon_id != round.hackathon_id:
        return False
    if round.track_id is None:
        return True
    # SubmissionTrack belongs to the submissions/track-opt-in implementation.
    # The current repository does not yet define that model, so keep the
    # dependency lazy and fail explicitly instead of making judging import
    # time fail for the Overall round.
    try:
        submission_track_model = django_apps.get_model("submissions", "SubmissionTrack")
    except LookupError:
        raise ValidationError(
            "Track-scoped judging requires the submissions SubmissionTrack model."
        )
    return submission_track_model.objects.filter(
        submission=submission, track_id=round.track_id,
    ).exists()


def _validate_round_rubric(*, round):
    criteria = list(round.criteria.all())
    if not criteria:
        raise ValidationError("A judging round must have at least one criterion.")
    total = sum((criterion.weight for criterion in criteria), Decimal("0"))
    if total != Decimal("100"):
        raise ValidationError({
            "weight": f"Criterion weights must sum to 100; received {total}.",
        })


# ---- FR-JUDGE-004: rounds ---------------------------------------------------

def list_rounds(*, actor, hackathon_id, track_id=None):
    rounds = JudgingRound.objects.select_related(
        "track", "hackathon", "hackathon__host_org",
    ).filter(hackathon_id=hackathon_id)
    if track_id is not None:
        rounds = rounds.filter(track_id=track_id)
    rounds = list(rounds.order_by("track_id", "id"))
    if not rounds:
        return rounds
    if _is_organizer(actor=actor, hackathon=rounds[0].hackathon):
        return rounds
    if all(
        round.track_id and _is_sponsor_for_track(actor=actor, track=round.track)
        for round in rounds
    ):
        return rounds
    raise PermissionDenied("You do not have access to these judging rounds.")


@transaction.atomic
def create_round(*, actor, hackathon_id, track_id=None):
    try:
        hackathon = Hackathon.objects.select_related("host_org").get(id=hackathon_id)
    except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()

    track = None
    if track_id is not None:
        try:
            track = ChallengeTrack.objects.get(id=track_id, hackathon_id=hackathon.id)
        except (ChallengeTrack.DoesNotExist, ValueError, DjangoValidationError):
            raise NotFound()
        if not _is_organizer(actor=actor, hackathon=hackathon) and not _is_sponsor_for_track(
            actor=actor, track=track,
        ):
            raise PermissionDenied("You do not manage this challenge track.")
    else:
        _require_organizer(actor=actor, hackathon=hackathon)

    if JudgingRound.objects.filter(hackathon=hackathon, track=track).exists():
        raise ConflictError("A judging round already exists for this scope.")

    return JudgingRound.objects.create(hackathon=hackathon, track=track)


def open_round(*, actor, round_id):
    round = _get_round_or_404(round_id)
    _require_round_manager(actor=actor, round=round)
    if round.status != "not_started":
        raise ValidationError("Only a not-started round can be opened.")
    _validate_round_rubric(round=round)
    now = timezone.now()
    round.status = "open"
    round.opened_at = now
    round.save(update_fields=["status", "opened_at"])
    return round


def close_round(*, actor, round_id):
    round = _get_round_or_404(round_id)
    _require_round_manager(actor=actor, round=round)
    if round.status != "open":
        raise ValidationError("Only an open round can be closed.")
    round.status = "closed"
    round.closed_at = timezone.now()
    round.save(update_fields=["status", "closed_at"])
    calculate_round_results(round_id=round.id)
    return round


# ---- FR-HACK-004 / BR-005: criteria -----------------------------------------

def list_criteria(*, actor, round_id):
    round = _get_round_or_404(round_id)
    _require_round_manager(actor=actor, round=round)
    return round.criteria.all().order_by("id")


def create_criterion(*, actor, round_id, name, min_score=0, max_score=None, weight=0):
    round = _get_round_or_404(round_id)
    _require_round_manager(actor=actor, round=round)
    if round.status == "open":
        raise ConflictError("The rubric cannot be modified after judging opens.")
    if max_score is None or max_score <= min_score:
        raise ValidationError({"maxScore": "Must be greater than minScore."})
    criterion = JudgingCriterion.objects.create(
        round=round,
        name=name,
        min_score=min_score,
        max_score=max_score,
        weight=weight,
    )
    # BR-005 says the rubric is weight-balanced on save. We validate the
    # aggregate immediately, but allow the temporary incomplete state needed
    # to build a rubric criterion-by-criterion before opening the round.
    if sum((c.weight for c in round.criteria.all()), Decimal("0")) > Decimal("100"):
        criterion.delete()
        raise ValidationError({"weight": "Criterion weights cannot exceed 100."})
    return criterion


# ---- FR-JUDGE-001: invitations and assignment -------------------------------

@transaction.atomic
def invite_judge(*, actor, email, round_id):
    round = _get_round_or_404(round_id)
    _require_round_manager(actor=actor, round=round)
    if round.status != "not_started":
        raise ValidationError("Judges cannot be invited after the round has opened.")
    normalized = email.strip().lower()
    invitation = JudgeInvitation.objects.create(
        email=normalized, round=round, invited_at=timezone.now(),
    )
    return invitation


@transaction.atomic
def accept_invitation(*, actor, invitation_id):
    try:
        invitation = JudgeInvitation.objects.select_related("round").get(id=invitation_id)
    except (JudgeInvitation.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()
    if invitation.email.lower() != actor.email.lower():
        raise PermissionDenied("This invitation is not addressed to your account.")
    if invitation.status != "sent":
        raise ConflictError("This invitation is no longer available.")
    invitation.status = "accepted"
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=["status", "responded_at"])
    RoleAssignment.objects.get_or_create(
        user=actor,
        role="judge",
        scope_type="hackathon",
        scope_id=invitation.round.hackathon_id,
    )
    return invitation


def _eligible_submissions_for_round(round):
    qs = Submission.objects.filter(
        hackathon_id=round.hackathon_id,
        eligibility_status="eligible",
    )
    if round.track_id:
        try:
            submission_track_model = django_apps.get_model("submissions", "SubmissionTrack")
        except LookupError:
            raise ValidationError(
                "Track-scoped judging requires the submissions SubmissionTrack model."
            )
        qs = qs.filter(
            id__in=submission_track_model.objects.filter(
                track_id=round.track_id,
            ).values("submission_id")
        )
    return qs.order_by("id")


def assign_judge(*, actor, round_id, submission_id, judge_user_id):
    round = _get_round_or_404(round_id)
    _require_organizer(actor=actor, hackathon=round.hackathon)
    if round.status != "not_started":
        raise ValidationError("Assignments cannot be changed after judging opens.")
    submission = _get_submission_or_404(submission_id)
    if not _submission_in_round(submission=submission, round=round):
        raise ValidationError("This submission is not in the judging round.")
    if submission.eligibility_status != "eligible":
        raise ValidationError("Only eligible submissions can be assigned.")
    try:
        judge = Account.objects.get(id=judge_user_id)
    except (Account.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()
    if not _has_accepted_judge_invitation(user=judge, round=round):
        raise ValidationError("The judge must accept an invitation for this round.")
    assignment, created = JudgingAssignment.objects.get_or_create(
        round=round,
        submission=submission,
        judge_user=judge,
        defaults={"assigned_at": timezone.now()},
    )
    if not created:
        raise ConflictError("This judge is already assigned to this submission.")
    return assignment


@transaction.atomic
def auto_distribute(*, actor, round_id, judge_user_ids):
    round = _get_round_or_404(round_id)
    _require_organizer(actor=actor, hackathon=round.hackathon)
    if round.status != "not_started":
        raise ValidationError("Assignments cannot be changed after judging opens.")
    judges = list(Account.objects.filter(id__in=judge_user_ids))
    if len(judges) != len(set(judge_user_ids)):
        raise ValidationError("All requested judges must exist.")
    for judge in judges:
        if not _has_accepted_judge_invitation(user=judge, round=round):
            raise ValidationError(f"{judge.email} has not accepted an invitation for this round.")

    submissions = list(_eligible_submissions_for_round(round))
    if not judges:
        raise ValidationError("At least one judge is required.")
    # Round-robin produces assignment counts differing by at most one.
    for index, submission in enumerate(submissions):
        judge = judges[index % len(judges)]
        JudgingAssignment.objects.get_or_create(
            round=round,
            submission=submission,
            judge_user=judge,
            defaults={"assigned_at": timezone.now()},
        )
    return list(JudgingAssignment.objects.filter(round=round).select_related("submission", "judge_user"))


@transaction.atomic
def remove_assignment(*, actor, assignment_id, confirm_score_discard=False):
    try:
        assignment = JudgingAssignment.objects.select_related(
            "round__hackathon", "submission",
        ).get(id=assignment_id)
    except (JudgingAssignment.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()
    _require_organizer(actor=actor, hackathon=assignment.round.hackathon)
    if assignment.round.status != "not_started":
        raise ValidationError("Assignments cannot be changed after judging opens.")
    has_scores = Score.objects.filter(
        submission=assignment.submission,
        judge_user=assignment.judge_user,
        criterion__round=assignment.round,
    ).exists()
    if has_scores and not confirm_score_discard:
        raise ConflictError(
            "This judge has already scored the submission; confirm score discard before removal."
        )
    if has_scores:
        Score.objects.filter(
            submission=assignment.submission,
            judge_user=assignment.judge_user,
            criterion__round=assignment.round,
        ).delete()
    assignment.delete()


@transaction.atomic
def reassign_judge(*, actor, assignment_id, new_judge_user_id, confirm_score_discard=False):
    try:
        assignment = JudgingAssignment.objects.select_related(
            "round__hackathon", "submission",
        ).get(id=assignment_id)
    except (JudgingAssignment.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()
    round = assignment.round
    _require_organizer(actor=actor, hackathon=round.hackathon)
    if round.status != "not_started":
        raise ValidationError("Assignments cannot be changed after judging opens.")
    try:
        new_judge = Account.objects.get(id=new_judge_user_id)
    except (Account.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()
    if not _has_accepted_judge_invitation(user=new_judge, round=round):
        raise ValidationError("The new judge must accept an invitation for this round.")
    if JudgingAssignment.objects.filter(
        round=round, submission=assignment.submission, judge_user=new_judge,
    ).exclude(id=assignment.id).exists():
        raise ConflictError("The new judge is already assigned to this submission.")
    has_scores = Score.objects.filter(
        submission=assignment.submission,
        judge_user=assignment.judge_user,
        criterion__round=round,
    ).exists()
    if has_scores and not confirm_score_discard:
        raise ConflictError(
            "This judge has already scored the submission; confirm score discard before reassignment."
        )
    if has_scores:
        Score.objects.filter(
            submission=assignment.submission,
            judge_user=assignment.judge_user,
            criterion__round=round,
        ).delete()
    assignment.reassigned_from_user = assignment.judge_user
    assignment.judge_user = new_judge
    assignment.assigned_at = timezone.now()
    assignment.save(update_fields=[
        "reassigned_from_user", "judge_user", "assigned_at",
    ])
    return assignment


def list_assignments(*, actor, round_id, judge_user_id=None):
    round = _get_round_or_404(round_id)
    if judge_user_id is not None and str(actor.id) == str(judge_user_id):
        return JudgingAssignment.objects.filter(
            round=round, judge_user_id=judge_user_id,
        ).select_related("submission", "judge_user")
    _require_organizer(actor=actor, hackathon=round.hackathon)
    qs = JudgingAssignment.objects.filter(round=round)
    if judge_user_id:
        qs = qs.filter(judge_user_id=judge_user_id)
    return qs.select_related("submission", "judge_user")


# ---- FR-JUDGE-002: scoring --------------------------------------------------

def submit_score(*, actor, submission_id, criterion_id, score_value, comment="", status="final"):
    criterion = _get_criterion_or_404(criterion_id)
    round = criterion.round
    submission = _get_submission_or_404(submission_id)
    if not _submission_in_round(submission=submission, round=round):
        raise ValidationError("This submission is not part of the criterion's judging round.")
    _require_assigned_judge(actor=actor, round=round, submission=submission)
    existing = Score.objects.filter(
        submission=submission, judge_user=actor, criterion=criterion,
    ).first()
    reopened_revision = existing is not None and existing.status == "draft" and existing.reopened_at is not None
    if round.status != "open" and not (round.status == "closed" and reopened_revision):
        raise ValidationError("Scores can only be saved while the judging round is open.")
    if not criterion.min_score <= score_value <= criterion.max_score:
        raise ValidationError({
            "scoreValue": f"Must be between {criterion.min_score} and {criterion.max_score}.",
        })
    if status == "final":
        _validate_round_rubric(round=round)

    score, created = Score.objects.get_or_create(
        submission=submission,
        judge_user=actor,
        criterion=criterion,
        defaults={
            "score_value": score_value,
            "comment": comment,
            "status": status,
            "finalized_at": timezone.now() if status == "final" else None,
        },
    )
    if not created:
        if score.status == "final":
            raise ConflictError("A final score cannot be edited by the judge.")
        score.score_value = score_value
        score.comment = comment
        score.status = status
        score.finalized_at = timezone.now() if status == "final" else None
        score.save()
        if status == "final" and round.status == "closed":
            calculate_round_results(round_id=round.id)
    return score


def reopen_score(*, actor, score_id, reason):
    try:
        score = Score.objects.select_related("criterion__round", "submission").get(id=score_id)
    except (Score.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()
    round = score.criterion.round
    _require_organizer(actor=actor, hackathon=round.hackathon)
    if not reason or len(reason.strip()) < 10:
        raise ValidationError({"reason": "A reopen reason must be at least 10 characters."})
    score.status = "draft"
    score.reopened_at = timezone.now()
    score.reopen_reason = reason.strip()
    score.save(update_fields=["status", "reopened_at", "reopen_reason"])
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="judging.score_reopened",
        target_type="score",
        target_id=str(score.id),
        metadata={"reason": reason.strip()},
    )
    return score


def list_submission_scores(*, actor, submission_id):
    submission = _get_submission_or_404(submission_id)
    _require_organizer(actor=actor, hackathon=submission.hackathon)
    return Score.objects.filter(
        submission=submission,
    ).select_related("criterion", "judge_user").order_by("criterion_id", "judge_user_id")


# ---- FR-JUDGE-003: result calculation ---------------------------------------

def calculate_round_results(*, round_id):
    round = _get_round_or_404(round_id)
    if round.status != "closed":
        raise ValidationError("Results can only be calculated for a closed round.")

    criteria = list(round.criteria.all())
    if not criteria:
        return []

    final_scores = Score.objects.filter(
        criterion__round=round,
        status="final",
    ).select_related("criterion")

    by_judge_submission = defaultdict(list)
    for score in final_scores:
        by_judge_submission[(score.submission_id, score.judge_user_id)].append(score)

    weighted_by_submission = defaultdict(list)
    for (submission_id, judge_id), scores in by_judge_submission.items():
        by_criterion = {score.criterion_id: score for score in scores}
        # A judge only contributes a final score when they completed the
        # entire rubric. Partial scoring is not silently treated as zero.
        if len(by_criterion) != len(criteria):
            continue
        weighted = sum(
            (Decimal(score.score_value) * score.criterion.weight for score in scores),
            Decimal("0"),
        ) / Decimal("100")
        weighted_by_submission[submission_id].append(weighted)

    aggregates = []
    for submission_id, judge_scores in weighted_by_submission.items():
        if not judge_scores:
            continue
        aggregate = (
            sum(judge_scores, Decimal("0")) / Decimal(len(judge_scores))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        aggregates.append((submission_id, aggregate))

    aggregates.sort(key=lambda item: (-item[1], str(item[0])))
    now = timezone.now()
    with transaction.atomic():
        RoundResult.objects.filter(round=round).delete()
        results = []
        for rank, (submission_id, aggregate) in enumerate(aggregates, start=1):
            results.append(RoundResult.objects.create(
                round=round,
                submission_id=submission_id,
                aggregate_score=aggregate,
                rank=rank,
                calculated_at=now,
            ))
    return results
