"""
judging -- services

All cross-model orchestration and business rules for FR-HACK-004 and
FR-JUDGE-001..004 live here.
"""

import logging
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from django.apps import apps as django_apps
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import models, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

logger = logging.getLogger(__name__)

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

def get_invitation_details(invitation_id):
    try:
        return JudgeInvitation.objects.select_related(
            "round", "round__hackathon", "round__hackathon__host_org",
        ).get(id=invitation_id)
    except (JudgeInvitation.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound("Judge invitation not found.")


@transaction.atomic
def invite_judge(*, actor, email, round_id=None, hackathon_id=None, note=""):
    if not round_id and not hackathon_id:
        raise ValidationError("Either round_id or hackathon_id is required.")

    if round_id:
        round = _get_round_or_404(round_id)
        _require_round_manager(actor=actor, round=round)
    else:
        try:
            hackathon = Hackathon.objects.select_related("host_org").get(id=hackathon_id)
        except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
            raise NotFound("Hackathon not found.")
        _require_organizer(actor=actor, hackathon=hackathon)
        round, _ = JudgingRound.objects.get_or_create(hackathon=hackathon, track=None)

    if round.status != "not_started":
        raise ValidationError("Judges cannot be invited after the round has opened.")

    normalized = email.strip().lower()
    existing_inv = JudgeInvitation.objects.filter(
        round=round, email=normalized, status__in=["sent", "accepted"],
    ).first()

    if existing_inv and existing_inv.status == "accepted":
        raise ConflictError("This user is already an accepted judge for this hackathon.")

    if existing_inv:
        invitation = existing_inv
        if note:
            invitation.note = note
            invitation.save(update_fields=["note"])
    else:
        invitation = JudgeInvitation.objects.create(
            email=normalized, round=round, invited_at=timezone.now(), note=note or "",
        )

    # Dispatch Judge Invitation Email
    frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
    accept_link = f"{frontend_url}/accept-judge-invite?token={invitation.id}"
    hackathon_title = round.hackathon.title if hasattr(round, "hackathon") and round.hackathon else "Innovation Hackathon"
    org_name = round.hackathon.host_org.name if hasattr(round.hackathon, "host_org") and round.hackathon.host_org else "Event Organizer"
    subject = f"Invitation: Official Judge Panelist for {hackathon_title}"
    inviter_name = getattr(actor, "full_name", None) or getattr(actor, "email", "Event Organizer")
    
    note_line = f"\nPersonal Note from Organizer:\n\"{note.strip()}\"\n" if note and note.strip() else ""

    message = (
        f"Dear Colleague,\n\n"
        f"You have been officially invited by {inviter_name} ({org_name}) to serve as an Official Judge for '{hackathon_title}'.\n\n"
        f"Your technical expertise, evaluation experience, and domain insights will play a key role in reviewing submissions and selecting the winning innovations.\n"
        f"{note_line}\n"
        f"Please click the link below to review your invitation and choose whether to Accept or Decline:\n"
        f"{accept_link}\n\n"
        f"Best regards,\n"
        f"HODANA Innovation Ecosystem Team"
    )
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[normalized],
            fail_silently=False,
        )
    except Exception as exc:
        logger.warning("Could not dispatch judge invitation email to %s: %s", normalized, exc)

    return invitation


@transaction.atomic
def accept_invitation(*, actor, invitation_id):
    try:
        invitation = JudgeInvitation.objects.select_related("round", "round__hackathon").get(id=invitation_id)
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


@transaction.atomic
def decline_invitation(*, actor, invitation_id):
    invitation = get_invitation_details(invitation_id)
    if invitation.email.lower() != actor.email.lower():
        raise PermissionDenied("This invitation is not addressed to your account.")
    if invitation.status not in ["sent", "accepted"]:
        raise ConflictError("This invitation is no longer available.")
    invitation.status = "declined"
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=["status", "responded_at"])
    RoleAssignment.objects.filter(
        user=actor, role="judge", scope_type="hackathon", scope_id=invitation.round.hackathon_id,
    ).delete()
    JudgingAssignment.objects.filter(
        round=invitation.round, judge_user=actor,
    ).delete()
    return invitation


