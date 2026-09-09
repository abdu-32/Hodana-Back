"""
analytics -- services

All business logic and cross-model orchestration for FR-ANALYTICS-001 and
FR-ANALYTICS-002 lives here (Design Spec Sec 3.1), reading directly from
apps.registrations, apps.teams, and apps.submissions -- this app has no
models of its own (see models.py).

Caching note: Design Spec Sec 6.1 lists `aggregate_analytics` as a Celery
Beat job (every 5 minutes) and Sec 6.2 reserves an `analytics` broker
queue for it, anticipating a pre-computed/cached read path. Celery itself
is still disabled repo-wide (config/settings/base.py), and at MVP scale
(tens to low hundreds of organizations, per ADR-004) a live aggregate
query over one hackathon's registrations/teams/submissions is cheap
enough to compute per-request. Doing so also trivially satisfies
FR-ANALYTICS-001's "within 5 minutes" freshness bound *and* FR-REG-002's
tighter "withdrawal reflected within 60 seconds" bound at the same time,
which a single 5-minute cache TTL could not. If/when Celery is
re-enabled and hackathon sizes grow, this module is the place to add a
cache read with `aggregate_analytics` as the writer -- the public
function signatures below are written so that swap wouldn't change any
caller.
"""

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.accounts.models import RoleAssignment
from apps.hackathons.models import Hackathon
from apps.registrations.models import Registration
from apps.submissions.models import Submission
from apps.teams.models import TeamMember

# BR-011: minimum cohort size before any demographic figure is shown at all.
MIN_COHORT_SIZE = 10


def _get_hackathon_or_404(hackathon_id):
    try:
        return Hackathon.objects.select_related("host_org").get(id=hackathon_id)
    except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _is_organizer(*, actor, hackathon):
    return RoleAssignment.objects.filter(
        user=actor,
        role="organizer",
        scope_type="organization",
        scope_id=hackathon.host_org_id,
    ).exists()


def _require_analytics_access(*, actor, hackathon):
    """FR-ANALYTICS-001's acceptance criterion: "visible only to
    Organizers of that specific hackathon and to Platform Admins.\""""
    if getattr(actor, "is_platform_admin", False):
        return
    if _is_organizer(actor=actor, hackathon=hackathon):
        return
    raise PermissionDenied("Only this hackathon's Organizer or a Platform Admin can view its analytics.")


def _round1(value):
    """FR-ANALYTICS-001: "displayed to one decimal place.\""""
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def get_registration_dashboard(*, actor, hackathon_id):
    """Implements FR-ANALYTICS-001.

    Returns registration count over time (bucketed by day), the team
    formation rate (percentage of active registrants on a team), and the
    submission conversion rate (percentage of active registrants whose
    team has submitted). Withdrawn registrations (FR-REG-002) are
    excluded from every figure here, not just the headline count.
    """
    hackathon = _get_hackathon_or_404(hackathon_id)
    _require_analytics_access(actor=actor, hackathon=hackathon)

    active_registrations = Registration.objects.filter(
        hackathon=hackathon, withdrawn_at__isnull=True,
    )
    registrant_user_ids = set(active_registrations.values_list("user_id", flat=True))
    registration_count = len(registrant_user_ids)

    registrations_over_time = _bucket_registrations_by_day(active_registrations)

    if registration_count == 0:
        # FR-ANALYTICS-001's precondition ("at least one registration") is
        # a display-readiness note, not a hard error -- a brand-new
        # hackathon's dashboard should show honest zeros, not a 4xx.
        return {
            "hackathon_id": str(hackathon.id),
            "registration_count": 0,
            "registrations_over_time": registrations_over_time,
            "team_formation_rate": 0.0,
            "submission_conversion_rate": 0.0,
        }

    on_team_user_ids = set(
        TeamMember.objects.filter(
            hackathon=hackathon,
            join_status="accepted",
            user_id__in=registrant_user_ids,
        ).values_list("user_id", flat=True)
    )

    submitted_team_ids = set(
        Submission.objects.filter(
            hackathon=hackathon, submitted_at__isnull=False,
        ).values_list("team_id", flat=True)
    )
    submitted_user_ids = set(
        TeamMember.objects.filter(
            hackathon=hackathon,
            join_status="accepted",
            user_id__in=registrant_user_ids,
            team_id__in=submitted_team_ids,
        ).values_list("user_id", flat=True)
    )

    team_formation_rate = _round1(len(on_team_user_ids) / registration_count * 100)
    submission_conversion_rate = _round1(len(submitted_user_ids) / registration_count * 100)

    return {
        "hackathon_id": str(hackathon.id),
        "registration_count": registration_count,
        "registrations_over_time": registrations_over_time,
        "team_formation_rate": team_formation_rate,
        "submission_conversion_rate": submission_conversion_rate,
    }


