"""
Unit tests against analytics/services.py directly (Design Spec Sec 3.1),
per the 80% coverage target in NFR-MAINT-001.
"""

from datetime import date

import pytest
from freezegun import freeze_time
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.accounts.models import RoleAssignment
from apps.accounts.tests.factories import AccountFactory
from apps.hackathons.tests.factories import PublishedHackathonFactory
from apps.organizations.tests.factories import VerifiedOrganizationFactory
from apps.registrations.tests.factories import (
    RegistrationFactory,
    WithdrawnRegistrationFactory,
)
from apps.submissions.tests.factories import SubmissionFactory
from apps.teams.tests.factories import AcceptedTeamMemberFactory, TeamFactory

from .. import services

pytestmark = pytest.mark.django_db


@pytest.fixture
def organizer():
    return AccountFactory()


@pytest.fixture
def org(organizer):
    return VerifiedOrganizationFactory(created_by=organizer)


@pytest.fixture
def organizer_role(organizer, org):
    return RoleAssignment.objects.create(
        user=organizer, role="organizer", scope_type="organization", scope_id=org.id,
    )


@pytest.fixture
def hackathon(org, organizer, organizer_role):
    return PublishedHackathonFactory(host_org=org, created_by=organizer)


@pytest.fixture
def platform_admin():
    return AccountFactory(is_platform_admin=True)


# ---- access control ---------------------------------------------------


def test_dashboard_denies_non_organizer(hackathon):
    stranger = AccountFactory()
    with pytest.raises(PermissionDenied):
        services.get_registration_dashboard(actor=stranger, hackathon_id=hackathon.id)


def test_dashboard_allows_organizer(hackathon, organizer):
    result = services.get_registration_dashboard(actor=organizer, hackathon_id=hackathon.id)
    assert result["hackathon_id"] == str(hackathon.id)


def test_dashboard_allows_platform_admin(hackathon, platform_admin):
    result = services.get_registration_dashboard(actor=platform_admin, hackathon_id=hackathon.id)
    assert result["registration_count"] == 0


def test_dashboard_404s_for_unknown_hackathon(organizer):
    import uuid

    with pytest.raises(NotFound):
        services.get_registration_dashboard(actor=organizer, hackathon_id=uuid.uuid4())


# ---- FR-ANALYTICS-001: registration dashboard --------------------------


def test_dashboard_zero_registrations_is_not_an_error(hackathon, organizer):
    result = services.get_registration_dashboard(actor=organizer, hackathon_id=hackathon.id)
    assert result["registration_count"] == 0
    assert result["registrations_over_time"] == []
    assert result["team_formation_rate"] == 0.0
    assert result["submission_conversion_rate"] == 0.0


def test_dashboard_counts_active_registrations_bucketed_by_day(hackathon, organizer):
    RegistrationFactory(hackathon=hackathon)
    RegistrationFactory(hackathon=hackathon)

    result = services.get_registration_dashboard(actor=organizer, hackathon_id=hackathon.id)

    assert result["registration_count"] == 2
    assert len(result["registrations_over_time"]) == 1
    assert result["registrations_over_time"][0]["count"] == 2


def test_dashboard_excludes_withdrawn_registrations(hackathon, organizer):
    RegistrationFactory(hackathon=hackathon)
    WithdrawnRegistrationFactory(hackathon=hackathon)

    result = services.get_registration_dashboard(actor=organizer, hackathon_id=hackathon.id)

    assert result["registration_count"] == 1
    assert result["registrations_over_time"][0]["count"] == 1


def test_dashboard_team_formation_rate(hackathon, organizer):
    on_team_reg = RegistrationFactory(hackathon=hackathon)
    RegistrationFactory(hackathon=hackathon)  # not on a team
    team = TeamFactory(hackathon=hackathon)
    AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=on_team_reg.user)

    result = services.get_registration_dashboard(actor=organizer, hackathon_id=hackathon.id)

    assert result["registration_count"] == 2
    assert result["team_formation_rate"] == 50.0


def test_dashboard_submission_conversion_rate(hackathon, organizer):
    submitter_reg = RegistrationFactory(hackathon=hackathon)
    RegistrationFactory(hackathon=hackathon)  # never submits
    team = TeamFactory(hackathon=hackathon)
    AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=submitter_reg.user)
    SubmissionFactory(team=team, hackathon=hackathon, submitted_at=timezone.now())

    result = services.get_registration_dashboard(actor=organizer, hackathon_id=hackathon.id)

    assert result["submission_conversion_rate"] == 50.0