@transaction.atomic
def revoke_invitation(*, actor, invitation_id):
    invitation = get_invitation_details(invitation_id)
    _require_organizer(actor=actor, hackathon=invitation.round.hackathon)
    invitation.status = "revoked"
    invitation.save(update_fields=["status"])
    matching_accounts = Account.objects.filter(email__iexact=invitation.email)
    for acc in matching_accounts:
        RoleAssignment.objects.filter(
            user=acc, role="judge", scope_type="hackathon", scope_id=invitation.round.hackathon_id,
        ).delete()
        JudgingAssignment.objects.filter(
            round=invitation.round, judge_user=acc,
        ).delete()
    return invitation


def list_organizer_judges(*, actor, hackathon_id=None, status=None):
    org_ids = RoleAssignment.objects.filter(
        user=actor, role="organizer", scope_type="organization",
    ).values_list("scope_id", flat=True)

    # Also include hackathons created directly by actor
    created_hackathon_ids = Hackathon.objects.filter(created_by=actor).values_list("id", flat=True)

    qs = JudgeInvitation.objects.filter(
        models.Q(round__hackathon__host_org_id__in=org_ids) |
        models.Q(round__hackathon_id__in=created_hackathon_ids),
    ).select_related("round__hackathon", "round")

    if hackathon_id and hackathon_id != "All":
        qs = qs.filter(round__hackathon_id=hackathon_id)

    if status and status != "All":
        qs = qs.filter(status__iexact=status.lower())

    invitations = list(qs.order_by("-invited_at"))

    results = []
    email_map = {inv.email.lower(): None for inv in invitations}
    for acc in Account.objects.filter(email__in=email_map.keys()):
        email_map[acc.email.lower()] = acc

    for inv in invitations:
        acc = email_map.get(inv.email.lower())
        assigned_count = 0
        scored_count = 0
        if acc:
            assigned_count = JudgingAssignment.objects.filter(
                round=inv.round, judge_user=acc,
            ).count()
            scored_count = Score.objects.filter(
                criterion__round=inv.round, judge_user=acc,
            ).values("submission").distinct().count()

        results.append({
            "id": str(inv.id),
            "email": inv.email,
            "name": acc.full_name if acc else inv.email.split("@")[0],
            "hackathonId": str(inv.round.hackathon_id),
            "hackathonTitle": inv.round.hackathon.title,
            "status": inv.status.upper(),
            "note": inv.note or "",
            "invitedAt": inv.invited_at.isoformat() if inv.invited_at else None,
            "respondedAt": inv.responded_at.isoformat() if inv.responded_at else None,
            "assignmentsCount": assigned_count,
            "scoredCount": scored_count,
        })
    return results


def list_assigned_hackathons_for_judge(*, actor):
    direct_hackathon_ids = set(RoleAssignment.objects.filter(
        user=actor, role="judge", scope_type="hackathon",
    ).values_list("scope_id", flat=True))

    invited_hackathon_ids = set(JudgeInvitation.objects.filter(
        email__iexact=actor.email, status="accepted",
    ).values_list("round__hackathon_id", flat=True))

    assignment_hackathon_ids = set(JudgingAssignment.objects.filter(
        judge_user=actor,
    ).values_list("round__hackathon_id", flat=True))

    all_ids = direct_hackathon_ids | invited_hackathon_ids | assignment_hackathon_ids
    is_judge = (
        getattr(actor, "role", None) == "judge"
        or getattr(actor, "is_platform_admin", False)
        or RoleAssignment.objects.filter(user=actor, role="judge").exists()
    )

    if is_judge:
        submission_hids = set(Submission.objects.values_list("hackathon_id", flat=True))
        all_ids = all_ids | submission_hids
        if not all_ids:
            all_ids = set(Hackathon.objects.values_list("id", flat=True))
    elif not all_ids:
        return []

    hackathons = Hackathon.objects.filter(
        id__in=all_ids,
    ).select_related("host_org").order_by("-submission_closes_at")

    results = []
    for h in hackathons:
        total_subs = Submission.objects.filter(
            hackathon=h, eligibility_status="eligible",
        ).count()
        evaluated_subs = Score.objects.filter(
            criterion__round__hackathon=h, judge_user=actor,
        ).values("submission").distinct().count()

        org_name = h.host_org.name if h.host_org else "Innovation Hub"
        category_str = ", ".join(h.tags[:2]) if h.tags else "Technology"

        results.append({
            "id": str(h.id),
            "title": h.title,
            "slug": h.slug,
            "organizerName": org_name,
            "deadline": h.submission_closes_at.isoformat() if h.submission_closes_at else "",
            "totalSubmissions": total_subs,
            "evaluatedSubmissions": evaluated_subs,
            "category": category_str,
            "bannerImage": h.banner_url or "",
        })
    return results


