import re
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils.text import slugify
from django.utils import timezone
from apps.knowledge_base.models import Category, FAQ

class Command(BaseCommand):
    help = "Seed Knowledge Base categories and FAQs from docs/faq_knowledge_base.md"

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Starting Knowledge Base Seeding..."))
        
        filepath = os.path.join(settings.BASE_DIR, "docs", "faq_knowledge_base.md")
        if not os.path.exists(filepath):
            self.stderr.write(self.style.ERROR(f"File not found: {filepath}"))
            return
            
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse markdown by categories (## Section Name) and FAQs (### Q: Question)
        category_blocks = re.split(r'\n(?=## \d+\. |\n## PART )', content)
        
        categories_created = 0
        faqs_created = 0

        sort_order = 0
        for block in category_blocks:
            lines = block.strip().split("\n")
            if not lines:
                continue
                
            header_line = lines[0].strip()
            if not header_line.startswith("## "):
                continue

            # Extract category name
            cat_match = re.search(r'## (?:\d+\.\s*)?([^\n]+)', header_line)
            if not cat_match:
                continue
                
            cat_name = cat_match.group(1).strip()
            if cat_name.startswith("PART"):
                continue

            cat_slug = slugify(cat_name)
            if not cat_slug:
                cat_slug = f"category-{sort_order}"

            sort_order += 1
            category, _ = Category.objects.get_or_create(
                slug=cat_slug,
                defaults={
                    "name": cat_name,
                    "description": f"Knowledge base articles and FAQs regarding {cat_name}.",
                    "sort_order": sort_order
                }
            )
            categories_created += 1

            # Extract FAQs in this block (### Q: Question)
            faq_blocks = re.split(r'\n(?=### Q:)', block)
            faq_index = 0
            for faq_block in faq_blocks:
                if not faq_block.strip().startswith("### Q:"):
                    continue

                faq_lines = faq_block.strip().split("\n")
                question_line = faq_lines[0].replace("### Q:", "").strip()
                answer_text = "\n".join(faq_lines[1:]).strip()

                if not question_line or not answer_text:
                    continue

                faq_index += 1
                faq, created = FAQ.objects.update_or_create(
                    category=category,
                    question=question_line,
                    defaults={
                        "answer": answer_text,
                        "status": "published",
                        "published_at": timezone.now(),
                        "sort_order": faq_index
                    }
                )
                faqs_created += 1

                # Index chunk for apps/support_ai RAG if available
                try:
                    from apps.support_ai.embeddings import index_faq
                    index_faq(faq.id)
                except Exception:
                    # Ignore RAG indexing error if table/app not ready
                    pass

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully seeded Knowledge Base: {categories_created} categories and {faqs_created} FAQs processed."
            )
        )