def _bucket_registrations_by_day(registrations_qs):
    """Buckets active registrations by the calendar day of `registered_at`,
    per FR-ANALYTICS-001's "bucketed by day" acceptance criterion. Small
    enough result sets at MVP scale ("boring technology, deliberately" --
    Design Spec Sec 1.3; see module docstring on caching if this ever
    needs to change) that doing it in Python keeps this readable without
    a database-specific date-trunc expression.
    """
    counts = Counter(
        registered_at.date()
        for registered_at in registrations_qs.values_list("registered_at", flat=True)
    )
    return [
        {"date": day.isoformat(), "count": count}
        for day, count in sorted(counts.items())
    ]


def _bucket_with_privacy_floor(counts, *, min_size=MIN_COHORT_SIZE):
    """BR-011: even once a hackathon clears the overall 10-registration
    threshold, an individual breakdown bucket smaller than that (e.g. a
    university with two registrants) could still identify a specific
    participant. Any bucket below `min_size` is folded into "Other"
    rather than shown on its own; buckets are returned in descending
    order with "Other" always last.
    """
    kept = []
    other = 0
    for label, count in counts.items():
        if count >= min_size:
            kept.append({"label": label, "count": count})
        else:
            other += count
    kept.sort(key=lambda bucket: (-bucket["count"], bucket["label"]))
    if other:
        kept.append({"label": "Other", "count": other})
    return kept


def _age_bucket(date_of_birth, *, as_of):
    """Coarse, fixed buckets rather than raw age -- an exact age next to a
    small headcount is itself a re-identification risk even after the
    BR-011 cohort floor is applied to the bucket as a whole."""
    age = as_of.year - date_of_birth.year - ((as_of.month, as_of.day) < (date_of_birth.month, date_of_birth.day))
    if age < 18:
        return "Under 18"
    if age <= 24:
        return "18-24"
    if age <= 34:
        return "25-34"
    if age <= 44:
        return "35-44"
    return "45+"


def get_demographic_breakdown(*, actor, hackathon_id):
    """Implements FR-ANALYTICS-002.

    An aggregated, anonymized breakdown of active registrants by
    university/institution, self-reported skill category, age group, and
    country -- the latter two read off Account.date_of_birth/country
    (FR-PROFILE-001, self-reported, same trust level as `university`).
    Below the BR-011 cohort-size floor, returns a placeholder rather than
    partial data, per that FR's own acceptance criterion; the same
    per-bucket floor (`_bucket_with_privacy_floor`) also applies to every
    individual age/country/university/skill bucket once that overall
    floor is cleared.
    """
    hackathon = _get_hackathon_or_404(hackathon_id)
    _require_analytics_access(actor=actor, hackathon=hackathon)

    registrants = list(
        Registration.objects.filter(
            hackathon=hackathon, withdrawn_at__isnull=True,
        ).select_related("user")
    )
    current_count = len(registrants)

    if current_count < MIN_COHORT_SIZE:
        return {
            "hackathon_id": str(hackathon.id),
            "available": False,
            "minimum_cohort_size": MIN_COHORT_SIZE,
            "current_count": current_count,
            "by_university": [],
            "by_skill": [],
            "by_age_group": [],
            "by_country": [],
        }

    today = timezone.now().date()
    university_counts = Counter()
    skill_counts = Counter()
    age_counts = Counter()
    country_counts = Counter()
    for registration in registrants:
        university = (registration.user.university or "").strip()
        if university:
            university_counts[university] += 1
        for skill in registration.user.skills:
            skill = (skill or "").strip()
            if skill:
                skill_counts[skill] += 1
        if registration.user.date_of_birth:
            age_counts[_age_bucket(registration.user.date_of_birth, as_of=today)] += 1
        if registration.user.country:
            country_counts[registration.user.country.strip().upper()] += 1

    return {
        "hackathon_id": str(hackathon.id),
        "available": True,
        "minimum_cohort_size": MIN_COHORT_SIZE,
        "current_count": current_count,
        "by_university": _bucket_with_privacy_floor(university_counts),
        "by_skill": _bucket_with_privacy_floor(skill_counts),
        "by_age_group": _bucket_with_privacy_floor(age_counts),
        "by_country": _bucket_with_privacy_floor(country_counts),
    }


def get_platform_stats():
    """Computes real-time platform metrics from PostgreSQL for public hero and landing pages."""
    from django.db.models import Sum
    from apps.accounts.models import Account
    from apps.hackathons.models import Hackathon
    from apps.registrations.models import Registration
    from apps.submissions.models import Submission

    active_developers = Account.objects.filter(
        deleted_at__isnull=True,
        is_suspended=False,
        is_platform_admin=False,
    ).count()

    total_registrations = Registration.objects.filter(withdrawn_at__isnull=True).count()
    total_hackathons = Hackathon.objects.filter(status="published").count()
    prize_sum = (
        Hackathon.objects.filter(status="published").aggregate(total=Sum("total_prize_budget"))["total"]
        or 0
    )
    total_projects = Submission.objects.count()

    return {
        "active_developers": active_developers,
        "total_registrations": total_registrations,
        "total_hackathons": total_hackathons,
        "total_prize_volume_etb": float(prize_sum),
        "total_projects": total_projects,
    }
