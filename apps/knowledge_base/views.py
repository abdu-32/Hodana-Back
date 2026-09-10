from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from apps.core.permissions import IsPlatformAdmin
from . import services, serializers

def _get_pagination_params(request):
    try:
        limit = int(request.query_params.get("limit", 20))
    except ValueError:
        limit = 20
    try:
        offset = int(request.query_params.get("offset", 0))
    except ValueError:
        offset = 0
    return limit, offset

class CategoryListView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsPlatformAdmin()]
        return [AllowAny()]

    def get(self, request):
        categories = services.list_categories()
        serializer = serializers.CategorySerializer(categories, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        # We handle this manually for simplicity
        name = request.data.get("name")
        slug = request.data.get("slug")
        description = request.data.get("description", "")
        sort_order = request.data.get("sortOrder", 0)
        
        category = services.create_category(
            actor=request.user,
            name=name,
            slug=slug,
            description=description,
            sort_order=sort_order
        )
        serializer = serializers.CategorySerializer(category)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class ArticleListView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsPlatformAdmin()]
        return [AllowAny()]

    def get(self, request):
        limit, offset = _get_pagination_params(request)
        category_slug = request.query_params.get("categorySlug")
        keyword = request.query_params.get("keyword")
        status_param = request.query_params.get("status", "published")
        
        results, total = services.list_articles(
            category_slug=category_slug,
            keyword=keyword,
            status=status_param,
            limit=limit,
            offset=offset,
            requester=request.user if request.user.is_authenticated else None
        )
        
        data = {
            "data": results,
            "meta": {"limit": limit, "offset": offset, "total": total}
        }
        serializer = serializers.PaginatedArticlesSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = serializers.ArticleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        article = services.create_article(
            actor=request.user,
            **serializer.validated_data
        )
        
        resp_serializer = serializers.ArticleSerializer(article)
        return Response(resp_serializer.data, status=status.HTTP_201_CREATED)

class ArticleDetailView(APIView):
    def get_permissions(self):
        if self.request.method in ["PUT", "DELETE"]:
            return [IsPlatformAdmin()]
        return [AllowAny()]

    def get(self, request, slug):
        article = services.get_article(
            slug=slug,
            requester=request.user if request.user.is_authenticated else None
        )
        serializer = serializers.ArticleSerializer(article)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, slug):
        article = services.get_article(
            slug=slug,
            requester=request.user
        )
        serializer = serializers.ArticleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        updated_article = services.update_article(
            actor=request.user,
            article_id=article.id,
            data=serializer.validated_data
        )
        
        resp_serializer = serializers.ArticleSerializer(updated_article)
        return Response(resp_serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, slug):
        article = services.get_article(
            slug=slug,
            requester=request.user
        )
        services.delete_article(
            actor=request.user,
            article_id=article.id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

class ArticleFeedbackView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, slug):
        article = services.get_article(
            slug=slug,
            requester=request.user
        )
        
        serializer = serializers.ArticleFeedbackCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        services.submit_article_feedback(
            actor=request.user,
            article_id=article.id,
            **serializer.validated_data
        )
        
        return Response({"message": "Feedback submitted successfully"}, status=status.HTTP_201_CREATED)

class FAQListView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsPlatformAdmin()]
        return [AllowAny()]

    def get(self, request):
        limit, offset = _get_pagination_params(request)
        category_slug = request.query_params.get("categorySlug")
        keyword = request.query_params.get("keyword")
        status_param = request.query_params.get("status", "published")
        
        results, total = services.list_faqs(
            category_slug=category_slug,
            keyword=keyword,
            status=status_param,
            limit=limit,
            offset=offset,
            requester=request.user if request.user.is_authenticated else None
        )
        
        data = {
            "data": results,
            "meta": {"limit": limit, "offset": offset, "total": total}
        }
        serializer = serializers.PaginatedFAQsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = serializers.FAQCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        faq = services.create_faq(
            actor=request.user,
            category_id=serializer.validated_data["categoryId"],
            question=serializer.validated_data["question"],
            answer=serializer.validated_data["answer"],
            sort_order=serializer.validated_data.get("sort_order", 0)
        )
        
        resp_serializer = serializers.FAQSerializer(faq)
        return Response(resp_serializer.data, status=status.HTTP_201_CREATED)

class FAQDetailView(APIView):
    def get_permissions(self):
        if self.request.method in ["PUT"]:
            return [IsPlatformAdmin()]
        return [AllowAny()]

    def get(self, request, id):
        faq = services._get_faq_or_404(id)
        serializer = serializers.FAQSerializer(faq)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        # Allow publishing FAQ
        status_val = request.data.get("status")
        if status_val == "published":
            faq = services.publish_faq(
                actor=request.user,
                faq_id=id
            )
            serializer = serializers.FAQSerializer(faq)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        return Response({"error": "Unsupported update operation"}, status=status.HTTP_400_BAD_REQUEST)

class ArticleSearchView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        limit, offset = _get_pagination_params(request)
        keyword = request.query_params.get("keyword", "")
        
        results, total = services.search_articles(
            keyword=keyword,
            limit=limit,
            offset=offset
        )
        
        data = {
            "data": results,
            "meta": {"limit": limit, "offset": offset, "total": total}
        }
        serializer = serializers.PaginatedArticlesSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)
