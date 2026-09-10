import factory
from factory.django import DjangoModelFactory
from django.utils import timezone
from apps.knowledge_base.models import Category, Article, FAQ, ArticleFeedback

class CategoryFactory(DjangoModelFactory):
    class Meta:
        model = Category
    name = factory.Sequence(lambda n: f"Category {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")

class ArticleFactory(DjangoModelFactory):
    class Meta:
        model = Article
    category = factory.SubFactory(CategoryFactory)
    title = factory.Sequence(lambda n: f"Article {n}")
    slug = factory.Sequence(lambda n: f"article-{n}")
    body = "Test article body content."
    status = "draft"

class PublishedArticleFactory(ArticleFactory):
    status = "published"
    published_at = factory.LazyFunction(timezone.now)

class FAQFactory(DjangoModelFactory):
    class Meta:
        model = FAQ
    category = factory.SubFactory(CategoryFactory)
    question = factory.Sequence(lambda n: f"Question {n}?")
    answer = "Test answer."
    status = "draft"

class PublishedFAQFactory(FAQFactory):
    status = "published"
