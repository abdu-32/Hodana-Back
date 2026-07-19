"""factory-boy factories for apps.submissions models."""

import factory
from factory.django import DjangoModelFactory

from apps.teams.tests.factories import TeamFactory

from ..models import Submission, SubmissionVersion


class SubmissionFactory(DjangoModelFactory):
    """Defaults to a complete-enough draft (title, description, repo
    link) so finalize-focused tests don't need to fill in FR-SUB-001's
    required fields themselves."""

    class Meta:
        model = Submission

    team = factory.SubFactory(TeamFactory)
    hackathon = factory.LazyAttribute(lambda o: o.team.hackathon)
    title = factory.Sequence(lambda n: f"Project {n}")
    tagline = "A test project."
    description = "A test project description."
    technologies = factory.LazyFunction(lambda: ["python", "django"])
    repo_link = "https://github.com/example/project"


class SubmissionVersionFactory(DjangoModelFactory):
    class Meta:
        model = SubmissionVersion

    submission = factory.SubFactory(SubmissionFactory)
    title = factory.LazyAttribute(lambda o: o.submission.title)
    description = "An earlier draft description."