"""
signal_handlers.py — Django post_save signal handlers for triggering async indexing.

These are connected in SupportAIConfig.ready(). They call Celery task .delay()
only -- never call embeddings functions inline.
"""
import logging

logger = logging.getLogger(__name__)


def on_article_save(sender, instance, created, **kwargs):
    """Trigger async re-indexing whenever an Article is saved."""
    try:
        from .tasks import index_article_task
        index_article_task.delay(str(instance.id))
    except Exception:
        logger.exception("Failed to enqueue article indexing for %s", instance.id)


def on_faq_save(sender, instance, created, **kwargs):
    """Trigger async re-indexing whenever a FAQ is saved."""
    try:
        from .tasks import index_faq_task
        index_faq_task.delay(str(instance.id))
    except Exception:
        logger.exception("Failed to enqueue FAQ indexing for %s", instance.id)


def on_hackathon_save(sender, instance, created, **kwargs):
    """Trigger async re-indexing whenever a Hackathon is saved."""
    try:
        from .tasks import index_hackathon_task
        index_hackathon_task.delay(str(instance.id))
    except Exception:
        logger.exception("Failed to enqueue hackathon indexing for %s", instance.id)
