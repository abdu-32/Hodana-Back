import re
from django.utils.text import slugify
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, F
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from apps.core.models import AuditLogEntry
from apps.accounts.models import Account
from .models import Category, Article, ArticleVersion, FAQ, ArticleFeedback

def _get_category_or_404(category_id):
    try:
        return Category.objects.get(id=category_id)
    except Category.DoesNotExist:
        raise NotFound("Category not found.")

def _get_article_or_404(article_id):
    try:
        return Article.objects.get(id=article_id)
    except Article.DoesNotExist:
        raise NotFound("Article not found.")

def _get_article_by_slug_or_404(slug):
    try:
        return Article.objects.get(slug=slug)
    except Article.DoesNotExist:
        raise NotFound("Article not found.")

def _get_faq_or_404(faq_id):
    try:
        return FAQ.objects.get(id=faq_id)
    except FAQ.DoesNotExist:
        raise NotFound("FAQ not found.")

def _unique_article_slug(title, exclude_id=None):
    base_slug = slugify(title)
    if not base_slug:
        base_slug = "article"
    slug = base_slug
    counter = 1
    qs = Article.objects.filter(slug=slug)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    while qs.exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
        qs = Article.objects.filter(slug=slug)
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
    return slug

def list_categories():
    return Category.objects.all().order_by("sort_order", "name")

def create_category(*, actor, name, slug=None, description="", sort_order=0):
    if not getattr(actor, 'is_platform_admin', False):
        raise PermissionDenied("Only Platform Admins can create categories.")
    
    if not slug:
        slug = slugify(name)
        if not slug:
            slug = "category"
        base_slug = slug
        counter = 1
        while Category.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
            
    if Category.objects.filter(name=name).exists():
        raise ValidationError({"name": ["Category with this name already exists."]})
    if Category.objects.filter(slug=slug).exists():
        raise ValidationError({"slug": ["Category with this slug already exists."]})
        
    category = Category.objects.create(
        name=name,
        slug=slug,
        description=description,
        sort_order=sort_order
    )
    
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="create_category",
        target_type="Category",
        target_id=str(category.id),
        metadata={"name": name, "slug": slug}
    )
    
    return category

@transaction.atomic
def create_article(*, actor, category_id, title, body, slug=None):
    """FR-KB-001: Article lifecycle - create"""
    if not getattr(actor, 'is_platform_admin', False):
        raise PermissionDenied("Only Platform Admins can create articles.")
        
    category = _get_category_or_404(category_id)
    
    if not slug:
        slug = _unique_article_slug(title)
    else:
        if Article.objects.filter(slug=slug).exists():
            raise ValidationError({"slug": ["Article with this slug already exists."]})
            
    article = Article.objects.create(
        category=category,
        title=title,
        body=body,
        slug=slug,
        status="draft",
        author=actor if isinstance(actor, Account) else None
    )
    
    ArticleVersion.objects.create(
        article=article,
        title=title,
        body=body,
        edited_by=actor if isinstance(actor, Account) else None
    )
    
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="create_article",
        target_type="Article",
        target_id=str(article.id),
        metadata={"title": title, "slug": slug}
    )
    
    return article

@transaction.atomic
def update_article(*, actor, article_id, data: dict):
    """FR-KB-001: Article lifecycle - update"""
    article = _get_article_or_404(article_id)
    
    is_admin = getattr(actor, 'is_platform_admin', False)
    if not is_admin and article.author_id != actor.id:
        raise PermissionDenied("Only Platform Admins or the author can update this article.")
        
    old_title = article.title
    old_body = article.body
    
    if "category_id" in data:
        article.category = _get_category_or_404(data["category_id"])
    if "title" in data:
        article.title = data["title"]
    if "body" in data:
        article.body = data["body"]
    if "status" in data:
        new_status = data["status"]
        if new_status not in ["draft", "published", "archived"]:
            raise ValidationError({"status": ["Invalid status."]})
        article.status = new_status
        if new_status == "published" and article.published_at is None:
            article.published_at = timezone.now()
        elif new_status == "draft":
            article.published_at = None
            
    article.save()
    
    if "title" in data or "body" in data:
        if data.get("title", old_title) != old_title or data.get("body", old_body) != old_body:
            ArticleVersion.objects.create(
                article=article,
                title=article.title,
                body=article.body,
                edited_by=actor
            )
            # Trim versions to 10
            versions = ArticleVersion.objects.filter(article=article).order_by("-created_at")
            if versions.count() > 10:
                versions_to_delete = versions[10:]
                ArticleVersion.objects.filter(id__in=[v.id for v in versions_to_delete]).delete()
                
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="update_article",
        target_type="Article",
        target_id=str(article.id),
        metadata={"fields_updated": list(data.keys())}
    )
    
    return article

def publish_article(*, actor, article_id):
    """FR-KB-001: Article lifecycle - publish"""
    if not getattr(actor, 'is_platform_admin', False):
        raise PermissionDenied("Only Platform Admins can publish articles.")
        
    article = _get_article_or_404(article_id)
    article.status = "published"
    if not article.published_at:
        article.published_at = timezone.now()
    article.save()
    
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="publish_article",
        target_type="Article",
        target_id=str(article.id),
        metadata={}
    )
    return article

