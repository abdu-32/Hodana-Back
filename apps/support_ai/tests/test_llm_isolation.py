import pytest
import httpx
from unittest.mock import patch
from apps.accounts.tests.factories import AccountFactory
from apps.support_ai.services import chat
from django.test import override_settings

pytestmark = pytest.mark.django_db

@override_settings(SUPPORT_AI_TEST_MODE=False, LLM_API_KEY="test")
@patch("httpx.Client.post")
def test_tc_nfr_avail_ai_001_timeout_isolation(mock_post):
    mock_post.side_effect = httpx.TimeoutException("Timeout")
    
    user = AccountFactory()
    
    # Should not raise an exception, should handle and return fallback
    result = chat(actor=user, question="Test timeout")
    
    assert result["llm_unavailable"] is True
