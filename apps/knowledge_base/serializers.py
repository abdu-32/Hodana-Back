from rest_framework import serializers
from .models import Category, Article, FAQ, ArticleFeedback

class CategorySerializer(serializers.ModelSerializer):
    sortOrder = serializers.IntegerField(source="sort_order", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "sortOrder", "createdAt", "updatedAt"]

class ArticleSerializer(serializers.ModelSerializer):
    categoryId = serializers.UUIDField(source="category_id", read_only=True)
    viewCount = serializers.IntegerField(source="view_count", read_only=True)
    publishedAt = serializers.DateTimeField(source="published_at", read_only=True)
    authorId = serializers.UUIDField(source="author_id", read_only=True, allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Article
        fields = ["id", "categoryId", "title", "slug", "body", "status", "viewCount", "publishedAt", "authorId", "createdAt", "updatedAt"]

class ArticleCreateSerializer(serializers.Serializer):
    categoryId = serializers.UUIDField(source="category_id")
    title = serializers.CharField(max_length=255)
    body = serializers.CharField()
    slug = serializers.CharField(max_length=255, required=False, allow_blank=True)

class ArticleUpdateSerializer(serializers.Serializer):
    categoryId = serializers.UUIDField(source="category_id", required=False)
    title = serializers.CharField(max_length=255, required=False)
    body = serializers.CharField(required=False)
    status = serializers.ChoiceField(choices=["draft", "published", "archived"], required=False)

class FAQSerializer(serializers.ModelSerializer):
    categoryId = serializers.UUIDField(source="category_id", read_only=True)
    sortOrder = serializers.IntegerField(source="sort_order", read_only=True)
    publishedAt = serializers.DateTimeField(source="published_at", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = FAQ
        fields = ["id", "categoryId", "question", "answer", "status", "sortOrder", "publishedAt", "createdAt", "updatedAt"]

class FAQCreateSerializer(serializers.Serializer):
    categoryId = serializers.UUIDField()
    question = serializers.CharField(max_length=500)
    answer = serializers.CharField()
    sortOrder = serializers.IntegerField(source="sort_order", required=False, default=0)

class ArticleFeedbackCreateSerializer(serializers.Serializer):
    isHelpful = serializers.BooleanField(source="is_helpful")
    comment = serializers.CharField(required=False, allow_blank=True, default="")

class PaginationMetaSerializer(serializers.Serializer):
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    total = serializers.IntegerField()

class PaginatedArticlesSerializer(serializers.Serializer):
    data = ArticleSerializer(many=True)
    meta = PaginationMetaSerializer()

class PaginatedFAQsSerializer(serializers.Serializer):
    data = FAQSerializer(many=True)
    meta = PaginationMetaSerializer()

class ArticleSearchResultSerializer(ArticleSerializer):
    pass
