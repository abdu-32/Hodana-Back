from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from . import serializers, services

class ChatView(APIView):
    """FR-AI-001. POST /api/v1/ai/chat/"""
    permission_classes = [AllowAny]

    def post(self, request):
        ser = serializers.ChatRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = services.chat(actor=request.user, **ser.validated_data)
        return Response(serializers.ChatResponseSerializer(result).data)

class AIFeedbackView(APIView):
    """FR-AI-002. POST /api/v1/ai/feedback/"""
    def post(self, request):
        ser = serializers.AIFeedbackCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        feedback = services.submit_feedback(actor=request.user, **ser.validated_data)
        return Response(serializers.AIFeedbackSerializer(feedback).data, status=status.HTTP_201_CREATED)