def list_submissions_for_judge(*, actor, hackathon_id, category=None, status_filter=None):
    try:
        hackathon = Hackathon.objects.get(id=hackathon_id)
    except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
        try:
            hackathon = Hackathon.objects.get(slug=hackathon_id)
        except Hackathon.DoesNotExist:
            raise NotFound("Hackathon not found.")

    real_hackathon_id = hackathon.id

    has_role = RoleAssignment.objects.filter(
        user=actor, role="judge", scope_type="hackathon", scope_id=real_hackathon_id,
    ).exists()
    has_accepted_invite = JudgeInvitation.objects.filter(
        round__hackathon_id=real_hackathon_id, email__iexact=actor.email, status="accepted",
    ).exists()
    has_assignment = JudgingAssignment.objects.filter(
        round__hackathon_id=real_hackathon_id, judge_user=actor,
    ).exists()

    is_judge_authorized = has_role or has_accepted_invite or has_assignment or getattr(actor, "is_platform_admin", False) or getattr(actor, "role", None) == "judge" or RoleAssignment.objects.filter(user=actor, role="judge").exists()
    if not is_judge_authorized:
        raise PermissionDenied("You are not authorized to judge this hackathon.")

    assignments = list(JudgingAssignment.objects.filter(
        round__hackathon_id=real_hackathon_id, judge_user=actor,
    ).select_related("submission"))

    if assignments:
        submission_ids = [a.submission_id for a in assignments]
        subs_qs = Submission.objects.filter(
            id__in=submission_ids,
        ).exclude(eligibility_status="disqualified")
    else:
        subs_qs = Submission.objects.filter(
            hackathon_id=real_hackathon_id,
        ).exclude(eligibility_status="disqualified")

    subs_qs = subs_qs.select_related("team", "hackathon").prefetch_related("team__members")
    submissions = list(subs_qs.order_by("created_at"))

    scores = list(Score.objects.filter(
        criterion__round__hackathon_id=real_hackathon_id,
        judge_user=actor,
        submission__in=submissions,
    ).select_related("criterion"))

    scores_by_sub = defaultdict(list)
    for sc in scores:
        scores_by_sub[sc.submission_id].append(sc)

    criteria_count = JudgingCriterion.objects.filter(
        round__hackathon_id=real_hackathon_id, round__track__isnull=True,
    ).count()

    results = []
    for s in submissions:
        sub_scores = scores_by_sub.get(s.id, [])
        has_any = len(sub_scores) > 0
        all_final = has_any and all(sc.status == "final" for sc in sub_scores) and (criteria_count == 0 or len(sub_scores) >= criteria_count)

        eval_status = "NOT_STARTED"
        if all_final:
            eval_status = "COMPLETED"
        elif has_any:
            eval_status = "IN_PROGRESS"

        if status_filter and status_filter != "all" and eval_status.lower() != status_filter.lower():
            continue

        my_eval = None
        if has_any:
            crit_scores = {}
            for sc in sub_scores:
                crit_name = sc.criterion.name.lower()
                crit_scores[crit_name] = float(sc.score_value)

            overall_val = sum((Decimal(sc.score_value) for sc in sub_scores), Decimal("0")) / Decimal(len(sub_scores)) if sub_scores else Decimal("0")
            latest_comment = next((sc.comment for sc in sub_scores if sc.comment), "")

            my_eval = {
                "id": f"eval-{s.id}",
                "submissionId": str(s.id),
                "judgeId": str(actor.id),
                "criteriaScores": crit_scores,
                "overallScore": float(overall_val.quantize(Decimal("0.1"))),
                "feedback": latest_comment,
                "status": "SUBMITTED" if all_final else "DRAFT",
                "updatedAt": (sub_scores[0].updated_at or sub_scores[0].created_at).isoformat() if sub_scores else "",
            }

        team_members_count = s.team.members.count() if s.team else 1
        team_name = s.team.team_name if s.team else "Independent Innovator"
        team_id = str(s.team.id) if s.team else f"team-{s.id}"

        results.append({
            "id": str(s.id),
            "teamId": team_id,
            "teamName": team_name,
            "teamMembersCount": team_members_count,
            "projectTitle": s.title,
            "description": s.description or "",
            "tagline": s.tagline or (s.description[:100] + "..." if s.description else ""),
            "category": hackathon.tags[0] if hackathon.tags else "General",
            "hackathonId": str(hackathon.id),
            "hackathonName": hackathon.title,
            "repoUrl": getattr(s, "repo_link", "") or "",
            "demoUrl": (s.attachment_urls[0] if getattr(s, "attachment_urls", None) else "") or "",
            "videoUrl": getattr(s, "demo_video_url", "") or "",
            "pitchDeckUrl": "",
            "techStack": getattr(s, "technologies", []) or [],
            "evaluationStatus": eval_status,
            "myEvaluation": my_eval,
        })

    return results


