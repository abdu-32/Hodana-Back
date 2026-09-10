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
