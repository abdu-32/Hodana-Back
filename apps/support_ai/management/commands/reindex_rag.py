import logging
from django.core.management.base import BaseCommand
from apps.knowledge_base.models import Article, FAQ
from apps.hackathons.models import Hackathon
from apps.support_ai.embeddings import index_article, index_faq, index_hackathon

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Bulk re-index all published Articles, FAQs, and Hackathons into DocumentChunk embeddings for RAG."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all existing DocumentChunk records before reindexing",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Starting RAG Re-indexing..."))

        if options["clear"]:
            from apps.support_ai.models import DocumentChunk
            deleted_count, _ = DocumentChunk.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Cleared {deleted_count} existing DocumentChunk records."))

        # 1. Index Articles
        published_articles = Article.objects.filter(status="published")
        article_chunks = 0
        for article in published_articles:
            try:
                count = index_article(article.id)
                article_chunks += count
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to index article {article.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Indexed {published_articles.count()} articles -> {article_chunks} chunks."))

        # 2. Index FAQs
        published_faqs = FAQ.objects.filter(status="published")
        faq_chunks = 0
        for faq in published_faqs:
            try:
                count = index_faq(faq.id)
                faq_chunks += count
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to index FAQ {faq.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Indexed {published_faqs.count()} FAQs -> {faq_chunks} chunks."))

        # 3. Index Hackathons
        active_hackathons = Hackathon.objects.filter(status__in=["published", "draft"])
        hackathon_chunks = 0
        for hackathon in active_hackathons:
            try:
                count = index_hackathon(hackathon.id)
                hackathon_chunks += count
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Failed to index hackathon {hackathon.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Indexed {active_hackathons.count()} hackathons -> {hackathon_chunks} chunks."))

        total_chunks = article_chunks + faq_chunks + hackathon_chunks
        self.stdout.write(
            self.style.SUCCESS(
                f"\nSuccessfully completed RAG re-indexing: {total_chunks} total DocumentChunk records created."
            )
        )
