"""
API / contract-level tests against apps/teams/urls.py + views.py.

Level, per Document 07 Sec 2's test pyramid: "API / contract -- views.py
and serializers.py via the DRF test client against Document 04's
contract. Verifies HTTP status codes, the shared error envelope (Document
03 Sec 6.5), and authorization behavior (Sec 8) at the boundary a real
client hits." That's the job of this file -- NOT re-proving every
business rule already covered in test_services.py. One happy path + the
contract-relevant error paths per endpoint is the target; exhaustive rule
branches (invitation expiry, ownership transfer on leave, etc.) stay in
test_services.py.

Endpoint mapping (none of these are in Document 04 yet -- see the
"Not yet in Doc 04/contracts/openapi.yaml" comments in views.py):
    POST   /teams/hackathons/{hackathonId}              -> FR-TEAM-001
    GET    /teams/{teamId}                               -> FR-TEAM-005
    POST   /teams/{teamId}/invitations                   -> FR-TEAM-002
    GET    /teams/{teamId}/invitations                   -> FR-TEAM-002 (owner-only list)
    POST   /teams/invitations/{invitationId}/accept       -> FR-TEAM-003
    POST   /teams/invitations/{invitationId}/decline      -> FR-TEAM-003
    GET    /teams/invitations/me                          -> supporting view
    POST   /teams/{teamId}/leave                          -> FR-TEAM-004
    DELETE /teams/{teamId}/members/{userId}               -> FR-TEAM-004
"""

import uuid

import pytest
from rest_framework import status

from apps.accounts.tests.factories import AccountFactory, RoleAssignmentFactory
from apps.registrations.tests.factories import RegistrationFactory

from .factories import AcceptedTeamMemberFactory, TeamFactory, TeamMemberFactory

pytestmark = pytest.mark.django_db

# ---------------------------------------------------------------------------
# POST /teams/hackathons/{hackathonId} -- FR-TEAM-001
# ---------------------------------------------------------------------------


