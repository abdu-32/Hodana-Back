"""
API / contract-level tests against apps/notifications/urls.py + views.py.

Level, per Document 07 Sec 2's test pyramid: "API / contract -- views.py
and serializers.py via the DRF test client against Document 04's
contract." One happy path + the contract-relevant error paths per
endpoint is the target; business-rule branch coverage stays in
test_services.py.

Endpoint mapping:
    POST /notifications                        -> Doc 04 createNotification
    GET  /notifications/me                     -> FR-NOTIFY-001 (not yet in Doc 04; add it)
    POST /notifications/me/{deliveryId}/read   -> FR-NOTIFY-001 (not yet in Doc 04; add it)
"""

import uuid

import pytest
from rest_framework import status

from apps.accounts.tests.factories import AccountFactory
from apps.registrations.tests.factories import RegistrationFactory

from .factories import NotificationDeliveryFactory

pytestmark = pytest.mark.django_db


class TestNotificationCreateEndpoint:
    url = "/api/v1/notifications/"

    def test_requires_authentication(self, api_client, hackathon):
        response = api_client.post(
            self.url, {"hackathonId": str(hackathon.id), "message": "Hi"}, format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_can_broadcast_and_gets_201(
        self, api_client, organizer_account, organizer_role, hackathon, auth_headers, mailoutbox,
    ):
        RegistrationFactory(hackathon=hackathon)

        response = api_client.post(
            self.url,
            {"hackathonId": str(hackathon.id), "message": "Doors open at 9am", "channel": "email"},
            format="json",
            **auth_headers(organizer_account),
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["hackathonId"] == str(hackathon.id)
        assert body["message"] == "Doors open at 9am"
        assert body["channel"] == "email"
        assert len(mailoutbox) == 1

    def test_non_organizer_gets_403(self, api_client, hackathon, auth_headers):
        outsider = AccountFactory()
        response = api_client.post(
            self.url, {"hackathonId": str(hackathon.id), "message": "Hi"}, format="json",
            **auth_headers(outsider),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_nonexistent_hackathon_returns_404(self, api_client, organizer_account, auth_headers):
        response = api_client.post(
            self.url, {"hackathonId": str(uuid.uuid4()), "message": "Hi"}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_missing_message_returns_400_validation_envelope(self, api_client, organizer_account, organizer_role, hackathon, auth_headers):
        response = api_client.post(
            self.url, {"hackathonId": str(hackathon.id)}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestMyNotificationsEndpoint:
    url = "/api/v1/notifications/me"

    def test_requires_authentication(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_returns_only_the_requesters_deliveries(self, api_client, participant, auth_headers):
        mine = NotificationDeliveryFactory(user=participant, channel="in_portal")
        NotificationDeliveryFactory(user=AccountFactory(), channel="in_portal")

        response = api_client.get(self.url, **auth_headers(participant))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["id"] == str(mine.id)

    def test_returns_empty_data_for_user_with_no_notifications(self, api_client, auth_headers):
        lonely_user = AccountFactory()
        response = api_client.get(self.url, **auth_headers(lonely_user))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"] == []


class TestNotificationMarkReadEndpoint:
    def url_for(self, delivery):
        return f"/api/v1/notifications/me/{delivery.id}/read"

    def test_requires_authentication(self, api_client, participant):
        delivery = NotificationDeliveryFactory(user=participant, channel="in_portal")
        response = api_client.post(self.url_for(delivery), format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_marks_read_and_returns_200(self, api_client, participant, auth_headers):
        delivery = NotificationDeliveryFactory(user=participant, channel="in_portal")

        response = api_client.post(self.url_for(delivery), format="json", **auth_headers(participant))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["readAt"] is not None

    def test_another_users_delivery_returns_404(self, api_client, participant, auth_headers):
        other_delivery = NotificationDeliveryFactory(user=AccountFactory(), channel="in_portal")

        response = api_client.post(self.url_for(other_delivery), format="json", **auth_headers(participant))

        assert response.status_code == status.HTTP_404_NOT_FOUND
