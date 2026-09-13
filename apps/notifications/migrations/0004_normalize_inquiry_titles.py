import re
from django.db import migrations


def normalize_inquiry_titles(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    try:
        Ticket = apps.get_model("support", "Ticket")
    except LookupError:
        Ticket = None

    INQUIRY_TITLES = {
        "technical": "Technical & Platform Bug",
        "billing": "Payments, Prizes, Billing",
        "general": "General Platform Questions",
        "hackathon_specific": "Hackathon Rules & Judging",
    }

    CANONICAL_MAP = {
        "payments, prizes & billing": "Payments, Prizes, Billing",
        "payments, prizes, billing": "Payments, Prizes, Billing",
        "payments & prizes": "Payments, Prizes, Billing",
        "general platform question": "General Platform Questions",
        "general platform questions": "General Platform Questions",
        "technical & platform bug": "Technical & Platform Bug",
        "hackathon rules & judging": "Hackathon Rules & Judging",
    }

    for notif in Notification.objects.all():
        stored_title = (notif.title or "").strip()
        msg = notif.message or ""
        lower_msg = msg.lower()
        cat = (notif.category or "").lower()

        # If already matching a canonical title, normalize if needed
        if stored_title.lower() in CANONICAL_MAP:
            target_title = CANONICAL_MAP[stored_title.lower()]
            if notif.title != target_title:
                notif.title = target_title
                notif.save(update_fields=["title"])
            continue

        is_support = (
            cat.startswith("support")
            or "support ticket" in lower_msg
            or "ticket reference" in lower_msg
            or "support specialist" in lower_msg
            or "replied to ticket" in lower_msg
            or "category: technical" in lower_msg
            or "category: billing" in lower_msg
            or "category: general" in lower_msg
            or "category: hackathon" in lower_msg
        )

        if not is_support:
            continue

        resolved_title = None
        resolved_category = None

        if "technical" in cat or "category: technical" in lower_msg:
            resolved_title = INQUIRY_TITLES["technical"]
            resolved_category = "support_technical"
        elif "billing" in cat or "category: billing" in lower_msg or "category: payments" in lower_msg:
            resolved_title = INQUIRY_TITLES["billing"]
            resolved_category = "support_billing"
        elif "hackathon" in cat or "category: hackathon" in lower_msg:
            resolved_title = INQUIRY_TITLES["hackathon_specific"]
            resolved_category = "support_hackathon_specific"
        elif "general" in cat or "category: general" in lower_msg:
            resolved_title = INQUIRY_TITLES["general"]
            resolved_category = "support_general"
        elif Ticket:
            match = re.search(r"['\"]([^'\"]+)['\"]", msg)
            if match:
                t_subj = match.group(1).strip()
                t = Ticket.objects.filter(subject__iexact=t_subj).first()
                if t and t.category in INQUIRY_TITLES:
                    resolved_title = INQUIRY_TITLES[t.category]
                    resolved_category = f"support_{t.category}"

        if not resolved_title:
            if any(w in lower_msg for w in ["payment", "prize", "payout", "invoice", "billing", "refund", "reward"]):
                resolved_title = INQUIRY_TITLES["billing"]
                resolved_category = "support_billing"
            elif any(w in lower_msg for w in ["rules", "judging criteria", "judging", "submission requirement"]):
                resolved_title = INQUIRY_TITLES["hackathon_specific"]
                resolved_category = "support_hackathon_specific"
            elif any(w in lower_msg for w in ["bug", "error", "broken", "technical", "verification", "login"]):
                resolved_title = INQUIRY_TITLES["technical"]
                resolved_category = "support_technical"
            else:
                resolved_title = INQUIRY_TITLES["general"]
                resolved_category = "support_general"

        notif.title = resolved_title
        if not notif.category or notif.category in ["support_ticket_updated", "support_ticket_created", "support_ticket_reply"]:
            notif.category = resolved_category
        notif.save(update_fields=["title", "category"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0003_backfill_support_notification_inquiry_titles"),
    ]

    operations = [
        migrations.RunPython(normalize_inquiry_titles, noop),
    ]
