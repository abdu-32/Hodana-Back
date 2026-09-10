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
    """
    if hackathon_id is not None:
        return Q(hackathon_id=hackathon_id) | Q(hackathon_id__isnull=True, visibility="public")
    if organization_id is not None:
        return Q(organization_id=organization_id) | Q(organization_id__isnull=True, visibility="public")
    # No context: only platform-wide public
    return Q(hackathon_id__isnull=True, organization_id__isnull=True)


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
    3. Similarity ranking (cosine similarity over embedding JSON vectors + question title boost)
    """
    from .models import DocumentChunk
    
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
    
    # Step 3: Retrieve candidates and rank by similarity
    candidates = list(qs.only("id", "text", "embedding", "source_type", "source_id",
                               "visibility", "metadata", "hackathon_id", "organization_id"))
    
    if not candidates or not query_embedding:
        return []
    
    q_norm = question.strip().lower().rstrip("?,.!")
    
    # Rank by cosine similarity + question title exact match boost
    scored = []
    for chunk in candidates:
        if not isinstance(chunk.embedding, list) or len(chunk.embedding) != len(query_embedding):
            continue
        score = _cosine_similarity(query_embedding, chunk.embedding)
        
        # Boost candidate if the chunk's question text matches the user query
        if q_norm and len(q_norm) > 3:
            chunk_lower = chunk.text.lower()
            if chunk_lower.startswith(q_norm) or f"### {q_norm}" in chunk_lower or q_norm in chunk_lower:
                score += 1.0
                
        scored.append((chunk, score))
        
    scored = [(chunk, score) for chunk, score in scored if score >= 0.15]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [chunk for chunk, _ in scored[:top_k]]
