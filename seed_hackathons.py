import os
import django
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.accounts.models import Account
from apps.organizations.models import Organization
from apps.hackathons.models import Hackathon

def seed():
    organizer = Account.objects.filter(email="mohammedumerbasha5@gmail.com").first()
    if not organizer:
        organizer = Account.objects.filter(role="organizer").first()
    if not organizer:
        organizer = Account.objects.first()

    org = Organization.objects.filter(name="Creavers PLC").first()
    if not org:
        org = Organization.objects.filter(verification_status="verified").first()
    if not org:
        org = Organization.objects.first()

    now = timezone.now()
    reg_opens = now - timedelta(days=7)
    reg_closes = now + timedelta(days=30)
    sub_opens = now - timedelta(days=2)
    sub_closes = now + timedelta(days=45)

    hackathons_data = [
        {
            "slug": "ethio-fin-innovate-2024",
            "title": "Ethio-Fin Innovate 2026",
            "description": "Revolutionizing digital payments for the Horn of Africa. Build the next generation of inclusive banking systems.",
            "field": "FinTech",
            "location_mode": "hybrid",
            "location_name": "Addis Ababa, Ethiopia",
            "venue": "National Bank Innovation Lab",
            "tags": ["FinTech", "Blockchain", "Machine Learning"],
            "total_prize_budget": Decimal("1200000.00"),
            "prize_info": "1st Prize: 600,000 ETB, 2nd Prize: 400,000 ETB, 3rd Prize: 200,000 ETB",
            "open_to": ["ALL"],
            "banner_url": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=1000&q=80",
        },
        {
            "slug": "greenseed-challenge-2024",
            "title": "GreenSeed Challenge",
            "description": "Optimizing coffee yield through IoT and satellite data mapping across the Oromia region.",
            "field": "Agriculture",
            "location_mode": "in_person",
            "location_name": "Jimma, Ethiopia",
            "venue": "Jimma Agricultural Center",
            "tags": ["Agriculture", "IoT", "Data Science"],
            "total_prize_budget": Decimal("500000.00"),
            "prize_info": "1st Prize: 300,000 ETB, 2nd Prize: 150,000 ETB, 3rd Prize: 50,000 ETB",
            "open_to": ["ALL"],
            "banner_url": "https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=800&q=80",
        },
        {
            "slug": "amharic-nlp-sprint-2024",
            "title": "Amharic NLP Sprint",
            "description": "Develop open-source Large Language Models specifically fine-tuned for Ethiopian local languages.",
            "field": "Artificial Intelligence",
            "location_mode": "online",
            "location_name": "Online / Virtual",
            "venue": "AAU AI Hub",
            "tags": ["AI", "Open Source", "Data Science"],
            "total_prize_budget": Decimal("750000.00"),
            "prize_info": "Top 3 teams receive computing grants and cash awards.",
            "open_to": ["ALL"],
            "banner_url": "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=800&q=80",
        },
        {
            "slug": "agristream-2024",
            "title": "AgriStream 2024",
            "description": "Revolutionizing supply chain efficiency for smallholder farmers using blockchain and IoT.",
            "field": "Agriculture",
            "location_mode": "hybrid",
            "location_name": "Addis Ababa, Ethiopia",
            "venue": "Addis Ababa Science Museum",
            "tags": ["AgriTech", "Blockchain", "IoT"],
            "total_prize_budget": Decimal("15000.00"),
            "prize_info": "$15,000 Prize Pool",
            "open_to": ["ALL"],
            "banner_url": "https://images.unsplash.com/photo-1625246333195-78d9c38ad449?auto=format&fit=crop&w=1200&q=80",
        },
        {
            "slug": "fintech-frontier",
            "title": "FinTech Frontier",
            "description": "Developing accessible micro-payment solutions for local commerce and cross-border trade.",
            "field": "FinTech",
            "location_mode": "online",
            "location_name": "Online / Virtual",
            "venue": "Virtual Hub",
            "tags": ["FinTech", "Micro-payments", "Trade"],
            "total_prize_budget": Decimal("25000.00"),
            "prize_info": "$25,000 Prize Pool",
            "open_to": ["ALL"],
            "banner_url": "https://images.unsplash.com/photo-1559526324-4b87b5e36e44?auto=format&fit=crop&w=1200&q=80",
        },
        {
            "slug": "ethio-health-ai",
            "title": "Ethio-Health AI",
            "description": "Leveraging machine learning to improve maternal health outcomes and diagnostic accuracy.",
            "field": "HealthTech",
            "location_mode": "in_person",
            "location_name": "Bahir Dar, Ethiopia",
            "venue": "Bahir Dar University Medical Center",
            "tags": ["HealthTech", "AI", "Machine Learning"],
            "total_prize_budget": Decimal("20000.00"),
            "prize_info": "$20,000 Prize Pool",
            "open_to": ["ALL"],
            "banner_url": "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?auto=format&fit=crop&w=1200&q=80",
        },
        {
            "slug": "egov-ethiopia-hack-2024",
            "title": "e-Gov Ethiopia Hack",
            "description": "Streamlining municipal service delivery through unified citizen-facing portals and identity systems.",
            "field": "Government",
            "location_mode": "in_person",
            "location_name": "Bahir Dar, Ethiopia",
            "venue": "Bahir Dar University ICT Center",
            "tags": ["Government", "Web Development", "Cybersecurity"],
            "total_prize_budget": Decimal("400000.00"),
            "prize_info": "400,000 ETB Prize Pool",
            "open_to": ["ALL"],
            "banner_url": "https://images.unsplash.com/photo-1517245386807-bb43f82c33c4?auto=format&fit=crop&w=800&q=80",
        },
    ]

    created_or_updated = []
    for h in hackathons_data:
        obj, created = Hackathon.objects.update_or_create(
            slug=h["slug"],
            defaults={
                "title": h["title"],
                "description": h["description"],
                "field": h["field"],
                "location_mode": h["location_mode"],
                "location_name": h["location_name"],
                "venue": h["venue"],
                "tags": h["tags"],
                "total_prize_budget": h["total_prize_budget"],
                "prize_info": h["prize_info"],
                "open_to": h["open_to"],
                "banner_url": h["banner_url"],
                "status": "published",
                "registration_opens_at": reg_opens,
                "registration_closes_at": reg_closes,
                "submission_opens_at": sub_opens,
                "submission_closes_at": sub_closes,
                "host_org": org,
                "created_by": organizer,
            }
        )
        created_or_updated.append(obj)
        print(f"Hackathon: {obj.title} (ID: {obj.id}, Slug: {obj.slug}, Status: {obj.status})")

    print(f"Successfully seeded {len(created_or_updated)} published hackathons.")

if __name__ == "__main__":
    seed()
