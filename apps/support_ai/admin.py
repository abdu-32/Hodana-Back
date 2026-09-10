from django.contrib import admin
from .models import DocumentChunk, ChatSession, ChatMessage, AIFeedback

@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ["id", "source_type", "visibility", "hackathon_id", "organization_id"]
    list_filter = ["source_type", "visibility"]

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "hackathon_id", "organization_id", "created_at"]

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ["id", "session", "role", "created_at"]
    list_filter = ["role"]

@admin.register(AIFeedback)
class AIFeedbackAdmin(admin.ModelAdmin):
    list_display = ["id", "message", "user", "rating", "created_at"]
    list_filter = ["rating"]
