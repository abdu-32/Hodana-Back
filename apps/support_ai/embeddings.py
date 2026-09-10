"""
embeddings.py — Chunk and embed source content for RAG indexing.

All embedding model calls live here. Never called inline on a request;
only called from tasks.py.
"""
import uuid
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Raised when the embedding provider fails."""


def chunk_text(text: str, max_tokens: int = 512, overlap: int = 50) -> list[str]:
    """
    Split text into overlapping chunks by approximate token count.
    Uses whitespace-based word splitting (1 token ≈ 4 chars).
    Pure function — no I/O, unit-testable.
    """
    if not text or not text.strip():
        return []
    max_chars = max_tokens * 4
    overlap_chars = overlap * 4
    words = text.split()
    if not words:
        return []
    chunks = []
    current_chars = 0
    current_words = []
    for word in words:
        word_len = len(word) + 1  # +1 for space
        if current_chars + word_len > max_chars and current_words:
            chunks.append(" ".join(current_words))
            # Overlap: keep last `overlap_chars` worth of words
            overlap_text = " ".join(current_words)
            overlap_start = max(0, len(overlap_text) - overlap_chars)
            overlap_portion = overlap_text[overlap_start:].split(" ", 1)
            if len(overlap_portion) > 1:
                current_words = overlap_portion[1].split()
            else:
                current_words = []
            current_chars = sum(len(w) + 1 for w in current_words)
        current_words.append(word)
        current_chars += word_len
    if current_words:
        chunks.append(" ".join(current_words))
    return chunks if chunks else [text]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Call the embedding model API. Returns list of float vectors.
    Raises EmbeddingError on any failure.
    
    Uses OpenAI-compatible API (configurable via LLM_PROVIDER_URL).
    Falls back to zero-vector in test mode (SUPPORT_AI_TEST_MODE=True).
    """
    if not texts:
        return []
    
    test_mode = getattr(settings, 'SUPPORT_AI_TEST_MODE', False)
    api_key = getattr(settings, 'LLM_API_KEY', '')

    import hashlib

    STOP_WORDS = {
        "the", "is", "at", "on", "a", "an", "and", "to", "in", "of", "it", "be", "are",
        "do", "does", "did", "for", "or", "can", "could", "should", "would", "tell",
        "me", "give", "you", "your", "my", "this", "that", "these", "those"
    }

    def normalize_word(w: str) -> str:
        w = w.strip("?,.:!;\n\r\"'()[]").lower()
        if w.startswith("submit"):
            return "submission"
        if w.startswith("project"):
            return "project"
        if w.startswith("hackathon"):
            return "hackathon"
        if w.startswith("team"):
            return "team"
        if w.startswith("judge") or w.startswith("judging"):
            return "judging"
        if w.startswith("prize") or w.startswith("payout") or w.startswith("payment"):
            return "payment"
        return w

    def _build_feature_vec(text: str, dim: int = 1536) -> list[float]:
        vec = [0.0] * dim
        lines = text.split("\n")
        for line in lines:
            weight = 5.0 if line.startswith("Question:") or line.startswith("Q:") or line.startswith("Title:") or line.startswith("### Q:") or "?" in line else 1.0
            words = [normalize_word(w) for w in line.split()]
            words = [w for w in words if w and w not in STOP_WORDS and len(w) > 1]
            for w in words:
                idx = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16) % dim
                vec[idx] += weight
        return vec

    if test_mode or not api_key:
        dim = getattr(settings, 'EMBEDDING_DIMENSION', 1536)
        return [_build_feature_vec(t, dim) for t in texts]
    
    import httpx
    provider_url = getattr(settings, 'LLM_PROVIDER_URL', 'https://api.openai.com')
    model = getattr(settings, 'EMBEDDING_MODEL', 'text-embedding-3-small')
    timeout = getattr(settings, 'LLM_TIMEOUT_SECONDS', 15)
    
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{provider_url.rstrip('/')}/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"input": texts, "model": model},
            )
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
    except Exception as exc:
        logger.warning("External embedding API error (%s). Falling back to feature vectors.", exc)
        dim = getattr(settings, 'EMBEDDING_DIMENSION', 1536)
        return [_build_feature_vec(t, dim) for t in texts]


