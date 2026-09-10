import uuid
from django.db import models
from django.conf import settings
from apps.core.models import TimeStampedModel

class ScopedChunkManager(models.Manager):
    """
    Required entry point for all DocumentChunk retrieval queries.
    Direct .filter()/.all() for retrieval is forbidden.
    The only sanctioned retrieval path is retriever.retrieve_chunks().
    """
    def visible_to(self, *, user, hackathon_id=None, organization_id=None):
        """Pre-filter queryset by user's visibility level.
        Called exclusively from retriever.py."""
        from .retriever import _allowed_visibility_levels, _build_scope_filter
        allowed = _allowed_visibility_levels(
            user=user, hackathon_id=hackathon_id, organization_id=organization_id
        )
        qs = self.get_queryset().filter(visibility__in=allowed)
        scope_filter = _build_scope_filter(
            hackathon_id=hackathon_id, organization_id=organization_id
        )
        if scope_filter is not None:
            qs = qs.filter(scope_filter)
        return qs


class DocumentChunk(TimeStampedModel):
    SOURCE_CHOICES = (
        ("article", "Article"),
        ("faq", "FAQ"),
        ("hackathon_rules", "Hackathon Rules"),
        ("hackathon_description", "Hackathon Description"),
        ("hackathon_rubric_criteria", "Hackathon Rubric Criteria"),
        ("showcase_project", "Showcase Project"),
    )
    VISIBILITY_CHOICES = (
        ("public", "Public"),
        ("organizer_only", "Organizer Only"),
        ("platform_admin_only", "Platform Admin Only"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_type = models.CharField(max_length=50, choices=SOURCE_CHOICES)
    source_id = models.UUIDField()
    organization_id = models.UUIDField(null=True, blank=True)
    hackathon_id = models.UUIDField(null=True, blank=True)
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default="public")
    text = models.TextField()
    embedding = models.JSONField(default=list)
    chunk_index = models.IntegerField(default=0)
    metadata = models.JSONField(default=dict)

    objects = ScopedChunkManager()

    class Meta:
        indexes = [
            models.Index(fields=["source_type", "source_id"]),
            models.Index(fields=["visibility"]),
            models.Index(fields=["hackathon_id"]),
            models.Index(fields=["organization_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "source_id", "chunk_index"],
                name="unique_chunk_per_source"
            )
        ]


class ChatSession(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.Account",
        on_delete=models.SET_NULL,
        null=True,
        related_name="ai_chat_sessions"
    )
    hackathon_id = models.UUIDField(null=True, blank=True)
    organization_id = models.UUIDField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
        ]


class ChatMessage(models.Model):
    ROLE_CHOICES = (
        ("user", "User"),
        ("assistant", "Assistant"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    retrieved_chunk_ids = models.JSONField(default=list)
    llm_model = models.CharField(max_length=100, blank=True, default="")
    latency_ms = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class AIFeedback(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="feedback")
    user = models.ForeignKey(
        "accounts.Account",
        on_delete=models.SET_NULL,
        null=True,
        related_name="ai_feedback_given"
    )
    rating = models.SmallIntegerField()
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["message", "user"], name="unique_ai_feedback_per_user")
        ]
