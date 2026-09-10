import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from apps.core.models import TimeStampedModel

CONTENT_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("published", "Published"),
    ("archived", "Archived")
]

class Category(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        app_label = "knowledge_base"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

class Article(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="articles")
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=CONTENT_STATUS_CHOICES, default="draft")
    author = models.ForeignKey("accounts.Account", on_delete=models.SET_NULL, null=True, blank=True, related_name="kb_articles_authored")
    view_count = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "category"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return self.title

class ArticleVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="versions")
    title = models.CharField(max_length=255)
    body = models.TextField()
    edited_by = models.ForeignKey("accounts.Account", on_delete=models.SET_NULL, null=True, blank=True, related_name="kb_article_versions_edited")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

class FAQ(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="faqs")
    question = models.CharField(max_length=500)
    answer = models.TextField()
    status = models.CharField(max_length=20, choices=CONTENT_STATUS_CHOICES, default="draft")
    sort_order = models.IntegerField(default=0)
    author = models.ForeignKey("accounts.Account", on_delete=models.SET_NULL, null=True, blank=True, related_name="kb_faqs_authored")
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["sort_order", "created_at"]

    def __str__(self):
        return self.question

class ArticleFeedback(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="feedback")
    user = models.ForeignKey("accounts.Account", on_delete=models.SET_NULL, null=True, blank=True, related_name="kb_feedback_given")
    is_helpful = models.BooleanField()
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["article", "user"], name="unique_article_feedback_per_user")
        ]
