"""
llm.py — Thin wrapper around the external LLM provider.

All timeouts, retries, and failure handling live here.
No other module may import the LLM provider SDK directly.
This isolates a slow/unavailable LLM from every other endpoint (NFR-AVAIL-003 analogue).

Isolation mechanism:
- httpx.Client with a dedicated connection pool
- Hard timeout: LLM_TIMEOUT_SECONDS (default 15s)
- Circuit breaker stored in Django cache (Redis in production)
"""
import logging
import time
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_CIRCUIT_FAILURES_KEY = "support_ai:llm:circuit_failures"
_CIRCUIT_OPEN_UNTIL_KEY = "support_ai:llm:circuit_open_until"


class LLMUnavailableError(Exception):
    """Raised when the LLM provider is unreachable or the circuit is open."""


class LLMTimeoutError(LLMUnavailableError):
    """Raised specifically when the LLM provider times out."""


def _is_circuit_open() -> bool:
    """Returns True if the circuit breaker is currently open."""
    open_until = cache.get(_CIRCUIT_OPEN_UNTIL_KEY)
    if open_until and time.time() < open_until:
        return True
    return False


def _record_failure():
    """Increment failure counter; open circuit if threshold exceeded."""
    threshold = getattr(settings, 'LLM_FAILURE_THRESHOLD', 5)
    circuit_open_seconds = getattr(settings, 'LLM_CIRCUIT_OPEN_SECONDS', 60)
    
    failures = cache.get(_CIRCUIT_FAILURES_KEY, 0) + 1
    cache.set(_CIRCUIT_FAILURES_KEY, failures, timeout=300)  # Reset after 5 min
    
    if failures >= threshold:
        cache.set(_CIRCUIT_OPEN_UNTIL_KEY, time.time() + circuit_open_seconds, timeout=circuit_open_seconds + 10)
        cache.delete(_CIRCUIT_FAILURES_KEY)
        logger.warning("LLM circuit breaker OPENED after %d failures", failures)


def _record_success():
    """Reset failure counter on success."""
    cache.delete(_CIRCUIT_FAILURES_KEY)
    cache.delete(_CIRCUIT_OPEN_UNTIL_KEY)


def chat_completion(
    *,
    messages: list[dict],
    model: str | None = None,
    timeout: float | None = None,
) -> str:
    """
    Call the LLM provider. Returns the assistant's reply text.
    Raises LLMUnavailableError on any failure.
    Never raises provider-specific exceptions — callers see only this module's types.
    """
    if _is_circuit_open():
        raise LLMUnavailableError("LLM circuit breaker is open. Failing fast.")

    test_mode = getattr(settings, 'SUPPORT_AI_TEST_MODE', False)
    api_key = getattr(settings, 'LLM_API_KEY', '')

    if test_mode or not api_key:
        last_user_msg = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        question_line = ""
        if "Question:" in last_user_msg:
            question_line = last_user_msg.split("Question:")[1].split("\n")[0].strip()

        cleaned_q = question_line.lower().strip("?,.!")
        if cleaned_q in {"hello", "hi", "hey", "greetings", "good morning", "good afternoon", "good evening", "howdy", "how are you"}:
            return "I'm here to help with questions about the Ethiopia Innovation Hub, its platform, features, processes, and documentation."

        if "Context:" in last_user_msg and "No relevant context found" not in last_user_msg:
            try:
                context_part = last_user_msg.split("Context:")[1].split("\n\nQuestion:")[0].strip()
                if "Answer:" in context_part:
                    return context_part.split("Answer:", 1)[1].strip()
                elif "A:" in context_part:
                    return context_part.split("A:", 1)[1].strip()
                return context_part
            except Exception:
                pass
        return "I can only help with questions related to the Ethiopia Innovation Hub, its features, processes, and documentation."
    
    import httpx
    provider_url = getattr(settings, 'LLM_PROVIDER_URL', 'https://api.openai.com')
    resolved_model = model or getattr(settings, 'LLM_MODEL', 'gpt-4o-mini')
    resolved_timeout = timeout if timeout is not None else getattr(settings, 'LLM_TIMEOUT_SECONDS', 15)
    
    try:
        with httpx.Client(
            timeout=resolved_timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        ) as client:
            start = time.monotonic()
            response = client.post(
                f"{provider_url.rstrip('/')}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": resolved_model,
                    "messages": messages,
                    "max_tokens": 1024,
                    "temperature": 0.3,
                },
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            response.raise_for_status()
            data = response.json()
            _record_success()
            return data["choices"][0]["message"]["content"]
    except httpx.TimeoutException as exc:
        _record_failure()
        logger.warning("LLM provider timed out: %s", exc)
        raise LLMTimeoutError(f"LLM provider timed out after {resolved_timeout}s") from exc
    except httpx.HTTPStatusError as exc:
        _record_failure()
        logger.error("LLM provider HTTP error %s: %s", exc.response.status_code, exc)
        raise LLMUnavailableError(f"LLM provider returned HTTP {exc.response.status_code}") from exc
    except Exception as exc:
        _record_failure()
        logger.exception("Unexpected LLM provider error")
        raise LLMUnavailableError(f"LLM provider error: {exc}") from exc
