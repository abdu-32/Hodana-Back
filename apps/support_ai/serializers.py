from rest_framework import serializers
from .models import ChatSession, ChatMessage, AIFeedback

class ChatRequestSerializer(serializers.Serializer):
    """POST /api/v1/ai/chat/ request body. Supports both camelCase and snake_case keys."""
    sessionId = serializers.UUIDField(required=False, allow_null=True)
    session_id = serializers.UUIDField(required=False, allow_null=True)
    hackathonId = serializers.UUIDField(required=False, allow_null=True)
    hackathon_id = serializers.UUIDField(required=False, allow_null=True)
    organizationId = serializers.UUIDField(required=False, allow_null=True)
    organization_id = serializers.UUIDField(required=False, allow_null=True)
    question = serializers.CharField(max_length=2000)

    def validate(self, attrs):
        session_id = attrs.get("session_id") or attrs.get("sessionId")
        hackathon_id = attrs.get("hackathon_id") or attrs.get("hackathonId")
        organization_id = attrs.get("organization_id") or attrs.get("organizationId")
        return {
            "session_id": session_id,
            "hackathon_id": hackathon_id,
            "organization_id": organization_id,
            "question": attrs["question"],
        }

class ChatResponseSerializer(serializers.Serializer):
    """POST /api/v1/ai/chat/ response body. Emits both camelCase and snake_case keys."""
    sessionId = serializers.UUIDField(source="session_id")
    session_id = serializers.UUIDField()
    messageId = serializers.UUIDField(source="message_id")
    message_id = serializers.UUIDField()
    answer = serializers.CharField()
    llmUnavailable = serializers.BooleanField(source="llm_unavailable")
    llm_unavailable = serializers.BooleanField()
    retrievedChunkCount = serializers.IntegerField(source="retrieved_chunk_count")
    retrieved_chunk_count = serializers.IntegerField()
    relatedQuestions = serializers.ListField(child=serializers.CharField(), source="related_questions", required=False, default=list)
    related_questions = serializers.ListField(child=serializers.CharField(), required=False, default=list)

class AIFeedbackCreateSerializer(serializers.Serializer):
    """POST /api/v1/ai/feedback/ request body. Supports both camelCase and snake_case."""
    messageId = serializers.UUIDField(required=False, allow_null=True)
    message_id = serializers.UUIDField(required=False, allow_null=True)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        message_id = attrs.get("message_id") or attrs.get("messageId")
        if not message_id:
            raise serializers.ValidationError({"messageId": "messageId or message_id is required."})
        return {
            "message_id": message_id,
            "rating": attrs["rating"],
            "comment": attrs.get("comment", ""),
        }

class AIFeedbackSerializer(serializers.ModelSerializer):
    messageId = serializers.UUIDField(source="message_id", read_only=True)
    userId = serializers.UUIDField(source="user_id", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    class Meta:
        model = AIFeedback
        fields = ["id", "messageId", "userId", "rating", "comment", "createdAt"]
