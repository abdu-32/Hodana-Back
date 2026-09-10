import pytest
import uuid
from unittest.mock import MagicMock
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from apps.accounts.tests.factories import AccountFactory
from apps.knowledge_base.services import (
    create_article, publish_article, get_article, list_articles,
    search_articles, submit_article_feedback, create_faq
)
from apps.knowledge_base.models import Article, ArticleVersion, ArticleFeedback
from apps.core.models import AuditLogEntry

def test_create_article(category):
    actor = AccountFactory(is_platform_admin=True)
    
    article = create_article(
        actor=actor,
        category_id=category.id,
        title="Test Article",
        body="Content"
    )
    
    assert article.status == "draft"
    assert article.slug == "test-article"
    
    # Check version was created
    assert ArticleVersion.objects.filter(article=article).count() == 1
    
    # Check audit log
    assert AuditLogEntry.objects.filter(action="create_article", target_id=str(article.id)).exists()

def test_publish_article(published_article):
    # Using a draft article instead
    published_article.status = "draft"
    published_article.published_at = None
    published_article.save()
    
    actor = AccountFactory(is_platform_admin=True)
    article = publish_article(actor=actor, article_id=published_article.id)
    
    assert article.status == "published"
    assert article.published_at is not None

def test_publish_article_permission_denied(published_article):
    published_article.status = "draft"
    published_article.save()
    
    actor = AccountFactory(is_platform_admin=False)
    with pytest.raises(PermissionDenied):
        publish_article(actor=actor, article_id=published_article.id)

def test_get_article(published_article):
    # Published accessible to anyone
    article = get_article(slug=published_article.slug)
    assert article.id == published_article.id
    
    # View count should be incremented
    assert article.view_count == 1

def test_get_article_draft_not_admin(published_article):
    published_article.status = "draft"
    published_article.save()
    
    with pytest.raises(NotFound):
        get_article(slug=published_article.slug)

def test_list_articles(published_article):
    # Create one draft
    draft_article = published_article
    draft_article.pk = None
    draft_article.slug = "draft-1"
    draft_article.status = "draft"
    draft_article.save()
    
    results, total = list_articles()
    assert total == 1
    assert results[0].status == "published"

def test_search_articles(category):
    # Published accessible to anyone
    actor = AccountFactory(is_platform_admin=True)
    article = create_article(
        actor=actor,
        category_id=category.id,
        title="UniqueTitle",
        body="Content Body"
    )
    publish_article(actor=actor, article_id=article.id)
    
    results, total = search_articles(keyword="UniqueTitle")
    assert total == 1
    assert results[0].id == article.id

def test_submit_feedback(published_article):
    actor = AccountFactory(is_platform_admin=False)
    feedback = submit_article_feedback(
        actor=actor,
        article_id=published_article.id,
        is_helpful=True,
        comment="Great!"
    )
    
    assert feedback.is_helpful is True
    assert ArticleFeedback.objects.count() == 1
    
    # Second submission updates
    feedback2 = submit_article_feedback(
        actor=actor,
        article_id=published_article.id,
        is_helpful=False,
        comment="Not great."
    )
    
    assert ArticleFeedback.objects.count() == 1
    assert feedback2.id == feedback.id
    assert feedback2.is_helpful is False

def test_create_faq(category):
    actor = AccountFactory(is_platform_admin=True)
    faq = create_faq(
        actor=actor,
        category_id=category.id,
        question="What is this?",
        answer="A test."
    )
    assert faq.status == "draft"
