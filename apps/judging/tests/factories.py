"""factory-boy factories for apps.judging models."""

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import AccountFactory
from apps.hackathons.tests.factories import HackathonFactory

from ..models import (
    JudgeInvitation, JudgingAssignment, JudgingCriterion, JudgingRound,
    RoundResult, Score,
)


class JudgingRoundFactory(DjangoModelFactory):
    class Meta:
        model = JudgingRound

    hackathon = factory.SubFactory(HackathonFactory)
    track = None
    status = "not_started"


class JudgingCriterionFactory(DjangoModelFactory):
    class Meta:
        model = JudgingCriterion

    round = factory.SubFactory(JudgingRoundFactory)
    name = factory.Sequence(lambda n: f"Criterion {n}")
    min_score = 0
    max_score = 10
    weight = 100


class JudgeInvitationFactory(DjangoModelFactory):
    class Meta:
        model = JudgeInvitation

    round = factory.SubFactory(JudgingRoundFactory)
    email = factory.Sequence(lambda n: f"judge{n}@example.com")
    status = "accepted"
    invited_at = factory.LazyFunction(timezone.now)
    responded_at = factory.LazyFunction(timezone.now)


class JudgingAssignmentFactory(DjangoModelFactory):
    class Meta:
        model = JudgingAssignment

    round = factory.SubFactory(JudgingRoundFactory)
    submission = factory.SubFactory("apps.submissions.tests.factories.SubmissionFactory")
    judge_user = factory.SubFactory(AccountFactory)
    assigned_at = factory.LazyFunction(timezone.now)


class ScoreFactory(DjangoModelFactory):
    class Meta:
        model = Score

    submission = factory.SubFactory("apps.submissions.tests.factories.SubmissionFactory")
    judge_user = factory.SubFactory(AccountFactory)
    criterion = factory.SubFactory(JudgingCriterionFactory)
    score_value = 5
    comment = ""
    status = "final"
    finalized_at = factory.LazyFunction(timezone.now)


class RoundResultFactory(DjangoModelFactory):
    class Meta:
        model = RoundResult

    round = factory.SubFactory(JudgingRoundFactory)
    submission = factory.SubFactory("apps.submissions.tests.factories.SubmissionFactory")
    aggregate_score = 5
    rank = 1
    calculated_at = factory.LazyFunction(timezone.now)
