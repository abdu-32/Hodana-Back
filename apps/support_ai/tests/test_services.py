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