def index_article(article_id: uuid.UUID) -> int:
    """
    Fetch Article, chunk body, embed, upsert DocumentChunk rows.
    Only called from tasks.py. Returns number of chunks written.
    Only indexes published articles (visibility=public).
    """
    from apps.knowledge_base.models import Article
    from .models import DocumentChunk
    
    try:
        article = Article.objects.select_related("category").get(
            id=article_id, status="published"
        )
    except Article.DoesNotExist:
        # Delete any existing chunks for this source (may have been unpublished)
        delete_chunks_for_source("article", article_id)
        return 0
    
    text_to_chunk = f"{article.title}\n\n{article.body}"
    chunks = chunk_text(text_to_chunk)
    
    try:
        embeddings = embed_texts(chunks)
    except EmbeddingError:
        logger.exception("Failed to embed article %s", article_id)
        return 0
    
    # Delete old chunks for this source before reinserting
    delete_chunks_for_source("article", article_id)
    
    count = 0
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        DocumentChunk.objects.create(
            source_type="article",
            source_id=article.id,
            visibility="public",
            text=chunk,
            embedding=embedding,
            chunk_index=i,
            metadata={"title": article.title, "slug": article.slug, "category": article.category.name if article.category else ""},
        )
        count += 1
    
    logger.info("Indexed article %s: %d chunks", article_id, count)
    return count


def index_faq(faq_id: uuid.UUID) -> int:
    """Fetch FAQ, embed answer, upsert DocumentChunk. Only published FAQs."""
    from apps.knowledge_base.models import FAQ
    from .models import DocumentChunk
    
    try:
        faq = FAQ.objects.select_related("category").get(id=faq_id, status="published")
    except FAQ.DoesNotExist:
        delete_chunks_for_source("faq", faq_id)
        return 0
    
    text_to_chunk = f"{faq.question}\n\n{faq.answer}"
    chunks = chunk_text(text_to_chunk)
    
    try:
        embeddings = embed_texts(chunks)
    except EmbeddingError:
        logger.exception("Failed to embed FAQ %s", faq_id)
        return 0
    
    delete_chunks_for_source("faq", faq_id)
    
    count = 0
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        DocumentChunk.objects.create(
            source_type="faq",
            source_id=faq.id,
            visibility="public",
            text=chunk,
            embedding=embedding,
            chunk_index=i,
            metadata={"question": faq.question, "category": faq.category.name if faq.category else ""},
        )
        count += 1
    
    return count


def index_hackathon(hackathon_id: uuid.UUID) -> int:
    """
    Index hackathon description and rules. Published -> public visibility.
    Draft -> organizer_only visibility (so organizers can get AI help with drafts).
    NEVER indexes: judge scores, team data, submission content, PII.
    """
    from apps.hackathons.models import Hackathon
    from .models import DocumentChunk
    
    try:
        hackathon = Hackathon.objects.select_related("host_org").get(id=hackathon_id)
    except Hackathon.DoesNotExist:
        delete_chunks_for_source("hackathon_description", hackathon_id)
        delete_chunks_for_source("hackathon_rules", hackathon_id)
        return 0
    
    if hackathon.status not in ("published", "draft"):
        delete_chunks_for_source("hackathon_description", hackathon_id)
        delete_chunks_for_source("hackathon_rules", hackathon_id)
        return 0
    
    visibility = "public" if hackathon.status == "published" else "organizer_only"
    org_id = hackathon.host_org_id
    
    count = 0
    
    # Index description
    if hackathon.description.strip():
        desc_text = f"{hackathon.title}\n\n{hackathon.description}"
        desc_chunks = chunk_text(desc_text)
        try:
            embeddings = embed_texts(desc_chunks)
            delete_chunks_for_source("hackathon_description", hackathon_id)
            for i, (chunk, emb) in enumerate(zip(desc_chunks, embeddings)):
                DocumentChunk.objects.create(
                    source_type="hackathon_description",
                    source_id=hackathon.id,
                    hackathon_id=hackathon.id,
                    organization_id=org_id,
                    visibility=visibility,
                    text=chunk,
                    embedding=emb,
                    chunk_index=i,
                    metadata={"hackathon_title": hackathon.title, "hackathon_slug": hackathon.slug},
                )
                count += 1
        except EmbeddingError:
            logger.exception("Failed to embed hackathon description %s", hackathon_id)
    
    # Index rules
    if hackathon.rules.strip():
        rules_chunks = chunk_text(hackathon.rules)
        try:
            embeddings = embed_texts(rules_chunks)
            delete_chunks_for_source("hackathon_rules", hackathon_id)
            for i, (chunk, emb) in enumerate(zip(rules_chunks, embeddings)):
                DocumentChunk.objects.create(
                    source_type="hackathon_rules",
                    source_id=hackathon.id,
                    hackathon_id=hackathon.id,
                    organization_id=org_id,
                    visibility=visibility,
                    text=chunk,
                    embedding=emb,
                    chunk_index=i,
                    metadata={"hackathon_title": hackathon.title, "section": "rules"},
                )
                count += 1
        except EmbeddingError:
            logger.exception("Failed to embed hackathon rules %s", hackathon_id)
    
    return count


def delete_chunks_for_source(source_type: str, source_id: uuid.UUID):
    """Delete all DocumentChunk rows for a given source. Called before re-indexing."""
    from .models import DocumentChunk
    DocumentChunk.objects.filter(source_type=source_type, source_id=source_id).delete()