class TestTeamCreateEndpoint:
    def url_for(self, hackathon):
        return f"/api/v1/teams/hackathons/{hackathon.id}"

    def test_requires_authentication(self, api_client, hackathon):
        response = api_client.post(self.url_for(hackathon), {"teamName": "Byte Busters"}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_returns_201_with_team_body(self, api_client, owner, owner_registration, hackathon, auth_headers):
        response = api_client.post(
            self.url_for(hackathon), {"teamName": "Byte Busters"}, format="json", **auth_headers(owner),
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        # Contract shape is camelCase, not a raw model dump.
        assert body["teamName"] == "Byte Busters"
        assert body["leaderUserId"] == str(owner.id)
        assert body["memberCount"] == 1

    def test_unregistered_actor_returns_400(self, api_client, owner, hackathon, auth_headers):
        # No owner_registration fixture -- owner isn't registered for
        # this hackathon.
        response = api_client.post(
            self.url_for(hackathon), {"teamName": "Byte Busters"}, format="json", **auth_headers(owner),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_already_on_a_team_returns_409(self, api_client, owner, hackathon, owner_registration, team, auth_headers):
        response = api_client.post(
            self.url_for(hackathon), {"teamName": "Second Team"}, format="json", **auth_headers(owner),
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["error"]["code"] == "CONFLICT"

    def test_duplicate_team_name_returns_409(self, api_client, hackathon, team, auth_headers):
        other = AccountFactory()
        RegistrationFactory(user=other, hackathon=hackathon)

        response = api_client.post(
            self.url_for(hackathon), {"teamName": team.team_name}, format="json", **auth_headers(other),
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_too_short_team_name_returns_400_validation_envelope(self, api_client, owner, owner_registration, hackathon, auth_headers):
        response = api_client.post(
            self.url_for(hackathon), {"teamName": "AB"}, format="json", **auth_headers(owner),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert "teamName" in error["details"]

    def test_nonexistent_hackathon_returns_404(self, api_client, owner, auth_headers):
        response = api_client.post(
            f"/api/v1/teams/hackathons/{uuid.uuid4()}", {"teamName": "Byte Busters"}, format="json",
            **auth_headers(owner),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# GET /teams/{teamId} -- FR-TEAM-005
# ---------------------------------------------------------------------------


class TestTeamDetailEndpoint:
    def url_for(self, team):
        return f"/api/v1/teams/{team.id}"

    def test_requires_authentication(self, api_client, team):
        response = api_client.get(self.url_for(team))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_member_gets_200_with_roster_envelope(self, api_client, owner, team, auth_headers):
        response = api_client.get(self.url_for(team), **auth_headers(owner))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["team"]["id"] == str(team.id)
        assert len(body["members"]) == 1
        assert body["members"][0]["userId"] == str(owner.id)
        assert body["members"][0]["role"] == "owner"

    def test_organizer_gets_200(self, api_client, team, hackathon, auth_headers):
        organizer = AccountFactory()
        RoleAssignmentFactory(
            user=organizer, role="organizer", scope_type="hackathon", scope_id=str(hackathon.id),
        )
        response = api_client.get(self.url_for(team), **auth_headers(organizer))
        assert response.status_code == status.HTTP_200_OK

    def test_non_member_non_organizer_returns_403(self, api_client, team, auth_headers):
        outsider = AccountFactory()
        response = api_client.get(self.url_for(team), **auth_headers(outsider))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_nonexistent_team_returns_404(self, api_client, owner, auth_headers):
        response = api_client.get(f"/api/v1/teams/{uuid.uuid4()}", **auth_headers(owner))
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# POST/GET /teams/{teamId}/invitations -- FR-TEAM-002
# ---------------------------------------------------------------------------


class TestTeamInvitationEndpoint:
    def url_for(self, team):
        return f"/api/v1/teams/{team.id}/invitations"

    def test_requires_authentication(self, api_client, team):
        response = api_client.post(self.url_for(team), {"inviteeEmail": "a@example.com"}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_owner_invite_returns_201_with_member_body(self, api_client, owner, team, hackathon, auth_headers):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)

        response = api_client.post(
            self.url_for(team), {"inviteeEmail": invitee.email}, format="json", **auth_headers(owner),
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["inviteeEmail"] == invitee.email
        assert body["joinStatus"] == "pending"

    def test_non_owner_returns_403(self, api_client, team, hackathon, auth_headers):
        non_owner = AccountFactory()
        RegistrationFactory(user=non_owner, hackathon=hackathon)
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)

        response = api_client.post(
            self.url_for(team), {"inviteeEmail": invitee.email}, format="json", **auth_headers(non_owner),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unregistered_invitee_returns_400(self, api_client, owner, team, auth_headers):
        invitee = AccountFactory()  # not registered for this hackathon

        response = api_client.post(
            self.url_for(team), {"inviteeEmail": invitee.email}, format="json", **auth_headers(owner),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_email_returns_400_validation_envelope(self, api_client, owner, team, auth_headers):
        response = api_client.post(
            self.url_for(team), {"inviteeEmail": "nobody@example.com"}, format="json", **auth_headers(owner),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert "inviteeEmail" in error["details"]

    def test_invitee_already_on_a_team_returns_400_with_rule_detail(self, api_client, owner, team, hackathon, auth_headers):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        other_team = TeamFactory(hackathon=hackathon)
        AcceptedTeamMemberFactory(team=other_team, hackathon=hackathon, user=invitee)

        response = api_client.post(
            self.url_for(team), {"inviteeEmail": invitee.email}, format="json", **auth_headers(owner),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"]["details"]["invitee"]["rule"] == "already_on_team"

    def test_duplicate_pending_invitation_returns_409(self, api_client, owner, team, hackathon, auth_headers):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        TeamMemberFactory(team=team, hackathon=hackathon, user=invitee, invitee_email=invitee.email)

        response = api_client.post(
            self.url_for(team), {"inviteeEmail": invitee.email}, format="json", **auth_headers(owner),
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_owner_can_list_pending_invitations(self, api_client, owner, team, hackathon, auth_headers):
        TeamMemberFactory(team=team, hackathon=hackathon)

        response = api_client.get(self.url_for(team), **auth_headers(owner))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == 1
        assert body[0]["joinStatus"] == "pending"

    def test_non_owner_list_returns_403(self, api_client, team, hackathon, auth_headers):
        non_owner = AccountFactory()
        RegistrationFactory(user=non_owner, hackathon=hackathon)

        response = api_client.get(self.url_for(team), **auth_headers(non_owner))
        assert response.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# POST /teams/invitations/{invitationId}/accept -- FR-TEAM-003
# ---------------------------------------------------------------------------


class TestAcceptInvitationEndpoint:
    def url_for(self, invitation):
        return f"/api/v1/teams/invitations/{invitation.id}/accept"

    def test_requires_authentication(self, api_client, team, hackathon):
        invitation = TeamMemberFactory(team=team, hackathon=hackathon)
        response = api_client.post(self.url_for(invitation))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_invitee_accept_returns_200(self, api_client, team, hackathon, auth_headers):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        invitation = TeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        response = api_client.post(self.url_for(invitation), **auth_headers(invitee))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["joinStatus"] == "accepted"

    def test_invitation_addressed_to_someone_else_returns_404(self, api_client, team, hackathon, auth_headers):
        invitation = TeamMemberFactory(team=team, hackathon=hackathon)
        outsider = AccountFactory()

        response = api_client.post(self.url_for(invitation), **auth_headers(outsider))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_already_responded_returns_400(self, api_client, team, hackathon, auth_headers):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        invitation = TeamMemberFactory(
            team=team, hackathon=hackathon, user=invitee, join_status="declined",
        )

        response = api_client.post(self.url_for(invitation), **auth_headers(invitee))
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# POST /teams/invitations/{invitationId}/decline -- FR-TEAM-003
# ---------------------------------------------------------------------------


class TestDeclineInvitationEndpoint:
    def url_for(self, invitation):
        return f"/api/v1/teams/invitations/{invitation.id}/decline"

    def test_requires_authentication(self, api_client, team, hackathon):
        invitation = TeamMemberFactory(team=team, hackathon=hackathon)
        response = api_client.post(self.url_for(invitation))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_invitee_decline_returns_200(self, api_client, team, hackathon, auth_headers):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        invitation = TeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        response = api_client.post(self.url_for(invitation), **auth_headers(invitee))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["joinStatus"] == "declined"

    def test_already_responded_returns_400(self, api_client, team, hackathon, auth_headers):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        invitation = TeamMemberFactory(
            team=team, hackathon=hackathon, user=invitee, join_status="accepted",
        )

        response = api_client.post(self.url_for(invitation), **auth_headers(invitee))
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# GET /teams/invitations/me
# ---------------------------------------------------------------------------


class TestMyInvitationsEndpoint:
    url = "/api/v1/teams/invitations/me"

    def test_requires_authentication(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_returns_only_invitations_addressed_to_caller(self, api_client, team, hackathon, auth_headers):
        me = AccountFactory()
        RegistrationFactory(user=me, hackathon=hackathon)
        TeamMemberFactory(team=team, hackathon=hackathon, user=me)
        TeamMemberFactory(team=team, hackathon=hackathon)  # someone else's invite

        response = api_client.get(self.url, **auth_headers(me))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == 1
        assert body[0]["userId"] == str(me.id)


# ---------------------------------------------------------------------------
# POST /teams/{teamId}/leave -- FR-TEAM-004
# ---------------------------------------------------------------------------


class TestLeaveTeamEndpoint:
    def url_for(self, team):
        return f"/api/v1/teams/{team.id}/leave"

    def test_requires_authentication(self, api_client, team):
        response = api_client.post(self.url_for(team))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_member_leave_returns_204(self, api_client, team, hackathon, auth_headers):
        member = AccountFactory()
        RegistrationFactory(user=member, hackathon=hackathon)
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member)

        response = api_client.post(self.url_for(team), **auth_headers(member))
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_non_member_returns_404(self, api_client, team, auth_headers):
        outsider = AccountFactory()
        response = api_client.post(self.url_for(team), **auth_headers(outsider))
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# DELETE /teams/{teamId}/members/{userId} -- FR-TEAM-004
# ---------------------------------------------------------------------------


class TestRemoveMemberEndpoint:
    def url_for(self, team, user):
        return f"/api/v1/teams/{team.id}/members/{user.id}"

    def test_requires_authentication(self, api_client, team, owner):
        response = api_client.delete(self.url_for(team, owner))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_owner_removes_member_returns_204(self, api_client, owner, team, hackathon, auth_headers):
        member = AccountFactory()
        RegistrationFactory(user=member, hackathon=hackathon)
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member)

        response = api_client.delete(self.url_for(team, member), **auth_headers(owner))
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_non_owner_returns_403(self, api_client, team, hackathon, auth_headers):
        member = AccountFactory()
        RegistrationFactory(user=member, hackathon=hackathon)
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member)
        other = AccountFactory()
        RegistrationFactory(user=other, hackathon=hackathon)

        response = api_client.delete(self.url_for(team, member), **auth_headers(other))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_owner_removing_self_returns_400(self, api_client, owner, team, auth_headers):
        response = api_client.delete(self.url_for(team, owner), **auth_headers(owner))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_nonexistent_member_returns_404(self, api_client, owner, team, auth_headers):
        response = api_client.delete(self.url_for(team, AccountFactory()), **auth_headers(owner))
        assert response.status_code == status.HTTP_404_NOT_FOUND