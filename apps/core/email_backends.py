"""
HTTPS-based email backend for transactional emails.
Cloud platforms (like Railway, AWS, DigitalOcean) frequently block outbound
SMTP ports (25, 465, 587) on hobby/starter plans.
This backend communicates over standard HTTPS (Port 443), which is never blocked.
"""

import logging
import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class ResendEmailBackend(BaseEmailBackend):
    """
    Sends emails via the Resend HTTP API (port 443) using requests.
    Configure via:
        EMAIL_BACKEND = "apps.core.email_backends.ResendEmailBackend"
        RESEND_API_KEY = "re_..." (or EMAIL_HOST_PASSWORD = "re_...")
    """

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = getattr(settings, "RESEND_API_KEY", "") or getattr(settings, "EMAIL_HOST_PASSWORD", "")
        if not api_key:
            logger.error("ResendEmailBackend: No API key configured (set RESEND_API_KEY or EMAIL_HOST_PASSWORD).")
            print("[RESEND ERROR] No API key configured. Set RESEND_API_KEY=re_...", flush=True)
            return 0

        sent_count = 0
        for message in email_messages:
            from_email = message.from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "onboarding@resend.dev")
            # Resend requires either a verified custom domain or "onboarding@resend.dev".
            # If the sender address uses an unverified public mailbox (e.g. @gmail.com) or local dummy domain,
            # Resend will reject the request with HTTP 403. Fall back to onboarding@resend.dev safely.
            lower_from = from_email.lower()
            if any(dom in lower_from for dom in ["@gmail.com", "@yahoo.com", "@outlook.com", "@hotmail.com", "innovationhub.local", "example.com"]):
                from_email = "Hodana <onboarding@resend.dev>"

            payload = {
                "from": from_email,
                "to": list(message.to),
                "subject": message.subject,
                "text": message.body,
            }

            # Support HTML email content if present
            if hasattr(message, "alternatives"):
                for content, mimetype in message.alternatives:
                    if mimetype == "text/html":
                        payload["html"] = content
                        break

            try:
                response = requests.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {api_key.strip()}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=getattr(settings, "EMAIL_TIMEOUT", 10),
                )

                if response.status_code in (200, 201):
                    sent_count += 1
                    logger.info("Resend successfully sent email to %s", message.to)
                    print(f"[RESEND SUCCESS] Email delivered via HTTPS to {message.to}", flush=True)
                else:
                    error_detail = response.text
                    logger.error("Resend API rejected email to %s: HTTP %s - %s", message.to, response.status_code, error_detail)
                    print(f"[RESEND ERROR] Status {response.status_code}: {error_detail}", flush=True)
            except Exception as exc:
                logger.exception("Resend connection error: %s", exc)
                print(f"[RESEND ERROR] Connection failure: {exc}", flush=True)
                if not self.fail_silently:
                    raise

        return sent_count


class BrevoEmailBackend(BaseEmailBackend):
    """
    Sends emails via the Brevo (formerly Sendinblue) HTTP API (port 443).
    Allows sending to ANY recipient email address using a free account.
    Configure via:
        EMAIL_BACKEND = "apps.core.email_backends.BrevoEmailBackend"
        BREVO_API_KEY = "xkeysib-..."
        DEFAULT_FROM_EMAIL = "natnael.yilma27@gmail.com"
    """

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = getattr(settings, "BREVO_API_KEY", "") or getattr(settings, "EMAIL_HOST_PASSWORD", "")
        if not api_key:
            logger.error("BrevoEmailBackend: No API key configured (set BREVO_API_KEY).")
            print("[BREVO ERROR] No API key configured. Set BREVO_API_KEY=xkeysib-...", flush=True)
            return 0

        sender_raw = getattr(settings, "DEFAULT_FROM_EMAIL", "natnael.yilma27@gmail.com")
        if "<" in sender_raw and ">" in sender_raw:
            sender_name = sender_raw.split("<")[0].strip() or "Hodana"
            sender_email = sender_raw.split("<")[1].rstrip(">").strip()
        else:
            sender_name = "Hodana"
            sender_email = sender_raw.strip()

        if "innovationhub.local" in sender_email or "example.com" in sender_email:
            sender_email = getattr(settings, "EMAIL_HOST_USER", "natnael.yilma27@gmail.com") or "natnael.yilma27@gmail.com"

        sent_count = 0
        for message in email_messages:
            payload = {
                "sender": {"name": sender_name, "email": sender_email},
                "to": [{"email": recipient} for recipient in message.to],
                "subject": message.subject,
                "textContent": message.body,
            }

            if hasattr(message, "alternatives"):
                for content, mimetype in message.alternatives:
                    if mimetype == "text/html":
                        payload["htmlContent"] = content
                        break

            try:
                response = requests.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={
                        "api-key": api_key.strip(),
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                    timeout=getattr(settings, "EMAIL_TIMEOUT", 10),
                )

                if response.status_code in (200, 201):
                    sent_count += 1
                    logger.info("Brevo successfully sent email to %s", message.to)
                    print(f"[BREVO SUCCESS] Email delivered via HTTPS to {message.to}", flush=True)
                else:
                    error_detail = response.text
                    logger.error("Brevo API rejected email to %s: HTTP %s - %s", message.to, response.status_code, error_detail)
                    print(f"[BREVO ERROR] Status {response.status_code}: {error_detail}", flush=True)
            except Exception as exc:
                logger.exception("Brevo connection error: %s", exc)
                print(f"[BREVO ERROR] Connection failure: {exc}", flush=True)
                if not self.fail_silently:
                    raise

        return sent_count
