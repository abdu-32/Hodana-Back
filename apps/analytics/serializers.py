"""
Request/response shape only (Design Spec Sec 3.1) -- every field here is
computed in services.py, not read off a model, since this app has no
models of its own (see models.py).

Field names are camelCase (the contract shape used across every other
app, e.g. apps.registrations.serializers.RegistrationSerializer /
apps.judging.serializers.JudgingRoundSerializer), mapped via `source=` to
the snake_case keys services.py returns. DRF's default field-level
`get_attribute` does a plain dict lookup on `source` when the instance is
a Mapping, so these serializers work directly against the plain dicts
services.py returns without needing a model or a custom renderer.
"""

from rest_framework import serializers


class RegistrationBucketSerializer(serializers.Serializer):
    """One day's bucket in the FR-ANALYTICS-001 registration-over-time chart."""

    date = serializers.DateField()
    count = serializers.IntegerField()


class RegistrationDashboardSerializer(serializers.Serializer):
    """Implements FR-ANALYTICS-001's registration and conversion dashboard."""

    hackathonId = serializers.UUIDField(source="hackathon_id")
    registrationCount = serializers.IntegerField(source="registration_count")
    registrationsOverTime = RegistrationBucketSerializer(many=True, source="registrations_over_time")
    teamFormationRate = serializers.FloatField(source="team_formation_rate")
    submissionConversionRate = serializers.FloatField(source="submission_conversion_rate")


class DemographicBucketSerializer(serializers.Serializer):
    """One aggregated cohort in a FR-ANALYTICS-002 breakdown -- never
    smaller than BR-011's minimum cohort size (see
    services._bucket_with_privacy_floor)."""

    label = serializers.CharField()
    count = serializers.IntegerField()


class DemographicBreakdownSerializer(serializers.Serializer):
    """Implements FR-ANALYTICS-002. `available=False` (with empty
    breakdown lists) is the BR-011 placeholder for a hackathon that
    hasn't yet cleared the minimum cohort size, not an error response."""

    hackathonId = serializers.UUIDField(source="hackathon_id")
    available = serializers.BooleanField()
    minimumCohortSize = serializers.IntegerField(source="minimum_cohort_size")
    currentCount = serializers.IntegerField(source="current_count")
    byUniversity = DemographicBucketSerializer(many=True, source="by_university")
    bySkill = DemographicBucketSerializer(many=True, source="by_skill")
    byAgeGroup = DemographicBucketSerializer(many=True, source="by_age_group")
    byCountry = DemographicBucketSerializer(many=True, source="by_country")


class PlatformStatsSerializer(serializers.Serializer):
    """Real-time platform-wide statistics for public hero/landing pages."""

    activeDevelopers = serializers.IntegerField(source="active_developers")
    totalRegistrations = serializers.IntegerField(source="total_registrations")
    totalHackathons = serializers.IntegerField(source="total_hackathons")
    totalPrizeVolumeETB = serializers.FloatField(source="total_prize_volume_etb")
    totalProjects = serializers.IntegerField(source="total_projects")
