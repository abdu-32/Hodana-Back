from django.apps import AppConfig


class SupportAIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.support_ai"
    verbose_name = "Support AI"

    def ready(self):
        """Connect indexing signals. Signal connections are one-directional:
        support_ai listens to other apps, no existing app imports support_ai."""
        try:
            from .httpx_compat import install_httpx_fallback
            install_httpx_fallback()
        except Exception:
            pass

        from django.db.models.signals import post_save

        from apps.knowledge_base.models import Article, FAQ
        from apps.hackathons.models import Hackathon
        from . import signal_handlers  # noqa: F401 - registers handlers as side effect
        from .signal_handlers import on_article_save, on_faq_save, on_hackathon_save
        
        post_save.connect(on_article_save, sender=Article)
        post_save.connect(on_faq_save, sender=FAQ)
        post_save.connect(on_hackathon_save, sender=Hackathon)