def test_dashboard_excludes_draft_submissions_from_conversion(hackathon, organizer):
    """A Submission row with no submitted_at (a draft never saved with a
    first submission) doesn't count as "submitted" -- DB Design Sec 4.6:
    submitted_at is the first-save timestamp, distinct from finalization,
    but still None until at least one save occurs."""
    reg = RegistrationFactory(hackathon=hackathon)
    team = TeamFactory(hackathon=hackathon)
    AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=reg.user)
    SubmissionFactory(team=team, hackathon=hackathon, submitted_at=None)

    result = services.get_registration_dashboard(actor=organizer, hackathon_id=hackathon.id)

    assert result["submission_conversion_rate"] == 0.0


# ---- FR-ANALYTICS-002 / BR-011: demographic breakdown ------------------


def test_demographics_denies_non_organizer(hackathon):
    stranger = AccountFactory()
    with pytest.raises(PermissionDenied):
        services.get_demographic_breakdown(actor=stranger, hackathon_id=hackathon.id)


def test_demographics_below_cohort_floor_is_placeholder(hackathon, organizer):
    for _ in range(9):
        RegistrationFactory(hackathon=hackathon)

    result = services.get_demographic_breakdown(actor=organizer, hackathon_id=hackathon.id)

    assert result["available"] is False
    assert result["current_count"] == 9
    assert result["by_university"] == []
    assert result["by_skill"] == []
    assert result["by_age_group"] == []
    assert result["by_country"] == []


def test_demographics_at_cohort_floor_is_available(hackathon, organizer):
    for i in range(10):
        RegistrationFactory(
            hackathon=hackathon,
            user=AccountFactory(university="Addis Ababa University", skills=["python"]),
        )

    result = services.get_demographic_breakdown(actor=organizer, hackathon_id=hackathon.id)

    assert result["available"] is True
    assert result["current_count"] == 10
    assert result["by_university"] == [{"label": "Addis Ababa University", "count": 10}]
    assert result["by_skill"] == [{"label": "python", "count": 10}]


@freeze_time("2026-01-15")
def test_demographics_buckets_by_age_group(hackathon, organizer):
    for i in range(10):
        RegistrationFactory(
            hackathon=hackathon,
            user=AccountFactory(date_of_birth=date(2001, 6, 1)),  # 24 -> "18-24"
        )

    result = services.get_demographic_breakdown(actor=organizer, hackathon_id=hackathon.id)

    assert result["by_age_group"] == [{"label": "18-24", "count": 10}]


@freeze_time("2026-01-15")
def test_demographics_registrants_without_date_of_birth_are_excluded_from_age_bucket(hackathon, organizer):
    for i in range(9):
        RegistrationFactory(
            hackathon=hackathon,
            user=AccountFactory(date_of_birth=date(2001, 6, 1)),  # 24 -> "18-24"
        )
    # Tenth registrant clears the overall cohort floor but never filled in
    # date_of_birth -- shouldn't be silently counted into any age bucket.
    RegistrationFactory(hackathon=hackathon, user=AccountFactory(date_of_birth=None))

    result = services.get_demographic_breakdown(actor=organizer, hackathon_id=hackathon.id)

    assert result["current_count"] == 10
    # Only 9 people reported an age, and 9 is below the 10-person
    # per-bucket privacy floor (_bucket_with_privacy_floor) -- same rule
    # applied to every other bucket -- so it folds into "Other" rather
    # than appearing as its own "18-24" label.
    assert result["by_age_group"] == [{"label": "Other", "count": 9}]


def test_demographics_buckets_by_country(hackathon, organizer):
    for i in range(10):
        RegistrationFactory(hackathon=hackathon, user=AccountFactory(country="ET"))

    result = services.get_demographic_breakdown(actor=organizer, hackathon_id=hackathon.id)

    assert result["by_country"] == [{"label": "ET", "count": 10}]


def test_demographics_folds_small_buckets_into_other(hackathon, organizer):
    for i in range(10):
        RegistrationFactory(
            hackathon=hackathon,
            user=AccountFactory(university="Addis Ababa University"),
        )
    # A university with only 2 registrants -- below BR-011's per-bucket
    # floor even though the hackathon overall clears 10 registrations.
    for i in range(2):
        RegistrationFactory(
            hackathon=hackathon,
            user=AccountFactory(university="Small College"),
        )

    result = services.get_demographic_breakdown(actor=organizer, hackathon_id=hackathon.id)

    assert result["current_count"] == 12
    assert result["by_university"] == [
        {"label": "Addis Ababa University", "count": 10},
        {"label": "Other", "count": 2},
    ]


def test_demographics_excludes_withdrawn_registrants(hackathon, organizer):
    for i in range(10):
        RegistrationFactory(hackathon=hackathon)
    WithdrawnRegistrationFactory(hackathon=hackathon)

    result = services.get_demographic_breakdown(actor=organizer, hackathon_id=hackathon.id)

    assert result["current_count"] == 10