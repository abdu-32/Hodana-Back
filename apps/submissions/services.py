"""
submissions -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here. This is the layer that enforces the business rules from
Document 02 Sec 3.8 (SUB module) and BR-003/BR-006, and is unit-tested
directly (NFR-MAINT-001: 80% coverage target) without spinning up HTTP
requests.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import RoleAssignment
from apps.core.models import AuditLogEntry
from apps.hackathons.models import Hackathon, ChallengeTrack
from apps.teams.models import TeamMember

from .models import Submission, SubmissionVersion, SubmissionTrack

# FR-SUB-002: "up to 5 media files (images or a single demo video link)".
MAX_ATTACHMENTS = 5

# FR-SUB-004: "up to the 10 most recent versions are retained".
MAX_RETAINED_VERSIONS = 10


import uuid

def _get_hackathon_or_404(hackathon_id):
    try:
        try:
            val = uuid.UUID(str(hackathon_id))
            return Hackathon.objects.get(id=val)
        except (ValueError, AttributeError):
            return Hackathon.objects.get(slug=str(hackathon_id))
    except Hackathon.DoesNotExist:
        raise NotFound("Hackathon not found.")


def _get_submission_or_404(submission_id):
    try:
        return Submission.objects.select_related("hackathon", "team").get(id=submission_id)
    except (Submission.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_actor_team(*, hackathon, actor):
    """FR-SUB-001: resolves actor's team in this hackathon, or auto-provisions
    a solo team if the user registered solo / without an existing team."""
    membership = TeamMember.objects.select_related("team").filter(
        hackathon=hackathon, user=actor, join_status="accepted",
    ).first()
    if membership:
        return membership.team

    from apps.teams.models import Team
    leader_team = Team.objects.filter(hackathon=hackathon, leader_user=actor).first()
    if leader_team:
        return leader_team

    from apps.registrations.models import Registration
    reg = Registration.objects.filter(hackathon=hackathon, user=actor, withdrawn_at__isnull=True).first()
    if not reg and not getattr(actor, "is_platform_admin", False):
        raise ValidationError("You must be registered for this hackathon to have a submission.")

    max_team_sz = 5
    if hackathon.eligibility_rules and isinstance(hackathon.eligibility_rules, dict):
        max_team_sz = hackathon.eligibility_rules.get("max_team_size", 5) or 5

    solo_team, _ = Team.objects.get_or_create(
        hackathon=hackathon,
        leader_user=actor,
        defaults={
            "team_name": (actor.full_name or actor.email.split("@")[0])[:60],
            "max_size": max_team_sz,
        },
    )
    TeamMember.objects.get_or_create(
        team=solo_team,
        user=actor,
        defaults={
            "hackathon": hackathon,
            "invitee_email": actor.email,
            "join_status": "accepted",
            "expires_at": timezone.now() + timezone.timedelta(days=365),
        },
    )
    return solo_team



def _is_team_member(*, team, actor):
    return team.leader_user_id == actor.id or TeamMember.objects.filter(team=team, user=actor, join_status="accepted").exists()


def _is_organizer_or_admin(*, hackathon, actor):
    if getattr(actor, "is_platform_admin", False):
        return True
    return (
        RoleAssignment.objects.filter(
            user=actor, role="organizer", scope_type="organization", scope_id=hackathon.host_org_id,
        ).exists()
        or RoleAssignment.objects.filter(
            user=actor, role="organizer", scope_type="hackathon", scope_id=hackathon.id,
        ).exists()
        or hackathon.created_by_id == actor.id
    )


def _require_team_member(*, submission, actor):
    if not _is_team_member(team=submission.team, actor=actor):
        raise PermissionDenied()


def _require_team_member_or_organizer(*, submission, actor):
    """FR-SUB-004: version history is visible only to team members and
    the Organizer -- reused for the submission-detail view too, since
    Doc 02 never opens either endpoint beyond that pair (public/judge
    visibility of a submission's *contents* is a separate concern owned
    by apps.showcase / apps.judging once they read this model directly)."""
    if _is_team_member(team=submission.team, actor=actor):
        return
    if _is_organizer_or_admin(hackathon=submission.hackathon, actor=actor):
        return
    raise PermissionDenied()


def _require_not_locked(hackathon):
    """BR-003: submissions become read-only immediately at the submission
    deadline. Checked live against the hackathon's deadline, same pattern
    as apps.teams.services._require_roster_not_locked -- the
    Celery-Beat-driven `locked_at` write described in Design Spec Sec 5.2
    is a supporting/notification job, not the source of truth for this
    check."""
    if timezone.now() >= hackathon.submission_closes_at:
        raise ValidationError("Submissions are locked after the submission deadline.")



def _record_version(*, submission, actor):
    """Snapshots the pre-change title/description, then trims to the 10
    most recently retained versions (FR-SUB-004)."""
    SubmissionVersion.objects.create(
        submission=submission, title=submission.title, description=submission.description, edited_by=actor,
    )
    stale_ids = list(
        SubmissionVersion.objects.filter(submission=submission)
        .order_by("-created_at")
        .values_list("id", flat=True)[MAX_RETAINED_VERSIONS:]
    )
    if stale_ids:
        SubmissionVersion.objects.filter(id__in=stale_ids).delete()


def _require_submission_track_editable(submission):
    """
    BR-003:
    Submission track opt-ins are locked after the submission deadline.
    """

    if timezone.now() > submission.hackathon.submission_closes_at:
        raise ValidationError(
            "Submission track opt-ins are locked after the submission deadline."
        )

# ---- FR-SUB-001: create and edit a submission -------------------------------

def upsert_submission(*, actor, hackathon_id, title, tagline="", description="", technologies=None, repo_link="", demo_video_url="", attachment_urls=None):
    hackathon = _get_hackathon_or_404(hackathon_id)
    team = _get_actor_team(hackathon=hackathon, actor=actor)
    _require_not_locked(hackathon)

    technologies = technologies or []
    attachment_urls = attachment_urls or []

    with transaction.atomic():
        submission = Submission.objects.select_for_update().filter(team=team).first()

        if submission is None:
            submission = Submission.objects.create(
                hackathon=hackathon, team=team, title=title, tagline=tagline, description=description,
                technologies=technologies, repo_link=repo_link, demo_video_url=demo_video_url,
                attachment_urls=attachment_urls,
                submitted_at=timezone.now(),
            )
            AuditLogEntry.objects.create(
                actor_id=actor.id, action="submission.created", target_type="submission",
                target_id=str(submission.id),
            )
            return submission

        if submission.title != title or submission.description != description:
            _record_version(submission=submission, actor=actor)

        submission.title = title
        submission.tagline = tagline
        submission.description = description
        submission.technologies = technologies
        submission.repo_link = repo_link
        submission.demo_video_url = demo_video_url
        if attachment_urls:
            submission.attachment_urls = attachment_urls
        submission.save(update_fields=[
            "title", "tagline", "description", "technologies", "repo_link", "demo_video_url", "attachment_urls", "updated_at",
        ])

    return submission



def get_my_submission(*, actor, hackathon_id):
    """GET /submissions/hackathons/{hackathonId}/me -- convenience lookup
    so a team can tell whether a draft already exists before calling the
    upsert endpoint."""
    hackathon = _get_hackathon_or_404(hackathon_id)
    team = _get_actor_team(hackathon=hackathon, actor=actor)
    try:
        return Submission.objects.get(team=team)
    except Submission.DoesNotExist:
        raise NotFound()


# ---- FR-SUB-002: attach project media ---------------------------------------

def attach_media(*, actor, submission_id, attachment_urls):
    submission = _get_submission_or_404(submission_id)
    _require_team_member(submission=submission, actor=actor)
    _require_not_locked(submission.hackathon)

    if len(attachment_urls) > MAX_ATTACHMENTS:
        raise ValidationError({"attachmentUrls": [f"A submission may have at most {MAX_ATTACHMENTS} attachments."]})

    submission.attachment_urls = attachment_urls
    submission.save(update_fields=["attachment_urls", "updated_at"])
    return submission


# ---- FR-SUB-003: finalize a submission --------------------------------------

def finalize_submission(*, actor, submission_id):
    submission = _get_submission_or_404(submission_id)
    _require_team_member(submission=submission, actor=actor)
    _require_not_locked(submission.hackathon)

    # FR-SUB-003 precondition: "the submission has all required fields
    # (FR-SUB-001)" -- title, description, and at least one of
    # {repo_link, demo_video_url, attachment_urls}. See models.py's
    # module docstring for why this is checked here, not at draft-save.
    errors = {}
    if not submission.title:
        errors["title"] = ["Title is required to finalize a submission."]
    if not submission.description:
        errors["description"] = ["Description is required to finalize a submission."]
    if not (submission.repo_link or submission.demo_video_url or submission.attachment_urls):
        errors["repoLink"] = ["At least one of a repository URL, demo URL, or media attachment is required."]
    if errors:
        raise ValidationError(errors)

    # FR-SUB-003: "A `final` submission can still be edited by the team
    # until the submission deadline" -- finalizing is a readiness signal,
    # not a lock, so this is a no-op-safe flag flip, re-settable by any
    # further edit... except FR-SUB-001 has no un-finalize action, so
    # once set it simply stays true until the deadline locks everything.
    submission.is_finalized = True
    submission.save(update_fields=["is_finalized", "updated_at"])

    AuditLogEntry.objects.create(
        actor_id=actor.id, action="submission.finalized", target_type="submission", target_id=str(submission.id),
    )
    return submission


# ---- View a submission and its history --------------------------------------

def get_submission(*, actor, submission_id):
    submission = _get_submission_or_404(submission_id)
    _require_team_member_or_organizer(submission=submission, actor=actor)
    return submission


def get_submission_history(*, actor, submission_id):
    submission = _get_submission_or_404(submission_id)
    _require_team_member_or_organizer(submission=submission, actor=actor)
    versions = list(submission.versions.order_by("-created_at"))
    return submission, versions


@transaction.atomic
def opt_in_submission_to_track(*, submission_id, track_id, actor):
    submission = (
        Submission.objects
        .select_for_update()
        .select_related("team__hackathon")
        .get(id=submission_id)
    )

    _require_submission_track_editable(submission)

    # Use your existing team membership authorization helper here.
    _require_team_member(
        submission=submission,
        actor=actor,
    )

    track = ChallengeTrack.objects.get(id=track_id)

    if track.hackathon_id != submission.team.hackathon_id:
        raise ValidationError(
            "The challenge track must belong to the submission's hackathon."
        )

    submission_track, created = SubmissionTrack.objects.get_or_create(
        submission=submission,
        track=track,
    )

    if created:
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="submission_track.opt_in", target_type="submission_track", target_id=str(submission_track.id),
        )

    return submission_track

@transaction.atomic
def remove_submission_from_track(*, submission_id, track_id, actor):
    submission = (
        Submission.objects
        .select_for_update()
        .select_related("team__hackathon")
        .get(id=submission_id)
    )

    _require_submission_track_editable(submission)

    _require_team_member(
        submission=submission,
        actor=actor,
    )

    try:
        submission_track = SubmissionTrack.objects.get(
            submission_id=submission_id,
            track_id=track_id,
        )
    except SubmissionTrack.DoesNotExist:
        raise NotFound(
            "Submission is not opted into this track."
        )

    AuditLogEntry.objects.create(
        actor_id=actor.id, action="submission_track.opt_out", target_type="submission_track", target_id=str(submission_track.id),
    )

    submission_track.delete()


def list_my_submitted_projects(actor):
    """
    Returns all submissions associated with teams the actor belongs to,
    enriched with judge evaluations/reviews and hackathon details.
    """
    from decimal import Decimal
    from apps.judging.models import Score
    from apps.teams.models import Team, TeamMember

    # Find all teams the user is member of or created
    team_ids = set(TeamMember.objects.filter(user=actor, join_status="accepted").values_list("team_id", flat=True))
    created_team_ids = set(Team.objects.filter(leader_user=actor).values_list("id", flat=True))
    all_team_ids = team_ids.union(created_team_ids)

    submissions = list(
        Submission.objects.filter(team_id__in=all_team_ids)
        .select_related("hackathon", "team")
        .order_by("-submitted_at", "-created_at")
    )

    results = []
    for sub in submissions:
        scores = list(Score.objects.filter(submission=sub).select_related("criterion"))
        review = None
        if scores:
            scores_val = [Decimal(s.score_value) for s in scores]
            avg_score = float((sum(scores_val, Decimal("0")) / Decimal(len(scores_val))).quantize(Decimal("0.1")))
            comments = [s.comment for s in scores if s.comment]
            latest_comment = comments[0] if comments else ""

            crit_breakdown = {}
            for s in scores:
                crit_breakdown[s.criterion.name] = float(s.score_value)

            review = {
                "overallScore": avg_score,
                "feedback": latest_comment,
                "status": "COMPLETED" if all(s.status == "final" for s in scores) else "IN_PROGRESS",
                "criteriaScores": crit_breakdown,
            }

        category = sub.hackathon.tags[0] if (sub.hackathon.tags and len(sub.hackathon.tags) > 0) else "General"

        payout_meta = _get_submission_payout_meta(sub)
        rank = "NONE"
        from apps.judging.models import RoundResult
        rr = RoundResult.objects.filter(submission=sub).first()
        if rr and rr.rank:
            if rr.rank == 1:
                rank = "FIRST"
            elif rr.rank == 2:
                rank = "SECOND"
            elif rr.rank == 3:
                rank = "THIRD"

        results.append({
            "id": str(sub.id),
            "hackathonId": str(sub.hackathon.id),
            "hackathonTitle": sub.hackathon.title,
            "hackathonCategory": category,
            "hackathonSlug": sub.hackathon.slug or str(sub.hackathon.id),
            "teamId": str(sub.team.id) if sub.team else "",
            "teamName": sub.team.team_name if sub.team else "My Team",
            "title": sub.title or "Untitled Project",
            "tagline": sub.tagline or "",
            "description": sub.description or "",
            "technologies": sub.technologies or [],
            "repoLink": sub.repo_link or "",
            "demoVideoUrl": sub.demo_video_url or "",
            "attachmentUrls": sub.attachment_urls or [],
            "isFinalized": sub.is_finalized,
            "submittedAt": sub.submitted_at,
            "createdAt": sub.created_at,
            "review": review,
            "rank": rank,
            "payoutStatus": payout_meta.get("status", "NOT_REQUESTED"),
            "payoutDetails": payout_meta.get("details"),
            "deadlinePassed": bool(sub.hackathon.submission_closes_at and sub.hackathon.submission_closes_at <= timezone.now()),
        })

    return results


def _get_submission_payout_meta(submission):
    import json
    if not submission.eligibility_reason:
        return {"status": "NOT_REQUESTED", "details": None}
    try:
        data = json.loads(submission.eligibility_reason)
        if isinstance(data, dict) and "payout" in data:
            return data["payout"]
    except Exception:
        pass
    return {"status": "NOT_REQUESTED", "details": None}


def _save_submission_payout_meta(submission, payout_meta):
    import json
    curr = {}
    if submission.eligibility_reason:
        try:
            curr = json.loads(submission.eligibility_reason)
            if not isinstance(curr, dict):
                curr = {"legacy_reason": str(curr)}
        except Exception:
            curr = {"legacy_reason": submission.eligibility_reason}
    curr["payout"] = payout_meta
    submission.eligibility_reason = json.dumps(curr)
    submission.save(update_fields=["eligibility_reason"])


def list_organizer_submissions(*, actor, hackathon_id=None, min_score=0.0, category=None):
    """
    Returns all submissions for hackathons managed by the authenticated organizer,
    enriched with judge evaluation scores, team info, winner ranks, and payout status.
    """
    from decimal import Decimal
    from django.db.models import Q
    from django.utils import timezone
    from apps.hackathons.models import Hackathon
    from apps.organizations.models import Organization
    from apps.accounts.models import RoleAssignment
    from apps.judging.models import Score, RoundResult

    # 1. Determine managed hackathons
    if (
        getattr(actor, "is_platform_admin", False)
        or getattr(actor, "is_superuser", False)
        or getattr(actor, "role", None) in ("organizer", "admin")
    ):
        hackathons_qs = Hackathon.objects.all()
    else:
        user_org_ids = RoleAssignment.objects.filter(
            user=actor, role="organizer", scope_type="organization"
        ).values_list("scope_id", flat=True)
        created_org_ids = Organization.objects.filter(created_by=actor).values_list("id", flat=True)
        hackathons_qs = Hackathon.objects.filter(
            Q(host_org_id__in=user_org_ids)
            | Q(host_org_id__in=created_org_ids)
            | Q(created_by=actor)
        )

    if hackathon_id and hackathon_id != "all":
        hackathons_qs = hackathons_qs.filter(id=hackathon_id)

    managed_hackathon_ids = list(hackathons_qs.values_list("id", flat=True))
    if not managed_hackathon_ids:
        return []

    # 2. Query submissions
    subs_qs = (
        Submission.objects.filter(hackathon_id__in=managed_hackathon_ids)
        .select_related("hackathon", "team")
        .prefetch_related("team__members")
        .order_by("-created_at")
    )

    results = []
    for sub in subs_qs:
        sub_cat = (
            sub.hackathon.tags[0]
            if (sub.hackathon.tags and len(sub.hackathon.tags) > 0)
            else "General"
        )
        if category and category.lower() != "all" and sub_cat.lower() != category.lower():
            continue

        # Get scores for this submission
        scores = list(
            Score.objects.filter(submission=sub).select_related("judge_user", "criterion")
        )
        if scores:
            scores_val = [Decimal(s.score_value) for s in scores]
            avg_score = float(
                (sum(scores_val, Decimal("0")) / Decimal(len(scores_val))).quantize(
                    Decimal("0.1")
                )
            )
            distinct_judges = len(set(s.judge_user_id for s in scores))
            eval_count = distinct_judges if distinct_judges > 0 else 1
        else:
            avg_score = 0.0
            eval_count = 0

        if min_score and min_score > 0 and avg_score < min_score:
            continue

        rank = "NONE"
        winner_notes = ""
        prize_awarded_at = None

        rr = RoundResult.objects.filter(submission=sub).first()
        if rr and rr.rank:
            if rr.rank == 1:
                rank = "FIRST"
            elif rr.rank == 2:
                rank = "SECOND"
            elif rr.rank == 3:
                rank = "THIRD"
            else:
                rank = "NONE"
            winner_notes = getattr(rr, "notes", "") or ""
            calculated_at = getattr(rr, "calculated_at", None)
            if calculated_at:
                prize_awarded_at = calculated_at.isoformat()

        demo_url = (sub.attachment_urls[0] if sub.attachment_urls else "") or ""
        team_members_count = sub.team.members.count() if sub.team else 1
        team_name = sub.team.team_name if sub.team else "Independent Innovator"
        team_id = str(sub.team.id) if sub.team else f"team-{sub.id}"

        payout_meta = _get_submission_payout_meta(sub)
        deadline_passed = bool(
            sub.hackathon.submission_closes_at and sub.hackathon.submission_closes_at <= timezone.now()
        )

        results.append({
            "id": str(sub.id),
            "teamId": team_id,
            "teamName": team_name,
            "teamMembersCount": team_members_count,
            "projectTitle": sub.title or "Untitled Project",
            "tagline": sub.tagline
            or (sub.description[:120] + "..." if sub.description else ""),
            "category": sub_cat,
            "hackathonId": str(sub.hackathon.id),
            "hackathonName": sub.hackathon.title,
            "averageScore": avg_score,
            "evaluationsCount": eval_count,
            "repoUrl": sub.repo_link or "",
            "demoUrl": demo_url,
            "rank": rank,
            "prizeAwardedAt": prize_awarded_at,
            "winnerNotes": winner_notes,
            "payoutStatus": payout_meta.get("status", "NOT_REQUESTED"),
            "payoutDetails": payout_meta.get("details"),
            "deadlinePassed": deadline_passed,
            "createdAt": sub.created_at.isoformat() if sub.created_at else "",
        })

    return results


def assign_submission_winner(*, actor, submission_id, rank="NONE", winner_notes=""):
    from decimal import Decimal
    from django.utils import timezone
    from apps.judging.models import RoundResult, JudgingRound

    submission = _get_submission_or_404(submission_id)
    _require_team_member_or_organizer(submission=submission, actor=actor)

    judging_round, _ = JudgingRound.objects.get_or_create(
        hackathon=submission.hackathon, track=None
    )

    rank_num = None
    if rank == "FIRST":
        rank_num = 1
    elif rank == "SECOND":
        rank_num = 2
    elif rank == "THIRD":
        rank_num = 3

    # If assigning a specific rank, clear that rank from any other submission in the round
    if rank_num:
        RoundResult.objects.filter(round=judging_round, rank=rank_num).update(rank=None)

    rr, _ = RoundResult.objects.get_or_create(
        round=judging_round,
        submission=submission,
        defaults={"aggregate_score": Decimal("0.00"), "calculated_at": timezone.now()},
    )
    rr.rank = rank_num
    rr.save(update_fields=["rank"])

    return {
        "success": True,
        "submissionId": str(submission.id),
        "rank": rank,
        "winnerNotes": winner_notes,
    }


def request_submission_payout(*, actor, submission_id, message=""):
    """
    Organizer requests winning team to submit their payment details.
    """
    from django.utils import timezone
    submission = _get_submission_or_404(submission_id)
    _require_team_member_or_organizer(submission=submission, actor=actor)

    payout_meta = _get_submission_payout_meta(submission)
    payout_meta["status"] = "REQUESTED"
    payout_meta["requested_at"] = timezone.now().isoformat()
    if message:
        payout_meta["message"] = message

    _save_submission_payout_meta(submission, payout_meta)

    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="submission.payout_requested",
        target_type="submission",
        target_id=str(submission.id),
    )

    return {
        "success": True,
        "submissionId": str(submission.id),
        "payoutStatus": "REQUESTED",
        "requestedAt": payout_meta["requested_at"],
    }


def request_top_3_payouts(*, actor, hackathon_id, message=""):
    """
    Organizer triggers payment form requests for the Top 3 submissions of a hackathon.
    If 1st, 2nd, and 3rd ranks are not already explicitly assigned, they are determined
    from the highest average judge scores.
    """
    from decimal import Decimal
    from django.utils import timezone
    from apps.judging.models import Score, RoundResult, JudgingRound
    from apps.hackathons.models import Hackathon

    hackathon = Hackathon.objects.get(id=hackathon_id)

    # Submissions in this hackathon
    subs = list(Submission.objects.filter(hackathon=hackathon).select_related("hackathon", "team"))
    if not subs:
        return {"success": True, "updatedCount": 0, "submissions": []}

    judging_round, _ = JudgingRound.objects.get_or_create(hackathon=hackathon, track=None)

    # Check if Top 3 ranks are already assigned
    existing_rrs = list(RoundResult.objects.filter(round=judging_round, rank__in=[1, 2, 3]).select_related("submission"))
    ranked_subs = {rr.rank: rr.submission for rr in existing_rrs if rr.submission}

    top_submissions = []
    if 1 in ranked_subs and 2 in ranked_subs and 3 in ranked_subs:
        top_submissions = [ranked_subs[1], ranked_subs[2], ranked_subs[3]]
    else:
        # Calculate scores and pick top 3
        sub_scores = []
        for s in subs:
            scores = list(Score.objects.filter(submission=s))
            if scores:
                avg = sum((Decimal(sc.score_value) for sc in scores), Decimal("0")) / Decimal(len(scores))
            else:
                avg = Decimal("0.0")
            sub_scores.append((s, avg))
        sub_scores.sort(key=lambda item: item[1], reverse=True)
        top_items = sub_scores[:3]

        ranks = [1, 2, 3]
        for idx, (sub, score_val) in enumerate(top_items):
            r_num = ranks[idx]
            RoundResult.objects.filter(round=judging_round, rank=r_num).update(rank=None)
            rr, _ = RoundResult.objects.get_or_create(
                round=judging_round,
                submission=sub,
                defaults={"aggregate_score": score_val, "calculated_at": timezone.now()},
            )
            rr.rank = r_num
            rr.save(update_fields=["rank"])
            top_submissions.append(sub)

    updated_ids = []
    now_iso = timezone.now().isoformat()
    for sub in top_submissions:
        payout_meta = _get_submission_payout_meta(sub)
        payout_meta["status"] = "REQUESTED"
        payout_meta["requested_at"] = now_iso
        if message:
            payout_meta["message"] = message
        _save_submission_payout_meta(sub, payout_meta)
        updated_ids.append(str(sub.id))

    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="submission.top3_payouts_requested",
        target_type="hackathon",
        target_id=str(hackathon.id),
    )

    return {
        "success": True,
        "updatedCount": len(updated_ids),
        "updatedIds": updated_ids,
        "requestedAt": now_iso,
    }


def submit_payout_details(*, actor, submission_id, beneficiary_name, provider, account_number, phone, notes=""):
    """
    Winning team submits their payout method details (Bank account, Telebirr, etc.).
    """
    from django.utils import timezone
    from apps.teams.models import TeamMember

    submission = _get_submission_or_404(submission_id)

    # Actor must be leader or accepted team member
    is_leader = submission.team and submission.team.leader_user_id == actor.id
    is_member = (
        submission.team
        and TeamMember.objects.filter(team=submission.team, user=actor, join_status="accepted").exists()
    )
    if not (is_leader or is_member or getattr(actor, "is_platform_admin", False) or getattr(actor, "is_superuser", False)):
        raise PermissionDenied("Only the winning project team members may submit payment details.")

    payout_meta = _get_submission_payout_meta(submission)
    payout_meta["status"] = "SUBMITTED"
    payout_meta["submitted_at"] = timezone.now().isoformat()
    payout_meta["details"] = {
        "beneficiaryName": beneficiary_name,
        "provider": provider,
        "accountNumber": account_number,
        "phone": phone,
        "notes": notes,
        "submittedBy": str(actor.email),
        "submittedAt": payout_meta["submitted_at"],
    }

    _save_submission_payout_meta(submission, payout_meta)

    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="submission.payout_details_submitted",
        target_type="submission",
        target_id=str(submission.id),
    )

    return {
        "success": True,
        "submissionId": str(submission.id),
        "payoutStatus": "SUBMITTED",
        "payoutDetails": payout_meta["details"],
        "details": payout_meta["details"],
    }


def mark_submission_payout_paid(*, actor, submission_id, transaction_ref=""):
    """
    Organizer marks the prize payout as disbursed/paid.
    """
    from django.utils import timezone
    submission = _get_submission_or_404(submission_id)
    _require_team_member_or_organizer(submission=submission, actor=actor)

    payout_meta = _get_submission_payout_meta(submission)
    payout_meta["status"] = "PAID"
    payout_meta["paid_at"] = timezone.now().isoformat()
    if transaction_ref:
        payout_meta["transactionRef"] = transaction_ref
    if "details" in payout_meta and payout_meta["details"]:
        payout_meta["details"]["paidAt"] = payout_meta["paid_at"]
        payout_meta["details"]["transactionRef"] = transaction_ref

    _save_submission_payout_meta(submission, payout_meta)

    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="submission.payout_disbursed",
        target_type="submission",
        target_id=str(submission.id),
    )

    return {
        "success": True,
        "submissionId": str(submission.id),
        "payoutStatus": "PAID",
        "paidAt": payout_meta["paid_at"],
        "transactionRef": transaction_ref,
        "payoutDetails": payout_meta.get("details"),
    }

