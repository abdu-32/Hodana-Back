"""
support_ai.services — Orchestration for AI chat and feedback.

FR-AI-001: chat()
FR-AI-002: submit_feedback()
"""
import logging
import time
import uuid

from django.db import transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import NotFound, ValidationError

from apps.core.models import AuditLogEntry

from .models import ChatSession, ChatMessage, AIFeedback
from .prompts import build_rag_prompt, build_fallback_response
from .llm import chat_completion, LLMUnavailableError
from .retriever import retrieve_chunks
from .embeddings import embed_texts, EmbeddingError

logger = logging.getLogger(__name__)


def _get_or_create_session(*, actor, session_id=None, hackathon_id=None, organization_id=None):
    user = actor if getattr(actor, 'is_authenticated', False) else None
    if session_id is not None:
        try:
            session = ChatSession.objects.get(id=session_id, user=user)
        except (ChatSession.DoesNotExist, ValueError, DjangoValidationError):
            raise NotFound("Chat session not found.")
        return session
    return ChatSession.objects.create(
        user=user,
        hackathon_id=hackathon_id,
        organization_id=organization_id,
    )


def _sanitize_response(content: str, question: str = "") -> str:
    """
    Sanitizes chatbot response content:
    1. Removes any leading question repetition or question title prefixes.
    2. Strips ALL asterisk (*) characters (no bolding, italics, or asterisk bullets).
    3. Cleans up excess whitespace.
    """
    if not content:
        return ""
    
    cleaned = content.strip()
    
    # 1. Remove leading question repetition if present
    if question:
        q_norm = question.strip().lower().rstrip("?")
        c_lower = cleaned.lower()
        if c_lower.startswith(q_norm):
            rest = cleaned[len(q_norm):].lstrip("? \t\n\r:")
            if rest:
                cleaned = rest
        elif "?" in cleaned:
            parts = cleaned.split("?", 1)
            if parts[0].strip().lower() == q_norm and len(parts) > 1 and parts[1].strip():
                cleaned = parts[1].strip()

    # 2. Strip leading 'Question:', 'Answer:', 'A:', or internal category headers
    import re
    cleaned = re.sub(r"^(###?\s*\d+\.?[^\n]+\n+)", "", cleaned)
    cleaned = re.sub(r"^(Category\s*\d+:?[^\n]+\n+)", "", cleaned, flags=re.IGNORECASE)

    if cleaned.lower().startswith("question:"):
        cleaned = cleaned.split(":", 1)[1].strip()
        if "?" in cleaned:
            cleaned = cleaned.split("?", 1)[1].strip()
    if cleaned.lower().startswith("answer:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    elif cleaned.lower().startswith("a:"):
        cleaned = cleaned.split(":", 1)[1].strip()

    # 3. Strip ALL asterisk (*) characters
    cleaned = cleaned.replace("*", "")

    # Strip horizontal dividers or raw doc boundaries
    if " --- " in cleaned or "\n---\n" in cleaned or cleaned.endswith("---"):
        cleaned = re.split(r"\s*---\s*", cleaned)[0].strip()
    cleaned = re.sub(r"#+\s*PART\s+[IVXLCDM\d]+:?.*$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()


    # 4. Format sequential list items into clear numbered lists (1. ---, 2. ---)
    if " - " in cleaned and "\n" not in cleaned:
        parts = [p.strip() for p in cleaned.split(" - ") if p.strip()]
        if len(parts) > 1:
            header = parts[0]
            items = parts[1:]
            formatted_items = [f"{i+1}. {item}" for i, item in enumerate(items)]
            cleaned = f"{header}\n\n" + "\n".join(formatted_items)

    lines = cleaned.split("\n")
    new_lines = []
    item_idx = 1
    in_list = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- "):
            item_text = stripped[2:].strip()
            new_lines.append(f"{item_idx}. {item_text}")
            item_idx += 1
            in_list = True
        elif re.match(r"^\d+\.\s+", stripped):
            item_text = re.sub(r"^\d+\.\s+", "", stripped)
            new_lines.append(f"{item_idx}. {item_text}")
            item_idx += 1
            in_list = True
        else:
            if in_list:
                item_idx = 1
                in_list = False
            new_lines.append(line)

    cleaned = "\n".join(new_lines)

    # 5. Clean up multiple spaces
    cleaned = re.sub(r"  +", " ", cleaned)

    return cleaned.strip()


def _extract_related_questions(chunks, single_word: str) -> list[str]:
    """
    Extract up to 3-5 distinct, semantically relevant question titles from matching chunks.
    """
    stem = single_word.lower().rstrip("s")
    extracted = []
    
    for chunk in chunks:
        text = chunk.text.strip()
        if "?" in text:
            q_text = text.split("?", 1)[0].strip() + "?"
            if q_text.startswith("###"):
                q_text = q_text.lstrip("#").strip()
            if q_text.lower().startswith("q:"):
                q_text = q_text[2:].strip()
            
            # Remove any asterisks from related questions too
            q_text = q_text.replace("*", "").strip()
            
            if q_text and q_text not in extracted:
                extracted.append(q_text)
    
    # Rank: prioritize questions containing the word or its stem
    prioritized = [q for q in extracted if stem in q.lower() or single_word.lower() in q.lower()]
    for q in extracted:
        if q not in prioritized:
            prioritized.append(q)
            
    return prioritized[:5]


def _get_live_platform_context(session=None) -> str:
    """
    Fetches real-time, live platform data (active/published hackathons, challenge tracks,
    current registration & submission deadlines, prizes, and status) to ensure
    the AI responds according to the current state of the platform.
    """
    try:
        from apps.hackathons.models import Hackathon
        from django.utils import timezone
        now = timezone.now()
        
        # Scoped to session's hackathon if available, else fetch top published hackathons
        qs = Hackathon.objects.filter(status="published", is_suspended=False).select_related("host_org").prefetch_related("tracks")
        if session and session.hackathon_id:
            qs = qs.filter(id=session.hackathon_id)
            
        hackathons = list(qs.order_by("-registration_opens_at")[:5])
        if not hackathons:
            return "Current Live Platform State: No active public hackathons or announcements at this moment."
            
        lines = ["Current Live Platform State & Active Events:"]
        for h in hackathons:
            is_reg_open = h.registration_opens_at <= now <= h.registration_closes_at
            is_sub_open = h.submission_opens_at <= now <= h.submission_closes_at
            reg_status = "Open Now" if is_reg_open else ("Upcoming" if now < h.registration_opens_at else "Closed")
            sub_status = "Open Now" if is_sub_open else ("Upcoming" if now < h.submission_opens_at else "Closed")
            
            h_info = (
                f"- Hackathon: {h.title} (Host: {h.host_org.name if h.host_org else 'Platform'})\n"
                f"  Location: {h.location_mode.title()}\n"
                f"  Registration: {reg_status} (Opens: {h.registration_opens_at.strftime('%Y-%m-%d')}, Closes: {h.registration_closes_at.strftime('%Y-%m-%d')})\n"
                f"  Submission: {sub_status} (Opens: {h.submission_opens_at.strftime('%Y-%m-%d')}, Closes: {h.submission_closes_at.strftime('%Y-%m-%d')})\n"
                f"  Prizes: {h.prize_info if h.prize_info else 'See challenge tracks for details'}\n"
            )
            tracks = list(h.tracks.all())
            if tracks:
                track_str = ", ".join([f"{t.name} (Prize: {t.prize})" for t in tracks])
                h_info += f"  Challenge Tracks: {track_str}\n"
            lines.append(h_info)
            
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Failed to fetch live platform context: {e}")
        return ""


def chat(
    *,
    actor,
    session_id=None,
    hackathon_id=None,
    organization_id=None,
    question: str,
) -> dict:
    """
    FR-AI-001. Orchestrates: embed question -> retrieve chunks (scoped) ->
    build prompt -> call LLM -> persist ChatMessage -> return response.

    On LLMUnavailableError: returns a canned fallback response and sets
    llm_unavailable=True in the response body. Does NOT raise.
    """
    if not question or not question.strip():
        raise ValidationError({"question": "Question cannot be empty."})
    
    session = _get_or_create_session(
        actor=actor,
        session_id=session_id,
        hackathon_id=hackathon_id,
        organization_id=organization_id,
    )
    
    # Get chat history for context
    history = list(
        session.messages.order_by("-created_at")[:10]
        .values("role", "content")
    )
    history.reverse()
    
    # Embed the question
    try:
        query_embeddings = embed_texts([question.strip()])
        query_embedding = query_embeddings[0] if query_embeddings else []
    except EmbeddingError:
        logger.exception("Failed to embed user question")
        query_embedding = []
    
    # Retrieve scoped chunks (security: filter is in SQL WHERE clause)
    chunks = []
    if query_embedding:
        chunks = retrieve_chunks(
            query_embedding=query_embedding,
            user=actor,
            question=question.strip(),
            hackathon_id=session.hackathon_id,
            organization_id=session.organization_id,
            top_k=5,
        )
    
    # Fetch live platform context for real-time awareness
    live_context = _get_live_platform_context(session=session)

    # Build prompt
    messages = build_rag_prompt(
        question=question.strip(),
        retrieved_chunks=chunks,
        chat_history=history,
        live_context=live_context,
    )
    
    # Save the user's message
    with transaction.atomic():
        user_msg = ChatMessage.objects.create(
            session=session,
            role="user",
            content=question.strip(),
            retrieved_chunk_ids=[str(c.id) for c in chunks],
        )
    
    # Scope & intent check
    llm_unavailable = False
    assistant_content = ""
    llm_model = ""
    latency_ms = None
    related_questions = []
    
    cleaned_q = question.strip().lower().strip("?,.!")
    words = [w for w in question.strip().split() if w]
    is_single_word = (len(words) == 1)
    GREETINGS = {"hello", "hi", "hey", "greetings", "good morning", "good afternoon", "good evening", "howdy", "how are you"}

    if cleaned_q in GREETINGS:
        assistant_content = "I'm here to help with questions about the Ethiopia Innovation Hub, its platform, features, processes, and documentation."
    elif is_single_word:
        single_word = words[0].strip("?,.!")
        if chunks:
            related_questions = _extract_related_questions(chunks, single_word)
        
        if related_questions:
            assistant_content = f"I found some information related to {single_word.capitalize()}. What would you like to know?"
        else:
            assistant_content = "I can only help with questions related to the Ethiopia Innovation Hub, its features, processes, and documentation."
    else:
        try:
            start = time.monotonic()
            assistant_content = chat_completion(messages=messages)
            latency_ms = int((time.monotonic() - start) * 1000)
            llm_model = getattr(__import__('django.conf', fromlist=['settings']).settings, 'LLM_MODEL', '')
        except LLMUnavailableError:
            logger.warning("LLM unavailable for chat session %s", session.id)
            llm_unavailable = True
            live_keywords = {"hackathon", "hackathons", "deadline", "deadlines", "registration", "submission", "track", "tracks", "update", "updates", "latest", "recent", "active", "event", "events", "prize", "prizes"}
            q_terms = set(cleaned_q.split())
            if q_terms.intersection(live_keywords) and live_context and "No active public hackathons" not in live_context:
                assistant_content = live_context
            elif chunks:
                best_chunk = chunks[0]
                answer_text = best_chunk.text.strip()
                if "?" in answer_text:
                    parts = answer_text.split("?", 1)
                    if len(parts) > 1 and parts[1].strip():
                        answer_text = parts[1].strip()
                if answer_text.lower().startswith("answer:"):
                    answer_text = answer_text.split(":", 1)[1].strip()
                elif answer_text.lower().startswith("a:"):
                    answer_text = answer_text.split(":", 1)[1].strip()
                assistant_content = answer_text
            else:
                assistant_content = "I can only help with questions related to the Ethiopia Innovation Hub, its features, processes, and documentation."
    
    # Sanitize assistant response: remove question repetition & strip all asterisks (*)
    assistant_content = _sanitize_response(assistant_content, question=question.strip())

    # Save assistant message
    with transaction.atomic():
        assistant_msg = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content=assistant_content,
            retrieved_chunk_ids=[str(c.id) for c in chunks],
            llm_model=llm_model,
            latency_ms=latency_ms,
        )
    
    return {
        "session_id": str(session.id),
        "message_id": str(assistant_msg.id),
        "answer": assistant_content,
        "llm_unavailable": llm_unavailable,
        "retrieved_chunk_count": len(chunks),
        "related_questions": related_questions,
    }


def submit_feedback(*, actor, message_id, rating, comment="") -> AIFeedback:
    """
    FR-AI-002. Rate an AI chat response.
    One per (message, user) pair — update_or_create.
    """
    if not (1 <= int(rating) <= 5):
        raise ValidationError({"rating": "Rating must be between 1 and 5."})
    
    try:
        message = ChatMessage.objects.get(id=message_id, role="assistant")
    except (ChatMessage.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound("Chat message not found.")
    
    # Verify the user owns the session
    if message.session.user != actor and not getattr(actor, 'is_platform_admin', False):
        raise NotFound("Chat message not found.")
    
    feedback, _ = AIFeedback.objects.update_or_create(
        message=message,
        user=actor,
        defaults={"rating": int(rating), "comment": comment or ""},
    )
    
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="ai_feedback.submitted",
        target_type="chat_message",
        target_id=str(message.id),
        metadata={"rating": int(rating)},
    )
    
    return feedback
