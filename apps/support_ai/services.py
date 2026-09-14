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
    Fetches comprehensive real-time, live platform data from the Hodana platform:
    1. Active & published hackathons, challenge tracks, registration/submission statuses,
       deadlines, locations/venues, total prize budgets, and registered participant stats.
    2. Supported local payment rails (Telebirr, CBE Birr, Chapa) and prize distribution policies.
    3. Registration options (Solo, Looking for Team, Create Team) and Teammate Finder.
    4. Recent platform announcements and active updates.
    """
    try:
        from apps.hackathons.models import Hackathon
        from django.utils import timezone
        now = timezone.now()

        sections = []

        # 1. Live Hackathons & Competitions
        qs = Hackathon.objects.filter(status="published", is_suspended=False).select_related("host_org").prefetch_related("tracks", "registrations")
        if session and session.hackathon_id:
            scoped_qs = qs.filter(id=session.hackathon_id)
            other_qs = qs.exclude(id=session.hackathon_id)
            hackathons = list(scoped_qs) + list(other_qs[:7])
        else:
            hackathons = list(qs.order_by("-registration_opens_at")[:10])

        if hackathons:
            h_lines = ["=== LIVE HACKATHONS & ACTIVE COMPETITIONS ==="]
            for h in hackathons:
                is_reg_open = h.registration_opens_at <= now <= h.registration_closes_at
                is_sub_open = h.submission_opens_at <= now <= h.submission_closes_at
                reg_status = "Open Now" if is_reg_open else ("Upcoming" if now < h.registration_opens_at else "Closed")
                sub_status = "Open Now" if is_sub_open else ("Upcoming" if now < h.submission_opens_at else "Closed")
                
                reg_count = h.registrations.count()
                location_str = h.location_mode.title()
                if h.venue and h.location_name:
                    location_str += f" ({h.venue}, {h.location_name})"
                elif h.location_name:
                    location_str += f" ({h.location_name})"
                elif h.venue:
                    location_str += f" ({h.venue})"

                prize_str = h.prize_info.strip() if h.prize_info else (f"{h.total_prize_budget:,.2f} ETB" if h.total_prize_budget else "See challenge tracks")

                h_info = (
                    f"- Event: {h.title} (Field: {h.field})\n"
                    f"  Host: {h.host_org.name if h.host_org else 'Ethiopia Innovation Hub'}\n"
                    f"  Format / Location: {location_str}\n"
                    f"  Registration: {reg_status} (Opens: {h.registration_opens_at.strftime('%Y-%m-%d')}, Closes: {h.registration_closes_at.strftime('%Y-%m-%d')} EAT)\n"
                    f"  Submission: {sub_status} (Opens: {h.submission_opens_at.strftime('%Y-%m-%d')}, Closes: {h.submission_closes_at.strftime('%Y-%m-%d')} EAT)\n"
                    f"  Registered Participants: {reg_count}\n"
                    f"  Total Prize Pool / Info: {prize_str}\n"
                )

                tracks = list(h.tracks.all())
                if tracks:
                    track_items = [f"{t.name} (Sponsor: {t.sponsor_org.name if t.sponsor_org else 'Partner'}, Prize: {t.prize})" for t in tracks]
                    h_info += f"  Challenge Tracks: {'; '.join(track_items)}\n"

                if h.rules:
                    clean_rules = h.rules.strip().replace("\n", " ")[:250]
                    h_info += f"  Rules Summary: {clean_rules}...\n"

                h_lines.append(h_info)
            sections.append("\n".join(h_lines))
        else:
            sections.append("=== LIVE HACKATHONS ===\nNo active public hackathons at this moment.")

        # 2. Payments & Prizes Information
        payments_info = (
            "=== PAYMENTS, PRIZES & LOCAL CURRENCY ===\n"
            "- Supported Local Payment Rails: Telebirr, CBE Birr, and Chapa (direct bank transfer / domestic card).\n"
            "- Currency: Ethiopian Birr (ETB) and project computing/cloud grants.\n"
            "- Prize Payout Policy: Cash prizes are disbursed automatically to verified Team Leaders upon judging conclusion. "
            "Teams sign a Prize Split Agreement to authorize team member distributions. No fees are deducted from participant prizes.\n"
            "- Platform Fee: 100% free for participants to enter hackathons, build teams, and submit projects."
        )
        sections.append(payments_info)

        # 3. Registrations, Teams & Teammate Finder
        reg_info = (
            "=== REGISTRATION, ELIGIBILITY & TEAM FORMATION ===\n"
            "- Participation Modes: Solo, Looking for a Team, or Create a Team.\n"
            "- Team Size: Typically 2 to 5 members (or individual if permitted by challenge rules).\n"
            "- Teammate Finder: Built-in discovery tool to filter participants by skills (Frontend, ML, UI/UX, Pitching) and send invitations.\n"
            "- Institutional Verification: Automatic domain verification for Ethiopian universities (.edu.et) and enterprises, granting verified trust badges."
        )
        sections.append(reg_info)

        # 4. Recent Platform Announcements & System Status
        try:
            from apps.notifications.models import Notification
            recent_notifs = list(Notification.objects.order_by("-id")[:4])
            if recent_notifs:
                notif_lines = ["=== RECENT PLATFORM ANNOUNCEMENTS & UPDATES ==="]
                for n in recent_notifs:
                    title_str = n.title.strip() or "Announcement"
                    msg_preview = n.message.strip().replace("\n", " ")[:160]
                    notif_lines.append(f"- {title_str}: {msg_preview}")
                sections.append("\n".join(notif_lines))
            else:
                sections.append("=== RECENT UPDATES ===\nPlatform operational. Low-bandwidth optimization and SMS alerts active.")
        except Exception:
            sections.append("=== RECENT UPDATES ===\nPlatform operational. Low-bandwidth optimization and SMS alerts active.")

        return "\n\n".join(sections)
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
            is_live_query = any(phrase in cleaned_q for phrase in [
                "active hackathon", "current hackathon", "ongoing hackathon", "live hackathon",
                "what hackathon", "what are the active", "upcoming hackathon", "latest hackathon",
                "active event", "upcoming event", "latest update", "announcement",
                "where is", "when does", "what are the prizes", "prize for", "tracks for",
                "how do payments work", "payment method", "telebirr", "cbe birr", "chapa",
                "how to register", "teammate finder", "ethio-fin", "greenseed", "amharic nlp",
                "agristream", "fintech frontier", "ethio-health", "egov", "e-gov"
            ])
            is_rules_or_guide_query = any(w in cleaned_q for w in [
                "hackathon rules", "submission rule", "general rule", "rubric criteria",
                "blind judging", "what is the ethiopia innovation hub", "who is the platform for",
                "system architecture", "modular monolith", "prompt injection", "sql injection"
            ])

            if chunks and not (is_live_query and not is_rules_or_guide_query):
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
            elif live_context and ("No active public hackathons" not in live_context or "PAYMENTS" in live_context):
                if any(w in cleaned_q for w in ["payment", "telebirr", "cbe birr", "chapa", "payout"]):
                    if "=== PAYMENTS" in live_context:
                        assistant_content = live_context.split("=== PAYMENTS")[1].split("===")[0].strip()
                        if assistant_content.startswith(", PRIZES & LOCAL CURRENCY ==="):
                            assistant_content = assistant_content.replace(", PRIZES & LOCAL CURRENCY ===", "").strip()
                    else:
                        assistant_content = live_context
                elif any(w in cleaned_q for w in ["announcement", "update", "latest", "news"]):
                    if "=== RECENT" in live_context:
                        assistant_content = live_context.split("=== RECENT")[1].strip()
                        if assistant_content.startswith("PLATFORM ANNOUNCEMENTS & UPDATES ==="):
                            assistant_content = assistant_content.replace("PLATFORM ANNOUNCEMENTS & UPDATES ===", "").strip()
                        elif assistant_content.startswith("UPDATES ==="):
                            assistant_content = assistant_content.replace("UPDATES ===", "").strip()
                    else:
                        assistant_content = live_context
                elif any(w in cleaned_q for w in ["register", "registration", "teammate finder", "solo", "team size"]):
                    if "=== REGISTRATION" in live_context:
                        assistant_content = live_context.split("=== REGISTRATION")[1].split("===")[0].strip()
                        if assistant_content.startswith(", ELIGIBILITY & TEAM FORMATION ==="):
                            assistant_content = assistant_content.replace(", ELIGIBILITY & TEAM FORMATION ===", "").strip()
                    else:
                        assistant_content = live_context
                else:
                    specific_match = None
                    if "=== LIVE HACKATHONS" in live_context:
                        h_block = live_context.split("=== LIVE HACKATHONS")[1].split("=== PAYMENTS")[0]
                        events = [e.strip() for e in h_block.split("- Event: ") if e.strip() and not e.startswith("& ACTIVE")]
                        for ev in events:
                            ev_first_line = ev.split("\n")[0].lower()
                            ev_words = [w for w in ev_first_line.split() if len(w) > 3]
                            if any(w in cleaned_q for w in ev_words):
                                specific_match = "- Event: " + ev
                                break
                    if specific_match:
                        assistant_content = specific_match
                    elif "=== PAYMENTS" in live_context:
                        assistant_content = live_context.split("=== PAYMENTS")[0].strip()
                    else:
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
