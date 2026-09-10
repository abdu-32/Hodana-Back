"""
support_ai tasks — Celery tasks for async content indexing.

All tasks run in the 'ai_indexing' queue (CELERY_TASK_ROUTES).
Each task is retryable with exponential backoff (max 3 retries).
Business logic lives in embeddings.py; tasks are thin wrappers.
"""
import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(
    name="apps.support_ai.tasks.index_article",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    queue="ai_indexing",
)
def index_article_task(self, article_id: str):
    """Async indexing of a single Article. Idempotent."""
    from .embeddings import index_article
    import uuid
    count = index_article(uuid.UUID(article_id))
    logger.info("index_article_task: article %s -> %d chunks", article_id, count)
    return count


@shared_task(
    name="apps.support_ai.tasks.index_faq",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    queue="ai_indexing",
)
def index_faq_task(self, faq_id: str):
    """Async indexing of a single FAQ. Idempotent."""
    from .embeddings import index_faq
    import uuid
    count = index_faq(uuid.UUID(faq_id))
    logger.info("index_faq_task: faq %s -> %d chunks", faq_id, count)
    return count


@shared_task(
    name="apps.support_ai.tasks.index_hackathon",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    queue="ai_indexing",
)
def index_hackathon_task(self, hackathon_id: str):
    """Async indexing of a single Hackathon description+rules. Idempotent."""
    from .embeddings import index_hackathon
    import uuid
    count = index_hackathon(uuid.UUID(hackathon_id))
    logger.info("index_hackathon_task: hackathon %s -> %d chunks", hackathon_id, count)
    return count


@shared_task(
    name="apps.support_ai.tasks.bulk_reindex_articles",
    queue="ai_indexing",
)
def bulk_reindex_articles_task():
    """
    Full re-index of all published Articles.
    Paginates in batches (INDEXING_BATCH_SIZE) — never an unbounded queryset.
    Intended for off-peak hours (02:00 server time via CELERY_BEAT_SCHEDULE).
    """
    from apps.knowledge_base.models import Article
    from .embeddings import index_article
    import uuid
    
    batch_size = getattr(settings, 'INDEXING_BATCH_SIZE', 100)
    total = 0
    offset = 0
    
    while True:
        batch = list(
            Article.objects.filter(status="published")
            .values_list("id", flat=True)
            [offset:offset + batch_size]
        )
        if not batch:
            break
        for article_id in batch:
            index_article_task.delay(str(article_id))
            total += 1
        offset += batch_size
    
    logger.info("bulk_reindex_articles_task: enqueued %d articles", total)
    return total
