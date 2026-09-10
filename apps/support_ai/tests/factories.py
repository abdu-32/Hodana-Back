import uuid
import factory
from factory.django import DjangoModelFactory
from apps.support_ai.models import DocumentChunk, ChatSession, ChatMessage, AIFeedback
from apps.accounts.tests.factories import AccountFactory


class DocumentChunkFactory(DjangoModelFactory):
    class Meta:
        model = DocumentChunk
    
    source_type = "article"
    source_id = factory.LazyFunction(uuid.uuid4)
    visibility = "public"
    text = "Test chunk text."
    embedding = factory.LazyFunction(lambda: [0.1] * 1536)
    chunk_index = 0

class ChatSessionFactory(DjangoModelFactory):
    class Meta:
        model = ChatSession
    user = factory.SubFactory(AccountFactory)

class ChatMessageFactory(DjangoModelFactory):
    class Meta:
        model = ChatMessage
    session = factory.SubFactory(ChatSessionFactory)
    role = "assistant"
    content = "Test response."