@transaction.atomic
def submit_judge_evaluation(*, actor, hackathon_id=None, submission_id, criteria_scores=None, criteriaScores=None, feedback="", status="final"):
    scores_dict = criteria_scores if criteria_scores is not None else (criteriaScores or {})
    submission = _get_submission_or_404(submission_id)
    if not hackathon_id:
        hackathon_id = submission.hackathon_id
    elif str(submission.hackathon_id) != str(hackathon_id):
        raise ValidationError("Submission does not belong to the specified hackathon.")

    has_role = RoleAssignment.objects.filter(
        user=actor, role="judge", scope_type="hackathon", scope_id=hackathon_id,
    ).exists()
    has_accepted_invite = JudgeInvitation.objects.filter(
        round__hackathon_id=hackathon_id, email__iexact=actor.email, status="accepted",
    ).exists()
    has_assignment = JudgingAssignment.objects.filter(
        round__hackathon_id=hackathon_id, judge_user=actor,
    ).exists()

    is_judge_authorized = has_role or has_accepted_invite or has_assignment or getattr(actor, "is_platform_admin", False) or getattr(actor, "role", None) == "judge" or RoleAssignment.objects.filter(user=actor, role="judge").exists()
    if not is_judge_authorized:
        raise PermissionDenied("You are not authorized to judge this hackathon.")

    judging_round, _ = JudgingRound.objects.get_or_create(hackathon_id=hackathon_id, track=None)

    criteria = list(judging_round.criteria.all())
    if not criteria:
        default_specs = [
            ("Innovation", 0, 10, Decimal("25.00")),
            ("Technical Execution", 0, 10, Decimal("25.00")),
            ("Design & Usability", 0, 10, Decimal("25.00")),
            ("Impact & Value", 0, 10, Decimal("25.00")),
        ]
        for name, min_s, max_s, wt in default_specs:
            criteria.append(JudgingCriterion.objects.create(
                round=judging_round, name=name, min_score=min_s, max_score=max_s, weight=wt,
            ))

    now = timezone.now()
    saved_scores = []
    for crit in criteria:
        val = None
        for key, v in scores_dict.items():
            if key.lower() in crit.name.lower() or crit.name.lower() in key.lower():
                val = int(round(v) if isinstance(v, float) else v)
                break
        if val is None:
            val = int(crit.min_score)

        sc, created = Score.objects.get_or_create(
            submission=submission,
            judge_user=actor,
            criterion=crit,
            defaults={
                "score_value": val,
                "comment": feedback or "",
                "status": status,
                "finalized_at": now if status == "final" else None,
            },
        )
        if not created:
            sc.score_value = val
            if feedback:
                sc.comment = feedback
            sc.status = status
            sc.finalized_at = now if status == "final" else None
            sc.save()
        saved_scores.append(sc)

    return {
        "submissionId": str(submission.id),
        "judgeId": str(actor.id),
        "criteriaScores": scores_dict,
        "overallScore": float(sum((Decimal(sc.score_value) for sc in saved_scores), Decimal("0")) / Decimal(len(saved_scores))) if saved_scores else 0.0,
        "feedback": feedback,
        "status": "SUBMITTED" if status == "final" else "DRAFT",
        "updatedAt": now.isoformat(),
    }


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
