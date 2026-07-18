"""
Unit tests against core/managers.py (TenantScopedManager) directly
(Design Spec Sec 3.1 / Sec 3.3), per the 80% coverage target in
NFR-MAINT-001.

Exercised against real tenant-scoped models (hackathons.Hackathon,
hackathons.ChallengeTrack, registrations.Registration) rather than a
throwaway test-only model, since the guarantee that matters is "the real
managers in this codebase behave correctly," not "the base class works in
isolation."
"""

import pytest

from apps.core.managers import TenantScopedManager
from apps.hackathons.models import ChallengeTrack, Hackathon
from apps.hackathons.tests.factories import ChallengeTrackFactory, HackathonFactory
from apps.organizations.tests.factories import VerifiedOrganizationFactory
from apps.registrations.models import Registration
from apps.registrations.tests.factories import RegistrationFactory

# ---------------------------------------------------------------------------
# The declaration guarantee: raises if scope_field is unset
# ---------------------------------------------------------------------------


class TestScopeFieldDeclarationGuarantee:
    def test_missing_scope_field_raises_not_implemented_error(self):
        manager = TenantScopedManager()
        with pytest.raises(NotImplementedError):
            manager.get_queryset()

    def test_scoped_to_also_raises_when_scope_field_is_unset(self):
        manager = TenantScopedManager()
        with pytest.raises(NotImplementedError):
            manager.scoped_to("00000000-0000-0000-0000-000000000000")

    @pytest.mark.django_db
    def test_declared_scope_field_does_not_raise(self):
        """Sanity check on the guard's condition itself -- a real
        subclass with scope_field set must not trip this at all."""
        assert Hackathon.objects.get_queryset().exists() in (True, False)  # no raise
        
# ---------------------------------------------------------------------------
# The filtering guarantee: scoped_to() actually scopes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestScopedToFiltersByDeclaredField:
    def test_hackathon_scoped_to_returns_only_that_organizations_hackathons(self):
        org_a = VerifiedOrganizationFactory()
        org_b = VerifiedOrganizationFactory()
        hackathon_a = HackathonFactory(host_org=org_a)
        HackathonFactory(host_org=org_b)  # a second org's hackathon -- must not leak in

        results = list(Hackathon.objects.scoped_to(org_a.id))

        assert results == [hackathon_a]

    def test_hackathon_scoped_to_returns_empty_for_org_with_no_hackathons(self):
        org = VerifiedOrganizationFactory()
        assert list(Hackathon.objects.scoped_to(org.id)) == []

    def test_challenge_track_scoped_to_returns_only_that_hackathons_tracks(self):
        hackathon_a = HackathonFactory()
        hackathon_b = HackathonFactory()
        track_a = ChallengeTrackFactory(hackathon=hackathon_a)
        ChallengeTrackFactory(hackathon=hackathon_b)  # different hackathon -- must not leak in

        results = list(ChallengeTrack.objects.scoped_to(hackathon_a.id))

        assert results == [track_a]

    def test_registration_scoped_to_returns_only_that_hackathons_registrations(self):
        hackathon_a = HackathonFactory(status="published")
        hackathon_b = HackathonFactory(status="published")
        registration_a = RegistrationFactory(hackathon=hackathon_a)
        RegistrationFactory(hackathon=hackathon_b)  # different hackathon -- must not leak in

        results = list(Registration.objects.scoped_to(hackathon_a.id))

        assert results == [registration_a]

    def test_scoped_to_uses_the_id_suffix_not_the_object(self):
        """scoped_to() is documented to take a tenant_id (a UUID/str), not
        the related object itself -- this locks that contract in so a
        future refactor of the manager can't silently start requiring the
        object instead without a test failing here."""
        hackathon = HackathonFactory()
        track = ChallengeTrackFactory(hackathon=hackathon)

        results = list(ChallengeTrack.objects.scoped_to(str(hackathon.id)))

        assert results == [track]