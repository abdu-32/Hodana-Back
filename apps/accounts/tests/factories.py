"""
factory-boy factories for apps.accounts models.

Per requirements/development.txt, factory-boy is the declared fixture-data
tool for this project -- use these instead of hand-rolled
Account.objects.create_user(...) calls scattered across test modules.
"""

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.models import Account, Badge, RoleAssignment

# FR-AUTH-001: >=10 chars, >=1 letter, >=1 digit.
DEFAULT_PASSWORD = "correct-horse-99"


class AccountFactory(DjangoModelFactory):
    """Defaults to a `verified`, active account -- the shape most tests
    (login, profile, public-profile) actually want. Use
    UnverifiedAccountFactory for FR-AUTH-003 flows."""

    class Meta:
        model = Account
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    full_name = factory.Faker("name")
    verification_status = "verified"
    profile_visibility = "public"

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        """Pass password=... to override; defaults to DEFAULT_PASSWORD.
        Plain `password = factory.PostGenerationMethodCall("set_password", ...)`
        won't work here since we need the raw value back out in tests too --
        callers that need the raw password should pass it in explicitly and
        keep their own reference to it, rather than relying on this factory
        to hand it back."""
        raw = extracted or DEFAULT_PASSWORD
        self.set_password(raw)
        if create:
            self.save(update_fields=["password"])


class UnverifiedAccountFactory(AccountFactory):
    """FR-AUTH-001: freshly registered, not yet through FR-AUTH-003."""

    verification_status = "unverified"


class PrivateAccountFactory(AccountFactory):
    """FR-PROFILE-002: profile_visibility=private -- get_public_profile
    must 404 on these."""

    profile_visibility = "private"


class BadgeFactory(DjangoModelFactory):
    class Meta:
        model = Badge

    user = factory.SubFactory(AccountFactory)
    type = "verified_student"
    awarded_at = factory.LazyFunction(timezone.now)


class RoleAssignmentFactory(DjangoModelFactory):
    class Meta:
        model = RoleAssignment

    user = factory.SubFactory(AccountFactory)
    role = "organizer"
    scope_type = "organization"
    scope_id = factory.Faker("uuid4")