"""factory-boy factories for apps.showcase models."""

import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import AccountFactory

from ..models import ShowcaseOverride


class ShowcaseOverrideFactory(DjangoModelFactory):
    class Meta:
        model = ShowcaseOverride

    hackathon = factory.SubFactory("apps.hackathons.tests.factories.HackathonFactory")
    submission = factory.SubFactory("apps.submissions.tests.factories.SubmissionFactory")
    is_visible = True
    reason = "Reviewed manually by the organizer."
    created_by = factory.SubFactory(AccountFactory)