import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from apps.accounts.tests.factories import AccountFactory
from apps.support.tests.factories import TicketFactory

def test_unauthorized_list_tickets(api_client):
    response = api_client.get("/api/v1/support/tickets/")
    assert response.status_code == 401

def test_list_own_tickets(api_client, regular_user, auth_headers):
    TicketFactory(submitter=regular_user)
    TicketFactory() # other user's ticket
    response = api_client.get("/api/v1/support/tickets/", **auth_headers)
    assert response.status_code == 200
    assert len(response.data["data"]) == 1

def test_create_ticket(api_client, auth_headers):
    response = api_client.post("/api/v1/support/tickets/", {
        "subject": "Help me",
        "body": "I need help",
        "category": "general"
    }, format="json", **auth_headers)
    assert response.status_code == 201
    assert response.data["subject"] == "Help me"

def test_create_ticket_with_human_support_fields(api_client, auth_headers):
    response = api_client.post("/api/v1/support/tickets/", {
        "subject": "Payment issue",
        "problem": "Billing",
        "description": "Unable to process Telebirr payment for registration.",
        "priority": "high",
        "otherDetails": "Transaction reference: TXN-998822"
    }, format="json", **auth_headers)
    assert response.status_code == 201
    assert response.data["subject"] == "Payment issue"
    assert response.data["category"] == "billing"
    assert response.data["priority"] == "high"


def test_get_other_user_ticket(api_client, auth_headers):
    other_ticket = TicketFactory()
    response = api_client.get(f"/api/v1/support/tickets/{other_ticket.id}/", **auth_headers)
    assert response.status_code == 404

def test_staff_get_any_ticket(api_client, staff_user):
    from rest_framework_simplejwt.tokens import RefreshToken
    token = RefreshToken.for_user(staff_user)
    token["token_version"] = staff_user.token_version
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}
    
    other_ticket = TicketFactory()
    response = api_client.get(f"/api/v1/support/tickets/{other_ticket.id}/", **headers)
    assert response.status_code == 200

def test_add_message(api_client, auth_headers, ticket):
    response = api_client.post(f"/api/v1/support/tickets/{ticket.id}/messages/", {
        "body": "More help needed"
    }, format="json", **auth_headers)
    assert response.status_code == 201

def test_list_staff_tickets_unauthorized(api_client, auth_headers):
    response = api_client.get("/api/v1/support/staff/tickets/", **auth_headers)
    assert response.status_code == 403

def test_list_staff_tickets_authorized(api_client, staff_user):
    from rest_framework_simplejwt.tokens import RefreshToken
    token = RefreshToken.for_user(staff_user)
    token["token_version"] = staff_user.token_version
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}
    
    TicketFactory()
    response = api_client.get("/api/v1/support/staff/tickets/", **headers)
    assert response.status_code == 200
    assert len(response.data["data"]) == 1

def test_create_internal_note_unauthorized(api_client, auth_headers, ticket):
    response = api_client.post("/api/v1/support/staff/notes/", {
        "ticketId": str(ticket.id),
        "body": "Secret note"
    }, format="json", **auth_headers)
    assert response.status_code == 403

def test_ticket_detail_includes_complete_conversation_history(api_client, regular_user, staff_user, auth_headers):
    from rest_framework_simplejwt.tokens import RefreshToken
    from apps.support.services import create_ticket, add_message

    ticket = create_ticket(
        actor=regular_user,
        subject="OAuth Issue",
        body="Google OAuth is failing with redirect_uri_mismatch.",
        category="technical"
    )

    # Admin replies
    add_message(
        actor=staff_user,
        ticket_id=ticket.id,
        body="Please clear cookies and use the trycloudflare domain."
    )

    # User replies back
    add_message(
        actor=regular_user,
        ticket_id=ticket.id,
        body="Works now, thank you!"
    )

    # Fetch ticket details as user
    response = api_client.get(f"/api/v1/support/tickets/{ticket.id}/", **auth_headers)
    assert response.status_code == 200
    assert "messages" in response.data
    assert len(response.data["messages"]) == 3
    assert response.data["messages"][0]["isStaffReply"] is False
    assert response.data["messages"][1]["isStaffReply"] is True
    assert response.data["messages"][2]["isStaffReply"] is False
    assert "conversationHistory" in response.data
    assert "Google OAuth is failing" in response.data["conversationHistory"]
    assert "clear cookies" in response.data["conversationHistory"]

