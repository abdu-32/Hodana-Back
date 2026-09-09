"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
"""

from rest_framework import serializers

from .models import Registration


class RegisterForHackathonSerializer(serializers.Serializer):
    """POST /registrations/hackathons/{hackathonId} -- FR-REG-001."""

    eligibilityConfirmed = serializers.BooleanField(
        source="eligibility_confirmed", required=False, default=False,
    )
    customAnswers = serializers.JSONField(
        source="custom_answers", required=False, allow_null=True,
    )
    registrationType = serializers.ChoiceField(
        choices=["solo", "looking_for_team", "create_team"],
        source="registration_type",
        required=False,
        default="solo",
    )
    teamName = serializers.CharField(
        source="team_name", required=False, allow_blank=True, max_length=60,
    )
    teamDescription = serializers.CharField(
        source="team_description", required=False, allow_blank=True, default="",
    )


class UpdateRegistrationTypeSerializer(serializers.Serializer):
    """PATCH /registrations/hackathons/{hackathonId}/type"""

    registrationType = serializers.ChoiceField(
        choices=["solo", "looking_for_team", "create_team"],
        source="registration_type",
        required=True,
    )


class RegistrationSerializer(serializers.ModelSerializer):
    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True)
    hackathonTitle = serializers.CharField(source="hackathon.title", read_only=True)
    hackathonSlug = serializers.CharField(source="hackathon.slug", read_only=True)
    hackathonBannerUrl = serializers.CharField(source="hackathon.banner_url", read_only=True, allow_blank=True)
    hackathonLocation = serializers.SerializerMethodField()
    hackathonStartDate = serializers.DateTimeField(source="hackathon.submission_opens_at", read_only=True)
    hackathonEndDate = serializers.DateTimeField(source="hackathon.submission_closes_at", read_only=True)
    hackathon = serializers.SerializerMethodField()
    team = serializers.SerializerMethodField()
    userId = serializers.UUIDField(source="user_id", read_only=True)
    eligibilityConfirmed = serializers.BooleanField(source="eligibility_confirmed", read_only=True)
    customAnswers = serializers.JSONField(source="custom_answers", read_only=True)
    registrationType = serializers.CharField(source="registration_type", read_only=True)
    verificationStatus = serializers.CharField(source="verification_status", read_only=True)
    registeredAt = serializers.DateTimeField(source="registered_at", read_only=True)
    withdrawnAt = serializers.DateTimeField(source="withdrawn_at", read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Registration
        fields = [
            "id", "hackathonId", "hackathonTitle", "hackathonSlug", "hackathonBannerUrl",
            "hackathonLocation", "hackathonStartDate", "hackathonEndDate", "hackathon",
            "userId", "eligibilityConfirmed", "customAnswers",
            "registrationType", "verificationStatus", "registeredAt", "withdrawnAt", "status",
            "team",
        ]

    def get_hackathonLocation(self, obj):
        if not obj.hackathon:
            return ""
        if getattr(obj.hackathon, "location_mode", "") == "online":
            return "Online"
        parts = [p for p in [getattr(obj.hackathon, "venue", ""), getattr(obj.hackathon, "location_name", "")] if p]
        return ", ".join(parts) if parts else getattr(obj.hackathon, "location_mode", "").replace("_", " ").title()

    def get_hackathon(self, obj):
        if not obj.hackathon:
            return None
        h = obj.hackathon
        return {
            "id": str(h.id),
            "title": h.title,
            "slug": h.slug,
            "bannerUrl": h.banner_url,
            "status": h.status,
            "locationMode": h.location_mode,
            "locationName": h.location_name,
            "venue": h.venue,
            "registrationOpensAt": h.registration_opens_at.isoformat() if h.registration_opens_at else None,
            "registrationClosesAt": h.registration_closes_at.isoformat() if h.registration_closes_at else None,
            "submissionOpensAt": h.submission_opens_at.isoformat() if h.submission_opens_at else None,
            "submissionClosesAt": h.submission_closes_at.isoformat() if h.submission_closes_at else None,
        }

    def get_team(self, obj):
        try:
            from apps.teams.models import TeamMember
            membership = TeamMember.objects.select_related("team").filter(
                user=obj.user, hackathon=obj.hackathon
            ).first()
            if membership and membership.team:
                is_leader = membership.team.leader_user_id == obj.user.id
                return {
                    "id": str(membership.team.id),
                    "name": membership.team.team_name,
                    "isLeader": is_leader,
                    "role": "Team Leader" if is_leader else "Member",
                }
        except Exception:
            pass
        return None


class OrganizerRegistrationSerializer(serializers.ModelSerializer):
    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True)
    hackathonTitle = serializers.CharField(source="hackathon.title", read_only=True)
    hackathonSlug = serializers.CharField(source="hackathon.slug", read_only=True)
    userId = serializers.UUIDField(source="user_id", read_only=True)
    
    # Profile information
    participantName = serializers.SerializerMethodField()
    email = serializers.EmailField(source="user.email", read_only=True)
    phoneNumber = serializers.CharField(source="user.phone_number", read_only=True, allow_null=True)
    country = serializers.CharField(source="user.country", read_only=True, allow_null=True)
    city = serializers.CharField(source="user.city", read_only=True, allow_null=True)
    avatarUrl = serializers.CharField(source="user.avatar_url", read_only=True, allow_null=True)
    university = serializers.CharField(source="user.university", read_only=True, allow_null=True)
    organization = serializers.CharField(source="user.organization", read_only=True, allow_null=True)
    department = serializers.CharField(source="user.department", read_only=True, allow_null=True)
    fieldOfStudy = serializers.CharField(source="user.field_of_study", read_only=True, allow_null=True)
    profession = serializers.CharField(source="user.profession", read_only=True, allow_null=True)
    role = serializers.SerializerMethodField()
    professionalTitle = serializers.CharField(source="user.professional_title", read_only=True, allow_null=True)
    experienceLevel = serializers.CharField(source="user.experience_level", read_only=True, allow_null=True)
    yearsOfExperience = serializers.IntegerField(source="user.years_of_experience", read_only=True, allow_null=True)
    skills = serializers.ListField(source="user.skills", child=serializers.CharField(), read_only=True)
    bio = serializers.CharField(source="user.bio", read_only=True, allow_null=True)
    
    # Social links
    linkedinUrl = serializers.CharField(source="user.linkedin_url", read_only=True, allow_null=True)
    githubUrl = serializers.CharField(source="user.github_url", read_only=True, allow_null=True)
    websiteUrl = serializers.CharField(source="user.website_url", read_only=True, allow_null=True)
    twitterUrl = serializers.CharField(source="user.twitter_url", read_only=True, allow_null=True)
    instagramUrl = serializers.CharField(source="user.instagram_url", read_only=True, allow_null=True)
    
    # Team collaboration preferences
    interestedInTeams = serializers.CharField(source="user.interested_in_teams", read_only=True, allow_null=True)
    lookingForTeammates = serializers.BooleanField(source="user.looking_for_teammates", read_only=True)
    teamSeekingDescription = serializers.CharField(source="user.team_seeking_description", read_only=True, allow_null=True)
    preferredTeamRoles = serializers.ListField(source="user.preferred_team_roles", child=serializers.CharField(), read_only=True)
    
    # Team in this hackathon
    team = serializers.SerializerMethodField()
    
    # Application specifics
    registrationType = serializers.CharField(source="registration_type", read_only=True)
    eligibilityConfirmed = serializers.BooleanField(source="eligibility_confirmed", read_only=True)
    verificationStatus = serializers.CharField(source="verification_status", read_only=True)
    customAnswers = serializers.JSONField(source="custom_answers", read_only=True)
    registeredAt = serializers.DateTimeField(source="registered_at", read_only=True)
    withdrawnAt = serializers.DateTimeField(source="withdrawn_at", read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Registration
        fields = [
            "id", "hackathonId", "hackathonTitle", "hackathonSlug", "userId",
            "participantName", "email", "phoneNumber", "country", "city", "avatarUrl",
            "university", "organization", "department", "fieldOfStudy", "profession", "role",
            "professionalTitle", "experienceLevel", "yearsOfExperience", "skills", "bio",
            "linkedinUrl", "githubUrl", "websiteUrl", "twitterUrl", "instagramUrl",
            "interestedInTeams", "lookingForTeammates", "teamSeekingDescription", "preferredTeamRoles",
            "team", "registrationType", "eligibilityConfirmed", "verificationStatus", "customAnswers",
            "registeredAt", "withdrawnAt", "status",
        ]

    def get_participantName(self, obj):
        return obj.user.full_name or obj.user.email.split("@")[0]

    def get_role(self, obj):
        return obj.user.profession or getattr(obj.user, "role", "") or "Participant"

    def get_team(self, obj):
        # Check team membership for this user in this hackathon
        try:
            from apps.teams.models import TeamMember
            membership = TeamMember.objects.select_related("team").filter(
                user=obj.user, hackathon=obj.hackathon
            ).first()
            if membership and membership.team:
                is_leader = membership.team.leader_user_id == obj.user.id
                return {
                    "id": str(membership.team.id),
                    "name": membership.team.team_name,
                    "isLeader": is_leader,
                    "role": "Team Leader" if is_leader else "Member",
                }
        except Exception:
            pass
        return None