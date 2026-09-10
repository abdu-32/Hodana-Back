import pytest
from rest_framework import status
from django.urls import reverse
from apps.support_ai.tests.factories import ChatMessageFactory
from apps.accounts.tests.factories import AccountFactory
from django.test import override_settings

pytestmark = pytest.mark.django_db

@override_settings(SUPPORT_AI_TEST_MODE=True)
def test_api_chat_unauthenticated(api_client):
    res = api_client.post("/api/v1/ai/chat/", {"question": "Hi"})
    assert res.status_code == status.HTTP_200_OK
    assert "answer" in res.data

@override_settings(SUPPORT_AI_TEST_MODE=True)
def test_api_chat_authorized(api_client, auth_headers):
    user = AccountFactory()
    res = api_client.post("/api/v1/ai/chat/", {"question": "Hi"}, **auth_headers(user))
    assert res.status_code == status.HTTP_200_OK
    assert "answer" in res.data

@override_settings(SUPPORT_AI_TEST_MODE=False, LLM_API_KEY="test")
def test_api_chat_llm_failure(api_client, auth_headers):
    from unittest.mock import patch
    import httpx
    
    user = AccountFactory()
    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Timeout")):
        res = api_client.post("/api/v1/ai/chat/", {"question": "How do I configure Telebirr payments?"}, **auth_headers(user))
        
    assert res.status_code == status.HTTP_200_OK
    assert res.data["llmUnavailable"] is True

def test_api_feedback_unauthorized(api_client):
    res = api_client.post("/api/v1/ai/feedback/", {"messageId": "00000000-0000-0000-0000-000000000000", "rating": 5})
    assert res.status_code == status.HTTP_401_UNAUTHORIZED

def test_api_feedback_authorized(api_client, auth_headers):
    user = AccountFactory()
    msg = ChatMessageFactory(role="assistant", session__user=user)
    
    res = api_client.post("/api/v1/ai/feedback/", {
        "messageId": str(msg.id),
        "rating": 5
    }, **auth_headers(user))
    
    assert res.status_code == status.HTTP_201_CREATED
    assert res.data["rating"] == 5
