import uuid
import pytest
from apps.support_ai.retriever import retrieve_chunks
from apps.support_ai.tests.factories import DocumentChunkFactory
from apps.accounts.tests.factories import AccountFactory

pytestmark = pytest.mark.django_db

def test_tc_rag_leak_001_org_isolation():
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    user = AccountFactory()
    
    DocumentChunkFactory(organization_id=org_a, text="Org A doc")
    DocumentChunkFactory(organization_id=org_b, text="Org B doc")
    
    chunks = retrieve_chunks(
        query_embedding=[0.1]*1536,
        user=user,
        organization_id=org_a
    )
    assert len(chunks) == 1
    assert chunks[0].text == "Org A doc"

def test_tc_rag_leak_002_participant_cannot_see_organizer_only():
    user = AccountFactory()
    DocumentChunkFactory(visibility="organizer_only", text="Secret")
    DocumentChunkFactory(visibility="public", text="Public")
    
    chunks = retrieve_chunks(
        query_embedding=[0.1]*1536,
        user=user,
    )
    assert len(chunks) == 1
    assert chunks[0].text == "Public"

def test_tc_rag_leak_003_hackathon_isolation():
    hack_a = uuid.uuid4()
    hack_b = uuid.uuid4()
    user = AccountFactory()
    
    DocumentChunkFactory(hackathon_id=hack_a, text="Hack A doc")
    DocumentChunkFactory(hackathon_id=hack_b, text="Hack B doc")
    
    chunks = retrieve_chunks(
        query_embedding=[0.1]*1536,
        user=user,
        hackathon_id=hack_a
    )
    assert len(chunks) == 1
    assert chunks[0].text == "Hack A doc"

def test_tc_rag_leak_004_platform_admin_only():
    from unittest.mock import patch
    user = AccountFactory()
    
    DocumentChunkFactory(visibility="platform_admin_only", text="Admin Secret")
    
    chunks = retrieve_chunks(
        query_embedding=[0.1]*1536,
        user=user,
    )
    assert len(chunks) == 0
    
    with patch("apps.support_ai.retriever._allowed_visibility_levels", return_value=["public", "organizer_only", "platform_admin_only"]):
        admin_chunks = retrieve_chunks(
            query_embedding=[0.1]*1536,
            user=user,
        )
        assert len(admin_chunks) == 1

def test_tc_rag_leak_005_anonymous_user():
    DocumentChunkFactory(visibility="organizer_only", text="Secret")
    DocumentChunkFactory(visibility="public", text="Public")
    
    chunks = retrieve_chunks(
        query_embedding=[0.1]*1536,
        user=None,
    )
    assert len(chunks) == 1
    assert chunks[0].text == "Public"

def test_tc_rag_leak_006_semantic_adjacency():
    user = AccountFactory()
    hack_a = uuid.uuid4()
    
    # Highly similar but wrong scope
    DocumentChunkFactory(text="Match", embedding=[0.9]*1536, hackathon_id=uuid.uuid4())
    # Less similar but right scope
    DocumentChunkFactory(text="Right", embedding=[0.1]*1536, hackathon_id=hack_a)
    
    chunks = retrieve_chunks(
        query_embedding=[0.9]*1536,
        user=user,
        hackathon_id=hack_a
    )
    assert len(chunks) == 1
    assert chunks[0].text == "Right"

def test_retrieve_hackathon_rules_query():
    user = AccountFactory()
    DocumentChunkFactory(
        visibility="public",
        text="All hackathons hosted on the Ethiopia Innovation Hub follow standard platform rules and guidelines: 1. Eligibility 2. Team Composition 3. Originality",
        metadata={"title": "What are the hackathon rules?", "question": "What are the hackathon rules?"}
    )
    DocumentChunkFactory(
        visibility="public",
        text="You can access the platform on any device with a web browser.",
        metadata={"title": "Which devices can I use to access the platform?", "question": "Which devices can I use to access the platform?"}
    )
    
    chunks = retrieve_chunks(
        query_embedding=[],
        user=user,
        question="What are the hackathon rules?"
    )
    assert len(chunks) >= 1
    assert "hackathon rules and guidelines" in chunks[0].text

def test_retrieve_chunks_keyword_fallback_when_embedding_empty():
    user = AccountFactory()
    chunk = DocumentChunkFactory(
        visibility="public",
        text="Official guidelines for hackathon submissions: provide code repo and demo video.",
        metadata={"title": "Hackathon Submission Guidelines"}
    )
    
    chunks = retrieve_chunks(
        query_embedding=[],
        user=user,
        question="What are the hackathon guidelines?"
    )
    assert len(chunks) >= 1
    assert chunks[0].id == chunk.id


def test_retrieve_chunks_semantic_synonym_matching():
    user = AccountFactory()
    chunk_team = DocumentChunkFactory(
        visibility="public",
        text="Can I participate as an individual, or do I need a team? Some hackathons allow solo entries, but most require teams of 2 to 5 members.",
        metadata={"title": "Can I participate as an individual, or do I need a team?"}
    )
    chunk_free = DocumentChunkFactory(
        visibility="public",
        text="Is the platform free to use? Creating an account and submitting projects is 100% free for participants.",
        metadata={"title": "Is the platform free to use?"}
    )
    
    # Test solo query maps to individual/team chunk
    chunks_solo = retrieve_chunks(
        query_embedding=[],
        user=user,
        question="Can I join solo without a team?"
    )
    assert len(chunks_solo) >= 1
    assert chunks_solo[0].id == chunk_team.id

    # Test fee/cost query maps to free chunk
    chunks_cost = retrieve_chunks(
        query_embedding=[],
        user=user,
        question="What is the fee or cost to use the platform?"
    )
    assert len(chunks_cost) >= 1
    assert chunks_cost[0].id == chunk_free.id


