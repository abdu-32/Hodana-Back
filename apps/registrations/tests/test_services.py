"""
Unit tests against registrations/services.py directly (Design Spec Sec 3.1),
per the 80% coverage target in NFR-MAINT-001. Prefer these over
HTTP-level tests for business-rule coverage.

Test IDs in each docstring/comment match Document 07 Sec 6's named cases
(TC-REG-*) where one exists; additional cases beyond that representative
list are included for branch coverage of services.py.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.exceptions import NotFound, ValidationError

from apps.core.models import AuditLogEntry
from apps.hackathons.tests.factories import HackathonFactory, PublishedHackathonFactory
from apps.organizations.tests.factories import VerifiedOrganizationFactory
from apps.registrations import services
from apps.registrations.models import Registration
from apps.accounts.tests.factories import AccountFactory

from .factories import RegistrationFactory, WithdrawnRegistrationFactory

# ---------------------------------------------------------------------------
# FR-REG-001: register for a hackathon
# ---------------------------------------------------------------------------


class TestRegisterForHackathon:
    def test_creates_registration_for_participant(self, participant, published_hackathon):
        registration = services.register_for_hackathon(
            actor=participant, hackathon_id=published_hackathon.id,
        )

        assert registration.hackathon_id == published_hackathon.id
        assert registration.user_id == participant.id
        assert registration.status == "registered"
        assert registration.withdrawn_at is None

    def test_stores_eligibility_confirmed_and_custom_answers(self, participant, published_hackathon):
        registration = services.register_for_hackathon(
            actor=participant,
            hackathon_id=published_hackathon.id,
            eligibility_confirmed=True,
            custom_answers={"dietary": "vegetarian"},
        )

        assert registration.eligibility_confirmed is True
        assert registration.custom_answers == {"dietary": "vegetarian"}

    def test_writes_audit_log_entry(self, participant, published_hackathon):
        registration = services.register_for_hackathon(
            actor=participant, hackathon_id=published_hackathon.id,
        )

        assert AuditLogEntry.objects.filter(
            action="registration.created", target_id=str(registration.id),
        ).exists()

    def test_sends_confirmation_email(self, participant, published_hackathon, mailoutbox):
        services.register_for_hackathon(actor=participant, hackathon_id=published_hackathon.id)

        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [participant.email]
        assert published_hackathon.title in mailoutbox[0].subject

    def test_falls_back_to_account_email_when_no_contact_email_set(self, participant, published_hackathon, mailoutbox):
        participant.contact_email = None
        participant.save(update_fields=["contact_email"])

        services.register_for_hackathon(actor=participant, hackathon_id=published_hackathon.id)

        assert mailoutbox[0].to == [participant.email]

    def test_uses_contact_email_when_set(self, participant, published_hackathon, mailoutbox):
        participant.contact_email = "alt@example.com"
        participant.save(update_fields=["contact_email"])

        services.register_for_hackathon(actor=participant, hackathon_id=published_hackathon.id)

        assert mailoutbox[0].to == ["alt@example.com"]

    def test_nonexistent_hackathon_raises_not_found(self, participant):
        with pytest.raises(NotFound):
            services.register_for_hackathon(actor=participant, hackathon_id=uuid.uuid4())

    def test_malformed_hackathon_id_raises_not_found_not_a_500(self, participant):
        with pytest.raises(NotFound):
            services.register_for_hackathon(actor=participant, hackathon_id="not-a-uuid")

    def test_draft_hackathon_is_rejected(self, participant):
        hackathon = HackathonFactory(status="draft")
        with pytest.raises(ValidationError):
            services.register_for_hackathon(actor=participant, hackathon_id=hackathon.id)

    def test_TC_REG_001a_duplicate_registration_returns_409(self, participant, published_hackathon):
        services.register_for_hackathon(actor=participant, hackathon_id=published_hackathon.id)

        with pytest.raises(services.ConflictError) as exc_info:
            services.register_for_hackathon(actor=participant, hackathon_id=published_hackathon.id)
        assert exc_info.value.status_code == 409

    def test_TC_REG_001b_registration_before_window_opens_is_rejected(self, participant):
        hackathon = PublishedHackathonFactory(
            registration_opens_at=timezone.now() + timedelta(days=1),
            registration_closes_at=timezone.now() + timedelta(days=8),
            submission_opens_at=timezone.now() + timedelta(days=8),
            submission_closes_at=timezone.now() + timedelta(days=15),
        )
        with pytest.raises(ValidationError):
            services.register_for_hackathon(actor=participant, hackathon_id=hackathon.id)

    def test_TC_REG_001b_registration_after_deadline_rejected_regardless_of_client_clock(self, participant):
        """BR-002: server time is authoritative -- the caller passes no
        client-supplied clock state at all, since register_for_hackathon's
        signature doesn't accept one; freeze_time simulates the deadline
        having already passed server-side."""
        with freeze_time("2026-01-01 00:00:00"):
            hackathon = PublishedHackathonFactory(
                registration_opens_at=timezone.now() - timedelta(days=8),
                registration_closes_at=timezone.now() - timedelta(seconds=1),
                submission_opens_at=timezone.now() + timedelta(days=1),
                submission_closes_at=timezone.now() + timedelta(days=8),
            )
            with pytest.raises(ValidationError):
                services.register_for_hackathon(actor=participant, hackathon_id=hackathon.id)

    def test_registration_exactly_at_close_boundary_is_allowed(self, participant):
        close_at = timezone.now() + timedelta(seconds=30)
        hackathon = PublishedHackathonFactory(
            registration_opens_at=timezone.now() - timedelta(days=1),
            registration_closes_at=close_at,
            submission_opens_at=close_at,
            submission_closes_at=close_at + timedelta(days=7),
        )
        with freeze_time(close_at):
            registration = services.register_for_hackathon(actor=participant, hackathon_id=hackathon.id)
        assert registration.status == "registered"

    def test_institution_restriction_allows_matching_email_domain(self, published_hackathon):

        allowed_org = VerifiedOrganizationFactory(primary_email_domain="aau.edu.et")
        published_hackathon.eligibility_rules = {"institution_restriction": [str(allowed_org.id)]}
        published_hackathon.save(update_fields=["eligibility_rules"])

        student = AccountFactory(email="student@aau.edu.et")
        registration = services.register_for_hackathon(actor=student, hackathon_id=published_hackathon.id)

        assert registration.status == "registered"

    def test_institution_restriction_blocks_non_matching_email_domain(self, published_hackathon):

        allowed_org = VerifiedOrganizationFactory(primary_email_domain="aau.edu.et")
        published_hackathon.eligibility_rules = {"institution_restriction": [str(allowed_org.id)]}
        published_hackathon.save(update_fields=["eligibility_rules"])

        outsider = AccountFactory(email="student@othercollege.edu")

        with pytest.raises(ValidationError) as exc_info:
            services.register_for_hackathon(actor=outsider, hackathon_id=published_hackathon.id)
        assert exc_info.value.detail["eligibility"]["rule"] == "institution_restriction"

    def test_institution_restriction_with_no_declared_domain_blocks_everyone(self, published_hackathon):
        """An org in the restriction list with no primary_email_domain can
        never be matched -- this is a data-entry gap for the Organizer,
        not a bug; documenting the behavior explicitly."""

        undeclared_org = VerifiedOrganizationFactory(primary_email_domain=None)
        published_hackathon.eligibility_rules = {"institution_restriction": [str(undeclared_org.id)]}
        published_hackathon.save(update_fields=["eligibility_rules"])

        anyone = AccountFactory(email="anyone@example.com")

        with pytest.raises(ValidationError):
            services.register_for_hackathon(actor=anyone, hackathon_id=published_hackathon.id)

    def test_no_eligibility_rules_allows_registration(self, participant, published_hackathon):
        published_hackathon.eligibility_rules = None
        published_hackathon.save(update_fields=["eligibility_rules"])

        registration = services.register_for_hackathon(actor=participant, hackathon_id=published_hackathon.id)
        assert registration.status == "registered"

    def test_min_max_team_size_rules_do_not_block_individual_registration(self, participant, published_hackathon):
        """min_team_size/max_team_size are FR-TEAM concerns (enforced by
        apps.teams at team-creation/invite time), not a FR-REG-001 gate --
        registration is per-individual, not per-team."""
        published_hackathon.eligibility_rules = {"min_team_size": 2, "max_team_size": 4}
        published_hackathon.save(update_fields=["eligibility_rules"])

        registration = services.register_for_hackathon(actor=participant, hackathon_id=published_hackathon.id)
        assert registration.status == "registered"


# ---------------------------------------------------------------------------
# FR-REG-002: withdraw registration
# ---------------------------------------------------------------------------


class TestWithdrawRegistration:
    def test_withdrawing_sets_withdrawn_at_and_status(self, participant, registration):
        result = services.withdraw_registration(actor=participant, hackathon_id=registration.hackathon_id)

        assert result.withdrawn_at is not None
        assert result.status == "withdrawn"

    def test_writes_audit_log_entry(self, participant, registration):
        services.withdraw_registration(actor=participant, hackathon_id=registration.hackathon_id)

        assert AuditLogEntry.objects.filter(
            action="registration.withdrawn", target_id=str(registration.id),
        ).exists()

    def test_nonexistent_registration_raises_not_found(self, participant, published_hackathon):
        with pytest.raises(NotFound):
            services.withdraw_registration(actor=participant, hackathon_id=published_hackathon.id)

    def test_withdrawing_someone_elses_registration_raises_not_found(self, registration):
        """FR-REG-003's strict-scoping principle applies here too --
        withdraw is keyed on (actor, hackathon), so another user simply
        has no registration row to find, not a 403."""

        other_user = AccountFactory()
        with pytest.raises(NotFound):
            services.withdraw_registration(actor=other_user, hackathon_id=registration.hackathon_id)

    def test_withdrawing_twice_is_rejected(self, participant, registration):
        services.withdraw_registration(actor=participant, hackathon_id=registration.hackathon_id)

        with pytest.raises(ValidationError):
            services.withdraw_registration(actor=participant, hackathon_id=registration.hackathon_id)

    def test_TC_REG_002a_withdrawal_after_submission_deadline_rejected(self, participant):
        with freeze_time("2026-01-01 00:00:00"):
            hackathon = PublishedHackathonFactory(
                registration_opens_at=timezone.now() - timedelta(days=8),
                registration_closes_at=timezone.now() - timedelta(days=1),
                submission_opens_at=timezone.now() - timedelta(days=1),
                submission_closes_at=timezone.now() - timedelta(seconds=1),
            )
            registration = RegistrationFactory(user=participant, hackathon=hackathon)

            with pytest.raises(ValidationError):
                services.withdraw_registration(actor=participant, hackathon_id=hackathon.id)

        assert registration.status == "registered"  # unchanged by the rejected call

    def test_withdrawal_exactly_before_submission_deadline_is_allowed(self, participant):
        close_at = timezone.now() + timedelta(days=7)
        hackathon = PublishedHackathonFactory(
            submission_opens_at=timezone.now() + timedelta(days=1),
            submission_closes_at=close_at,
        )
        registration = RegistrationFactory(user=participant, hackathon=hackathon)

        with freeze_time(close_at - timedelta(seconds=1)):
            result = services.withdraw_registration(actor=participant, hackathon_id=hackathon.id)

        assert result.status == "withdrawn"


# ---------------------------------------------------------------------------
# FR-REG-003: view my registrations
# ---------------------------------------------------------------------------


class TestListMyRegistrations:
    def test_returns_only_requesters_registrations(self, participant, registration):

        other_user = AccountFactory()
        RegistrationFactory(user=other_user)

        results = list(services.list_my_registrations(actor=participant))

        assert results == [registration]

    def test_returns_empty_list_for_user_with_no_registrations(self):

        lonely_user = AccountFactory()
        assert list(services.list_my_registrations(actor=lonely_user)) == []

    def test_orders_newest_first(self, participant):
        with freeze_time("2026-01-01 00:00:00"):
            older = RegistrationFactory(user=participant)
        with freeze_time("2026-01-02 00:00:00"):
            newer = RegistrationFactory(user=participant)

        results = list(services.list_my_registrations(actor=participant))
        assert results == [newer, older]

    def test_includes_withdrawn_registrations(self, participant):
        withdrawn = WithdrawnRegistrationFactory(user=participant)
        results = list(services.list_my_registrations(actor=participant))
        assert withdrawn in results