def unpublish_article(*, actor, article_id):
    """FR-KB-001: Article lifecycle - unpublish"""
    if not getattr(actor, 'is_platform_admin', False):
        raise PermissionDenied("Only Platform Admins can unpublish articles.")
        
    article = _get_article_or_404(article_id)
    article.status = "draft"
    article.published_at = None
    article.save()
    
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="unpublish_article",
        target_type="Article",
        target_id=str(article.id),
        metadata={}
    )
    return article

def archive_article(*, actor, article_id):
    """FR-KB-001: Article lifecycle - archive"""
    if not getattr(actor, 'is_platform_admin', False):
        raise PermissionDenied("Only Platform Admins can archive articles.")
        
    article = _get_article_or_404(article_id)
    article.status = "archived"
    article.save()
    
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="archive_article",
        target_type="Article",
        target_id=str(article.id),
        metadata={}
    )
    return article

def delete_article(*, actor, article_id):
    """FR-KB-001: Article lifecycle - delete"""
    if not getattr(actor, 'is_platform_admin', False):
        raise PermissionDenied("Only Platform Admins can delete articles.")
        
    article = _get_article_or_404(article_id)
    if article.status != "draft":
        raise ValidationError("Only draft articles can be deleted.")
        
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="delete_article",
        target_type="Article",
        target_id=str(article.id),
        metadata={"title": article.title}
    )
    article.delete()

def get_article(*, slug, requester=None):
    """FR-KB-001: Article lifecycle - get"""
    article = _get_article_by_slug_or_404(slug)
    
    is_admin = getattr(requester, 'is_platform_admin', False) if requester else False
    
    if article.status == "draft":
        if not is_admin and (not requester or article.author_id != requester.id):
            raise NotFound("Article not found.")
    elif article.status == "archived":
        if not is_admin:
            raise NotFound("Article not found.")
            
    # Increment view count safely
    Article.objects.filter(id=article.id).update(view_count=F("view_count") + 1)
    article.refresh_from_db()
    
    return article

def list_articles(*, category_slug=None, keyword=None, status="published", limit=20, offset=0, requester=None):
    """FR-KB-001: Article lifecycle - list"""
    qs = Article.objects.all()
    
    is_admin = getattr(requester, 'is_platform_admin', False) if requester else False
    if not is_admin or status == "published":
        qs = qs.filter(status="published")
    elif status:
        qs = qs.filter(status=status)
        
    if category_slug:
        qs = qs.filter(category__slug=category_slug)
        
    if keyword:
        qs = qs.filter(Q(title__icontains=keyword) | Q(body__icontains=keyword))
        
    qs = qs.order_by("-published_at", "-created_at")
    
    total = qs.count()
    results = list(qs[offset:offset+limit])
    return results, total

def create_faq(*, actor, category_id, question, answer, sort_order=0):
    """FR-KB-001: FAQ lifecycle - create"""
    if not getattr(actor, 'is_platform_admin', False):
        raise PermissionDenied("Only Platform Admins can create FAQs.")
        
    category = _get_category_or_404(category_id)
    
    faq = FAQ.objects.create(
        category=category,
        question=question,
        answer=answer,
        status="draft",
        sort_order=sort_order,
        author=actor if isinstance(actor, Account) else None
    )
    
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="create_faq",
        target_type="FAQ",
        target_id=str(faq.id),
        metadata={"question": question}
    )
    
    return faq

def publish_faq(*, actor, faq_id):
    """FR-KB-001: FAQ lifecycle - publish"""
    if not getattr(actor, 'is_platform_admin', False):
        raise PermissionDenied("Only Platform Admins can publish FAQs.")
        
    faq = _get_faq_or_404(faq_id)
    faq.status = "published"
    if not faq.published_at:
        faq.published_at = timezone.now()
    faq.save()
    
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="publish_faq",
        target_type="FAQ",
        target_id=str(faq.id),
        metadata={}
    )
    
    return faq

def list_faqs(*, category_slug=None, keyword=None, status="published", limit=20, offset=0, requester=None):
    """FR-KB-001: FAQ lifecycle - list"""
    qs = FAQ.objects.all()
    
    is_admin = getattr(requester, 'is_platform_admin', False) if requester else False
    if not is_admin or status == "published":
        qs = qs.filter(status="published")
    elif status:
        qs = qs.filter(status=status)
        
    if category_slug:
        qs = qs.filter(category__slug=category_slug)
        
    if keyword:
        qs = qs.filter(Q(question__icontains=keyword) | Q(answer__icontains=keyword))

    qs = qs.order_by("sort_order", "-created_at")
        
    total = qs.count()
    results = list(qs[offset:offset+limit])
    return results, total

def search_articles(*, keyword, limit=20, offset=0):
    """FR-KB-002: Knowledge base search"""
    qs = Article.objects.filter(status="published")
    
    if keyword:
        qs = qs.filter(Q(title__icontains=keyword) | Q(body__icontains=keyword))
        
    qs = qs.order_by("-published_at")
    
    total = qs.count()
    results = list(qs[offset:offset+limit])
    return results, total

def submit_article_feedback(*, actor, article_id, is_helpful, comment=""):
    """FR-KB-003: Article feedback"""
    article = _get_article_or_404(article_id)
    
    if article.status != "published":
        raise ValidationError("Cannot provide feedback on non-published articles.")
        
    feedback, created = ArticleFeedback.objects.update_or_create(
        article=article,
        user=actor,
        defaults={"is_helpful": is_helpful, "comment": comment}
    )
    
    return feedback
