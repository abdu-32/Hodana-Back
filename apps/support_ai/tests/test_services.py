import pytest
from unittest.mock import patch
from apps.support_ai.services import chat, submit_feedback
from apps.support_ai.models import ChatSession, ChatMessage
from apps.support_ai.tests.factories import ChatSessionFactory, ChatMessageFactory
from apps.accounts.tests.factories import AccountFactory
from apps.support_ai.llm import LLMUnavailableError
from rest_framework.exceptions import ValidationError

pytestmark = pytest.mark.django_db

@patch("apps.support_ai.services.chat_completion")
def test_chat_returns_fallback_on_llm_unavailable(mock_chat):
    mock_chat.side_effect = LLMUnavailableError("Error")
    user = AccountFactory()
    
    result = chat(actor=user, question="How do I configure webhook keys?")
    
    assert result["llm_unavailable"] is True
    assert "I can only help with questions related to" in result["answer"] or "temporarily unable" in result["answer"]

@patch("apps.support_ai.services.chat_completion", return_value="Reply")
def test_chat_creates_session_if_none_provided(mock_chat):
    user = AccountFactory()
    assert ChatSession.objects.count() == 0
    
    result = chat(actor=user, question="Hello")
    
    assert ChatSession.objects.count() == 1
    assert ChatMessage.objects.count() == 2  # user + assistant

@patch("apps.support_ai.services.chat_completion", return_value="Reply")
def test_chat_reuses_existing_session(mock_chat):
    user = AccountFactory()
    session = ChatSessionFactory(user=user)
    
    result = chat(actor=user, session_id=session.id, question="Hello")
    
    assert ChatSession.objects.count() == 1
    assert str(session.id) == result["session_id"]

def test_submit_feedback_validates_rating_range():
    user = AccountFactory()
    msg = ChatMessageFactory(role="assistant", session__user=user)
    
    with pytest.raises(ValidationError):
        submit_feedback(actor=user, message_id=msg.id, rating=6)

def test_submit_feedback_is_update_or_create():
    user = AccountFactory()
    msg = ChatMessageFactory(role="assistant", session__user=user)
    
    # Create
    f1 = submit_feedback(actor=user, message_id=msg.id, rating=4)
    assert f1.rating == 4
    
    # Update
    f2 = submit_feedback(actor=user, message_id=msg.id, rating=5)
    assert f2.id == f1.id
    assert f2.rating == 5

def test_chat_single_word_returns_related_questions():
    user = AccountFactory()
    from apps.support_ai.tests.factories import DocumentChunkFactory
    from apps.support_ai.embeddings import embed_texts
    emb = embed_texts(["Teams"])[0]
    DocumentChunkFactory(
        text="How do I create or join a team? You can create or join a team from the dashboard.",
        embedding=emb
    )
    result = chat(actor=user, question="Teams")
    assert "I found some information related to Teams" in result["answer"]
    assert "*" not in result["answer"]
    assert len(result["related_questions"]) > 0
    assert "How do I create or join a team?" in result["related_questions"]

def test_chat_single_word_unmatched_returns_fallback_without_suggestions():
    user = AccountFactory()
    result = chat(actor=user, question="asdfghjkl")
    assert "I can only help with questions related to" in result["answer"]
    assert len(result["related_questions"]) == 0

def test_sanitize_response_removes_question_repetition_and_asterisks():
    from apps.support_ai.services import _sanitize_response
    q = "What is the Ethiopia Innovation Hub?"
    raw = "What is the Ethiopia Innovation Hub?\nThe **Ethiopia Innovation Hub** is a *national* platform..."
    cleaned = _sanitize_response(raw, question=q)
    assert cleaned == "The Ethiopia Innovation Hub is a national platform..."
    assert "*" not in cleaned
    assert "What is the Ethiopia Innovation Hub?" not in cleaned

@patch("apps.support_ai.services.chat_completion")
def test_chat_hackathon_rules_retrieval_and_answer(mock_chat):
    user = AccountFactory()
    from apps.support_ai.tests.factories import DocumentChunkFactory
    rules_chunk = DocumentChunkFactory(
        visibility="public",
        text="What are the hackathon rules?\n\nAll hackathons follow standard rules: 1. Eligibility 2. Teams of 2 to 5 members 3. Original code.",
        metadata={"title": "What are the hackathon rules?", "question": "What are the hackathon rules?"}
    )
    mock_chat.return_value = "All hackathons follow standard rules: 1. Eligibility 2. Teams of 2 to 5 members 3. Original code."
    
    result = chat(actor=user, question="What are the hackathon rules?")
    
    assert result["retrieved_chunk_count"] >= 1
    assert "hackathons follow standard rules" in result["answer"]


@patch("apps.support_ai.services.chat_completion")
def test_chat_live_platform_context_in_llm_prompt(mock_chat):
    user = AccountFactory()
    from apps.hackathons.tests.factories import HackathonFactory
    from django.utils import timezone
    now = timezone.now()
    HackathonFactory(
        title="Ethio-Fintech Innovation Sprint",
        status="published",
        is_suspended=False,
        registration_opens_at=now - timezone.timedelta(days=2),
        registration_closes_at=now + timezone.timedelta(days=10),
        submission_opens_at=now - timezone.timedelta(days=1),
        submission_closes_at=now + timezone.timedelta(days=12),
        total_prize_budget=500000,
        rules="Build innovative financial inclusion solutions for Ethiopia.",
    )
    mock_chat.return_value = "The Ethio-Fintech Innovation Sprint is currently active with a prize pool of 500,000 ETB."

    result = chat(actor=user, question="What are the active hackathons?")

    # Verify that chat_completion was called with live platform state
    assert mock_chat.called
    call_messages = mock_chat.call_args[1]["messages"]
    user_prompt = call_messages[-1]["content"]
    assert "Ethio-Fintech Innovation Sprint" in user_prompt
    assert "PAYMENTS, PRIZES & LOCAL CURRENCY" in user_prompt
    assert "Telebirr" in user_prompt
    assert "500,000 ETB" in result["answer"]


@patch("apps.support_ai.services.chat_completion")
def test_chat_fallback_answers_payments_and_prizes(mock_chat):
    mock_chat.side_effect = LLMUnavailableError("Service down")
    user = AccountFactory()

    result = chat(actor=user, question="What payment methods and rails are supported?")

    assert result["llm_unavailable"] is True
    assert "Telebirr" in result["answer"]
    assert "CBE Birr" in result["answer"]
    assert "Chapa" in result["answer"]
    assert "*" not in result["answer"]


@patch("apps.support_ai.services.chat_completion")
def test_chat_fallback_answers_registrations_and_teams(mock_chat):
    mock_chat.side_effect = LLMUnavailableError("Service down")
    user = AccountFactory()

    result = chat(actor=user, question="How does registration and teammate finder work?")

    assert result["llm_unavailable"] is True
    assert "Teammate Finder" in result["answer"] or "Solo" in result["answer"]
    assert "*" not in result["answer"]

