"""
retriever.py — Scoped vector similarity search.

SECURITY REQUIREMENT (not a feature): the scope filter is applied in the
database query, BEFORE any chunk text is returned to the caller or handed
to prompts.py. The LLM is never given chunks it is not entitled to see.

The filter follows the same principle as TenantScopedManager (core/managers.py):
direct .filter()/.all() on DocumentChunk is forbidden for retrieval; the only
sanctioned entry point is `retrieve_chunks()` below.
"""
import math
from django.db.models import Q

VISIBILITY_RANK = {
    "public": 0,
    "organizer_only": 1,
    "platform_admin_only": 2,
}


def _allowed_visibility_levels(*, user, hackathon_id=None, organization_id=None) -> list[str]:
    """
    Determines which visibility values this user may see.
    
    Rules:
    1. Platform Admin -> all levels
    2. Organizer of the hackathon's host org (if hackathon_id) -> public + organizer_only
    3. Organizer of the organization (if org_id) -> public + organizer_only
    4. Authenticated participant / anonymous -> public only
    
    This function is the ONLY place that maps roles to visibility levels.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return ["public"]
    
    if getattr(user, 'is_platform_admin', False):
        return ["public", "organizer_only", "platform_admin_only"]
    
    # Check organizer role for hackathon context
    if hackathon_id is not None:
        from apps.accounts.models import RoleAssignment
        from apps.hackathons.models import Hackathon
        try:
            hackathon = Hackathon.objects.select_related("host_org").get(id=hackathon_id)
            if RoleAssignment.objects.filter(
                user=user,
                role="organizer",
                scope_type="organization",
                scope_id=hackathon.host_org_id,
            ).exists():
                return ["public", "organizer_only"]
        except Hackathon.DoesNotExist:
            pass
    
    # Check organizer role for organization context
    if organization_id is not None:
        from apps.accounts.models import RoleAssignment
        if RoleAssignment.objects.filter(
            user=user,
            role="organizer",
            scope_type="organization",
            scope_id=organization_id,
        ).exists():
            return ["public", "organizer_only"]
    
    return ["public"]


def _build_scope_filter(*, hackathon_id=None, organization_id=None):
    """
    Build the Q object that enforces context scoping.
    A hackathon-scoped session sees:
      - chunks scoped to THAT hackathon, OR
      - platform-wide public chunks (hackathon_id IS NULL AND visibility='public')
    but NOT chunks scoped to a different hackathon.
    A general session (no hackathon/org specified) sees all public content across the platform.
    """
    if hackathon_id is not None:
        return Q(hackathon_id=hackathon_id) | Q(hackathon_id__isnull=True, visibility="public")
    if organization_id is not None:
        return Q(organization_id=organization_id) | Q(organization_id__isnull=True, visibility="public")
    # No context: all public platform-wide chunks (FAQs, articles, published hackathons)
    return Q(visibility="public")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors. Pure function."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


STOP_WORDS = {
    "the", "is", "at", "on", "a", "an", "and", "to", "in", "of", "it", "be", "are",
    "do", "does", "did", "for", "or", "can", "could", "should", "would", "tell",
    "me", "give", "you", "your", "my", "this", "that", "these", "those", "what",
    "where", "when", "which", "who", "whom", "how", "why", "about", "i", "we"
}


def _stem_term(w: str) -> str:
    w = w.strip("?,.:!;\n\r\"'()[]").lower()
    if not w:
        return ""
    # Participation & Team
    if w in ("solo", "alone", "individual"):
        return "individual"
    if w.startswith("team") or w == "roster":
        return "team"
    if w.startswith("member"):
        return "member"
    # Rules & Guidelines
    if w.startswith("rule") or w.startswith("guideline") or w.startswith("policy"):
        return "rule"
    if w.startswith("eligib"):
        return "eligib"
    if w.startswith("require"):
        return "require"
    # Submissions & Projects
    if w.startswith("submit") or w in ("submission", "submissions"):
        return "submit"
    if w.startswith("project"):
        return "project"
    if w.startswith("deliverable"):
        return "deliverable"
    if w in ("repo", "repository", "github", "gitlab"):
        return "repo"
    if w in ("demo", "video", "youtube", "loom"):
        return "demo"
    if w.startswith("hackathon") or w.startswith("compet"):
        return "hackathon"
    # Judging & Scoring
    if w.startswith("judge") or w.startswith("judging"):
        return "judg"
    if w.startswith("rubric") or w.startswith("criteria"):
        return "rubric"
    if w.startswith("score") or w.startswith("scoring"):
        return "score"
    if w in ("blind", "bias", "unbiased", "anonymous"):
        return "blind_judg"
    # Payments & Prizes
    if w.startswith("prize") or w.startswith("award"):
        return "prize"
    if w.startswith("payout") or w.startswith("payment") or w.startswith("disburs") or w == "cash":
        return "payment"
    if w in ("telebirr", "cbe", "cbebirr", "chapa", "birr", "etb"):
        return w
    # Cost & Free
    if w in ("free", "cost", "fee", "fees", "price", "charge"):
        return "free_cost"
    # Language
    if w in ("amharic", "english", "language", "translate", "switch"):
        return w
    # Verification & Badges
    if w.startswith("badge") or w.startswith("verif"):
        return "verif"
    # Architecture & Tech
    if w.startswith("architect") or w in ("monolith", "microservice", "stack"):
        return "architect"
    if w in ("security", "encrypt", "jwt", "auth", "token"):
        return "security"
    return w


class _InMemoryFallbackChunk:
    def __init__(self, text: str, title: str, category: str = ""):
        import uuid
        self.id = uuid.uuid4()
        self.text = text
        self.visibility = "public"
        self.source_type = "faq"
        self.source_id = self.id
        self.metadata = {"title": title, "question": title, "category": category}
        self.embedding = []
        self.hackathon_id = None
        self.organization_id = None


def _load_in_memory_faqs() -> list:
    """Parses docs/faq_knowledge_base.md into in-memory fallback chunks."""
    import os
    import re
    from django.conf import settings
    chunks = []
    try:
        base_dir = getattr(settings, 'BASE_DIR', '')
        kb_path = os.path.join(base_dir, "docs", "faq_knowledge_base.md") if base_dir else "docs/faq_knowledge_base.md"
        if not os.path.exists(kb_path):
            return chunks
        with open(kb_path, "r", encoding="utf-8") as f:
            content = f.read()

        category_blocks = re.split(r'\n(?=## \d+\. |\n## PART )', content)
        for block in category_blocks:
            lines = block.strip().split("\n")
            if not lines or not lines[0].strip().startswith("## "):
                continue
            cat_match = re.search(r'## (?:\d+\.\s*)?([^\n]+)', lines[0].strip())
            cat_name = cat_match.group(1).strip() if cat_match else ""
            if cat_name.startswith("PART"):
                continue

            faq_blocks = re.split(r'\n(?=### Q:)', block)
            for fb in faq_blocks:
                if not fb.strip().startswith("### Q:"):
                    continue
                flines = fb.strip().split("\n")
                q_text = flines[0].replace("### Q:", "").strip()
                ans_text = "\n".join(flines[1:]).strip()
                if q_text and ans_text:
                    full_chunk_text = f"### Q: {q_text}\n{ans_text}"
                    chunks.append(_InMemoryFallbackChunk(text=full_chunk_text, title=q_text, category=cat_name))
    except Exception:
        pass
    return chunks


def _ensure_knowledge_base_seeded():
    """
    Ensures that published FAQs from docs/faq_knowledge_base.md are seeded
    in the database and indexed into DocumentChunk.
    """
    try:
        from .models import DocumentChunk
        if DocumentChunk.objects.filter(source_type="faq").count() >= 10:
            return

        from apps.knowledge_base.models import Category, FAQ
        from .embeddings import index_faq
        from django.conf import settings
        from django.utils import timezone
        from django.utils.text import slugify
        import os
        import re

        if FAQ.objects.filter(status="published").count() < 10:
            base_dir = getattr(settings, 'BASE_DIR', '')
            kb_path = os.path.join(base_dir, "docs", "faq_knowledge_base.md") if base_dir else "docs/faq_knowledge_base.md"
            if os.path.exists(kb_path):
                with open(kb_path, "r", encoding="utf-8") as f:
                    content = f.read()

                category_blocks = re.split(r'\n(?=## \d+\. |\n## PART )', content)
                sort_order = 0
                for block in category_blocks:
                    lines = block.strip().split("\n")
                    if not lines or not lines[0].strip().startswith("## "):
                        continue

                    cat_match = re.search(r'## (?:\d+\.\s*)?([^\n]+)', lines[0].strip())
                    if not cat_match or cat_match.group(1).strip().startswith("PART"):
                        continue

                    cat_name = cat_match.group(1).strip()
                    cat_slug = slugify(cat_name) or f"category-{sort_order}"
                    sort_order += 1

                    category, _ = Category.objects.get_or_create(
                        slug=cat_slug,
                        defaults={
                            "name": cat_name,
                            "description": f"Articles and FAQs regarding {cat_name}.",
                            "sort_order": sort_order,
                        }
                    )

                    faq_blocks = re.split(r'\n(?=### Q:)', block)
                    faq_idx = 0
                    for fb in faq_blocks:
                        if not fb.strip().startswith("### Q:"):
                            continue
                        flines = fb.strip().split("\n")
                        q_text = flines[0].replace("### Q:", "").strip()
                        ans_text = "\n".join(flines[1:]).strip()
                        if not q_text or not ans_text:
                            continue
                        faq_idx += 1
                        FAQ.objects.update_or_create(
                            category=category,
                            question=q_text,
                            defaults={
                                "answer": ans_text,
                                "status": "published",
                                "published_at": timezone.now(),
                                "sort_order": faq_idx,
                            }
                        )

        # Index all published FAQs into DocumentChunk
        for faq in FAQ.objects.filter(status="published"):
            try:
                index_faq(faq.id)
            except Exception:
                pass
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to auto-seed FAQ knowledge base: %s", e)


def retrieve_chunks(
    *,
    query_embedding: list[float],
    user,
    question: str = "",
    hackathon_id=None,
    organization_id=None,
    top_k: int = 5,
) -> list:
    """
    Returns at most top_k DocumentChunk rows, scoped to the user's access level.
    
    Filter chain (mandatory, applied unconditionally):
    1. visibility__in = _allowed_visibility_levels(user, hackathon_id, org_id)
    2. Context scope filter from _build_scope_filter()
    3. Hybrid similarity ranking (vector cosine similarity + title/keyword lexical match)
    """
    from .models import DocumentChunk
    
    # Auto-seed knowledge base if needed for general discovery
    if hackathon_id is None and organization_id is None:
        _ensure_knowledge_base_seeded()

    # Step 1: mandatory visibility filter
    allowed_visibility = _allowed_visibility_levels(
        user=user, hackathon_id=hackathon_id, organization_id=organization_id
    )
    
    # Step 2: context scope filter
    scope_filter = _build_scope_filter(
        hackathon_id=hackathon_id, organization_id=organization_id
    )
    
    # Apply both filters to the queryset (both in the SQL WHERE clause)
    qs = DocumentChunk.objects.filter(visibility__in=allowed_visibility)
    if scope_filter is not None:
        qs = qs.filter(scope_filter)
    
    # Step 3: Retrieve candidates
    candidates = list(qs.only("id", "text", "embedding", "source_type", "source_id",
                               "visibility", "metadata", "hackathon_id", "organization_id"))
    
    # Ultimate in-memory fallback if candidate table has no chunks
    if not candidates and hackathon_id is None and organization_id is None:
        candidates = _load_in_memory_faqs()

    if not candidates:
        return []

    q_norm = question.strip().lower().rstrip("?,.!")
    raw_words = question.strip().split()
    q_terms = [_stem_term(w) for w in raw_words if w.strip("?,.:!;\n\r\"'()[]")]
    q_terms = [t for t in q_terms if t and t not in STOP_WORDS and len(t) > 1]
    q_term_set = set(q_terms)
    
    has_valid_query_vec = isinstance(query_embedding, list) and len(query_embedding) > 0
    
    # Rank by cosine similarity + keyword and question title boost
    scored = []
    for chunk in candidates:
        vec_score = 0.0
        if has_valid_query_vec and isinstance(chunk.embedding, list) and len(chunk.embedding) == len(query_embedding):
            vec_score = _cosine_similarity(query_embedding, chunk.embedding)
            
        keyword_score = 0.0
        chunk_lower = chunk.text.lower()
        title_str = (chunk.metadata.get("title") or chunk.metadata.get("question") or "").strip().lower()
        
        # 1. Exact or substring question match
        if q_norm and len(q_norm) > 3:
            if chunk_lower.startswith(q_norm) or f"### q: {q_norm}" in chunk_lower or q_norm in chunk_lower:
                keyword_score += 2.0
            if title_str and (q_norm in title_str or title_str in q_norm):
                keyword_score += 3.0
                
        # 2. Token / keyword overlap with normalized terms
        if q_term_set:
            chunk_terms = set(_stem_term(w) for w in chunk_lower.split())
            title_terms = set(_stem_term(w) for w in title_str.split()) if title_str else set()
            
            title_matches = q_term_set.intersection(title_terms)
            if title_matches:
                match_ratio = len(title_matches) / len(q_term_set)
                keyword_score += 2.0 * match_ratio
                if len(title_matches) == len(q_term_set):
                    keyword_score += 1.5  # All key terms matched title/question!
                    
            body_matches = q_term_set.intersection(chunk_terms)
            if body_matches:
                match_ratio = len(body_matches) / len(q_term_set)
                keyword_score += 1.0 * match_ratio

        total_score = vec_score + keyword_score
        scored.append((chunk, total_score))
        
    scored = [(chunk, score) for chunk, score in scored if score > 0.05]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [chunk for chunk, _ in scored[:top_k]]

