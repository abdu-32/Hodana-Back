import logging
from django.db import transaction
from django.conf import settings
from django.core.mail import send_mail
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from apps.core.models import AuditLogEntry
from apps.accounts.models import Account
from apps.notifications.services import notify_users
from .models import Ticket, TicketMessage, InternalNote, StatusHistory, Attachment, Assignment

logger = logging.getLogger(__name__)


def _get_ticket_or_404(ticket_id):
    try:
        return Ticket.objects.get(id=ticket_id)
    except (Ticket.DoesNotExist, ValueError, TypeError):
        raise NotFound()

def _get_message_or_404(message_id, ticket):
    try:
        return TicketMessage.objects.get(id=message_id, ticket=ticket)
    except (TicketMessage.DoesNotExist, ValueError, TypeError):
        raise NotFound()

def _is_staff(actor):
    return actor and (getattr(actor, 'is_staff', False) or getattr(actor, 'is_platform_admin', False))

def _assert_ticket_access(actor, ticket):
    if not _is_staff(actor) and ticket.submitter_id != actor.id:
        raise NotFound()

def _validate_scope(scope_type, scope_id):
    if bool(scope_type) != bool(scope_id):
        raise ValidationError("Both scope_type and scope_id must be provided together.")
    if scope_type and scope_type not in ["hackathon", "organization"]:
        raise ValidationError("Invalid scope_type.")

def _get_platform_admins():
    """Returns active platform admin accounts, falling back to superusers."""
    admins = list(Account.objects.filter(is_platform_admin=True, is_suspended=False))
    if not admins:
        admins = list(Account.objects.filter(is_staff=True, is_superuser=True, is_suspended=False))
    return admins


def _notify_admins_new_ticket(ticket, full_body, actor):
    admins = _get_platform_admins()
    admin_emails = [a.contact_email or a.email for a in admins if (a.contact_email or a.email)]

    configured_admin_email = getattr(settings, "PLATFORM_ADMIN_EMAIL", "").strip()
    if configured_admin_email and configured_admin_email not in admin_emails:
        admin_emails.append(configured_admin_email)

    submitter_name = getattr(actor, 'full_name', 'Anonymous User') if actor else 'Anonymous User'
    submitter_email = (getattr(actor, 'contact_email', None) or getattr(actor, 'email', 'No email provided')) if actor else 'No email provided'

    frontend_url = getattr(settings, "FRONTEND_URL", "https://patent-bind-conclude-seas.trycloudflare.com").rstrip("/")
    admin_ticket_url = f"{frontend_url}/admin/support"

    short_id = str(ticket.id)[:8]
    admin_subject = f"[Support Ticket #{short_id}] {ticket.subject} ({ticket.priority.upper()})"

    admin_message = (
        f"A new user support ticket has been submitted on the Ethiopia Innovation Hub platform.\n\n"
        f"Ticket ID: {ticket.id}\n"
        f"Subject: {ticket.subject}\n"
        f"Category: {ticket.category.replace('_', ' ').title()}\n"
        f"Priority: {ticket.priority.upper()}\n"
        f"Status: {ticket.status.upper()}\n"
        f"Scope: {f'{ticket.scope_type} ({ticket.scope_id})' if ticket.scope_type else 'Platform General'}\n"
        f"Submitted By: {submitter_name} ({submitter_email})\n\n"
        f"Problem Description:\n"
        f"--------------------------------------------------\n"
        f"{full_body}\n"
        f"--------------------------------------------------\n\n"
        f"To view and manage this ticket in the Platform Admin Portal, visit:\n"
        f"{admin_ticket_url}\n"
    )

    badge_color = "#b91c1c" if ticket.priority == "urgent" else ("#c2410c" if ticket.priority == "high" else "#0369a1")
    badge_bg = "#fee2e2" if ticket.priority == "urgent" else ("#ffedd5" if ticket.priority == "high" else "#e0f2fe")

    admin_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #1e293b; background-color: #f8fafc; margin: 0; padding: 0; }}
    .container {{ max-width: 600px; margin: 24px auto; background: #ffffff; border-radius: 16px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
    .header {{ background: linear-gradient(135deg, #0e2b25 0%, #0f6b5c 100%); color: #ffffff; padding: 28px 32px; }}
    .badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; background: {badge_bg}; color: {badge_color}; }}
    .content {{ padding: 32px; }}
    .field-group {{ margin-bottom: 20px; }}
    .field-label {{ font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }}
    .field-value {{ font-size: 15px; font-weight: 500; color: #0f172a; }}
    .message-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px; margin: 16px 0; font-size: 14px; white-space: pre-wrap; }}
    .btn {{ display: inline-block; background: #0f6b5c; color: #ffffff !important; text-decoration: none; padding: 12px 24px; border-radius: 10px; font-size: 14px; font-weight: 600; text-align: center; margin-top: 16px; }}
    .footer {{ background: #f1f5f9; padding: 20px 32px; font-size: 12px; color: #64748b; text-align: center; border-top: 1px solid #e2e8f0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: #fde047; margin-bottom: 6px;">Platform Admin Notification</div>
      <h1 style="margin: 0; font-size: 20px; font-weight: 700;">New Support Ticket Received</h1>
    </div>
    <div class="content">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid #f1f5f9; padding-bottom: 16px;">
        <div>
          <div class="field-label">Ticket Reference</div>
          <div style="font-family: monospace; font-size: 13px; color: #0f6b5c; font-weight: 600;">{ticket.id}</div>
        </div>
        <div>
          <span class="badge">{ticket.priority.upper()} PRIORITY</span>
        </div>
      </div>

      <div class="field-group">
        <div class="field-label">Subject</div>
        <div class="field-value" style="font-size: 17px; font-weight: 700;">{ticket.subject}</div>
      </div>

      <div class="field-group" style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
        <div>
          <div class="field-label">Submitter</div>
          <div class="field-value">{submitter_name}</div>
          <div style="font-size: 13px; color: #64748b;">{submitter_email}</div>
        </div>
        <div>
          <div class="field-label">Category</div>
          <div class="field-value">{ticket.category.replace('_', ' ').title()}</div>
        </div>
      </div>

      <div class="field-group">
        <div class="field-label">Issue Description</div>
        <div class="message-box">{full_body}</div>
      </div>

      <div style="text-align: center; margin-top: 24px;">
        <a href="{admin_ticket_url}" class="btn">View & Reply in Admin Portal &rarr;</a>
      </div>
    </div>
    <div class="footer">
      Ethiopia Innovation Hub &bull; Support Ticket System &bull; Confidential
    </div>
  </div>
</body>
</html>"""

    if admin_emails:
        try:
            send_mail(
                subject=admin_subject,
                message=admin_message,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=admin_emails,
                fail_silently=False,
                html_message=admin_html,
            )
            logger.info("Dispatched support ticket email to platform admins: %s", admin_emails)
        except Exception as exc:
            logger.error("Failed to dispatch support ticket email to platform admins: %s", exc)

    if admins:
        notify_users(
            category="support_ticket_created",
            recipients=admins,
            subject=f"New Ticket: {ticket.subject}",
            message=f"New support ticket submitted by {submitter_name}: '{ticket.subject}' [{ticket.priority.upper()}].",
            channels=("in_portal",),
        )


def _notify_submitter_ticket_created(ticket, actor):
    if not actor:
        return
    short_id = str(ticket.id)[:8]
    sub_subject = f"Your Support Ticket [#{short_id}] has been received"
    sub_message = (
        f"Hello {getattr(actor, 'full_name', '') or 'there'},\n\n"
        f"Thank you for contacting the Ethiopia Innovation Hub support team. "
        f"We have received your support ticket regarding '{ticket.subject}'.\n\n"
        f"Ticket Reference: {ticket.id}\n"
        f"Category: {ticket.category.replace('_', ' ').title()}\n"
        f"Priority: {ticket.priority.upper()}\n"
        f"Status: Open\n\n"
        f"Our support team has been notified and will review your request shortly. "
        f"You can view and reply to this ticket anytime in the Knowledge Base -> My Tickets section.\n\n"
        f"Best regards,\n"
        f"Ethiopia Innovation Hub Support Team"
    )
    notify_users(
        category="support_ticket_created",
        recipients=[actor],
        subject=sub_subject,
        message=sub_message,
        channels=("email", "in_portal"),
    )


def create_ticket(*, actor, subject, body, category, priority="normal", scope_type=None, scope_id=None, other_details=None) -> Ticket:
    """
    FR-SUPPORT-001. Creates a ticket and its first message in one atomic block.
    Validates scope_type/scope_id pair. Writes AuditLogEntry.
    Dispatches notifications to both Platform Admin (email + in_portal) and submitter.
    """
    _validate_scope(scope_type, scope_id)
    
    valid_categories = ["technical", "billing", "general", "hackathon_specific"]
    clean_category = category.lower().replace(" ", "_") if category else "general"
    if clean_category not in valid_categories:
        clean_category = "general"

    full_body = body
    if other_details and other_details.strip():
        full_body = f"{body}\n\n--- Additional Support Details ---\n{other_details.strip()}"

    with transaction.atomic():
        ticket = Ticket.objects.create(
            submitter=actor,
            subject=subject,
            category=clean_category,
            priority=priority if priority in ["low", "normal", "high", "urgent"] else "normal",
            scope_type=scope_type,
            scope_id=scope_id
        )
        TicketMessage.objects.create(
            ticket=ticket,
            author=actor,
            body=full_body,
            is_staff_reply=False
        )
        AuditLogEntry.objects.create(
            actor_id=actor.id if actor else None, action="ticket_created", target_type="ticket", target_id=str(ticket.id), metadata={}
        )

    # Dispatch notifications outside transaction
    try:
        _notify_admins_new_ticket(ticket, full_body, actor)
    except Exception as exc:
        logger.error("Error notifying admins of new ticket: %s", exc)

    try:
        _notify_submitter_ticket_created(ticket, actor)
    except Exception as exc:
        logger.error("Error notifying submitter of new ticket: %s", exc)

    return ticket


def list_my_tickets(*, actor, status=None, limit=20, offset=0) -> tuple:
    """FR-SUPPORT-002. Returns (results, total) for the actor's own tickets."""
    qs = Ticket.objects.filter(submitter=actor)
    if status:
        qs = qs.filter(status=status)
    total = qs.count()
    qs = qs.order_by("-created_at")[offset:offset+limit]
    return list(qs), total

def get_ticket(*, actor, ticket_id) -> Ticket:
    """FR-SUPPORT-002. Returns ticket if actor is owner OR staff. 404 otherwise."""
    ticket = _get_ticket_or_404(ticket_id)
    _assert_ticket_access(actor, ticket)
    return ticket

def list_staff_tickets(*, actor, status=None, priority=None, assignee_id=None, limit=20, offset=0) -> tuple:
    """FR-SUPPORT-002. Staff-only listing of all tickets. PermissionDenied if not staff."""
    if not _is_staff(actor):
        raise PermissionDenied()
    qs = Ticket.objects.all().select_related("submitter")
    if status:
        qs = qs.filter(status=status)
    if priority:
        qs = qs.filter(priority=priority)
    if assignee_id:
        qs = qs.filter(assignments__assignee_id=assignee_id, assignments__unassigned_at__isnull=True)
    total = qs.count()
    qs = qs.order_by("-created_at").distinct()[offset:offset+limit]
    return list(qs), total

def _format_ticket_conversation_history(ticket):
    """
    Returns (plain_text_history, html_history) for all messages in the ticket.
    """
    messages = list(ticket.messages.select_related("author").order_by("created_at"))
    text_lines = []
    html_items = []

    for idx, msg in enumerate(messages, 1):
        sender_role = "Platform Admin" if msg.is_staff_reply else "User"
        sender_name = msg.author.full_name if (msg.author and msg.author.full_name) else ("Specialist" if msg.is_staff_reply else "User")
        time_str = msg.created_at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(msg, "created_at") else ""

        text_lines.append(f"#{idx} [{time_str}] {sender_name} ({sender_role}):\n{msg.body}\n")

        is_admin = msg.is_staff_reply
        bg_color = "#f0fdf4" if is_admin else "#f8fafc"
        border_color = "#bbf7d0" if is_admin else "#e2e8f0"
        badge_bg = "#dcfce7" if is_admin else "#e0f2fe"
        badge_color = "#166534" if is_admin else "#0369a1"

        html_items.append(f"""
        <div style="margin-bottom: 12px; padding: 14px 16px; border-radius: 12px; background: {bg_color}; border: 1px solid {border_color};">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="font-weight: 700; font-size: 13px; color: #0f172a;">
              {sender_name} <span style="font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 9999px; background: {badge_bg}; color: {badge_color}; margin-left: 6px; text-transform: uppercase;">{sender_role}</span>
            </div>
            <div style="font-size: 11px; color: #64748b;">{time_str}</div>
          </div>
          <div style="font-size: 13px; color: #334155; white-space: pre-wrap; line-height: 1.5;">{msg.body}</div>
        </div>
        """)

    plain_text = "\n--------------------------------------------------\n".join(text_lines)
    html_text = "".join(html_items)
    return plain_text, html_text


def add_message(*, actor, ticket_id, body) -> TicketMessage:
    """
    FR-SUPPORT-003. Adds a message. is_staff_reply set based on actor.is_staff.
    Updates ticket status: if staff replies -> pending_user; if user replies -> pending_staff.
    Preserves complete conversation history between user and Platform Admin.
    Notifies the other party after atomic block with full thread history.
    """
    ticket = get_ticket(actor=actor, ticket_id=ticket_id)
    is_staff = _is_staff(actor)
    old_status = ticket.status

    with transaction.atomic():
        message = TicketMessage.objects.create(
            ticket=ticket, author=actor, body=body, is_staff_reply=is_staff
        )
        AuditLogEntry.objects.create(
            actor_id=actor.id if actor else None,
            action="ticket_message_added",
            target_type="ticket_message",
            target_id=str(message.id),
            metadata={"ticket_id": str(ticket.id), "is_staff_reply": is_staff}
        )
        if is_staff:
            new_status = "pending_user"
        else:
            new_status = "pending_staff"

        if old_status != new_status:
            ticket.status = new_status
            ticket.save(update_fields=["status", "updated_at"])
            StatusHistory.objects.create(
                ticket=ticket, from_status=old_status, to_status=new_status, actor=actor
            )
        else:
            ticket.save(update_fields=["updated_at"])

    author_name = getattr(actor, 'full_name', 'User') if actor else 'User'
    short_id = str(ticket.id)[:8]
    frontend_url = getattr(settings, "FRONTEND_URL", "https://patent-bind-conclude-seas.trycloudflare.com").rstrip("/")
    admin_ticket_url = f"{frontend_url}/admin/support"

    # Format the complete conversation history thread
    thread_plain, thread_html = _format_ticket_conversation_history(ticket)

    if not is_staff:
        # User replied -> notify Platform Admin
        admins = _get_platform_admins()
        admin_emails = [a.contact_email or a.email for a in admins if (a.contact_email or a.email)]
        configured_admin_email = getattr(settings, "PLATFORM_ADMIN_EMAIL", "").strip()
        if configured_admin_email and configured_admin_email not in admin_emails:
            admin_emails.append(configured_admin_email)

        msg_subject = f"[Ticket Reply #{short_id}] New message from {author_name}"
        msg_body = (
            f"User {author_name} posted a new reply to Ticket #{ticket.id} ('{ticket.subject}'):\n\n"
            f"Latest Message:\n"
            f"\"{body}\"\n\n"
            f"==================================================\n"
            f"COMPLETE CONVERSATION HISTORY\n"
            f"==================================================\n"
            f"{thread_plain}\n\n"
            f"View full conversation & reply in Admin Portal:\n"
            f"{admin_ticket_url}\n"
        )

        admin_reply_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1e293b; background: #f8fafc; margin: 0; padding: 0; }}
  .card {{ max-width: 620px; margin: 24px auto; background: #ffffff; border-radius: 16px; overflow: hidden; border: 1px solid #e2e8f0; }}
  .header {{ background: linear-gradient(135deg, #0e2b25 0%, #0f6b5c 100%); color: #ffffff; padding: 24px 28px; }}
  .content {{ padding: 28px; }}
  .latest-msg {{ background: #f0fdf4; border: 1px solid #86efac; border-radius: 12px; padding: 16px; margin: 16px 0; font-size: 14px; font-weight: 500; color: #14532d; }}
  .thread-box {{ margin-top: 24px; border-top: 1px solid #e2e8f0; padding-top: 20px; }}
  .btn {{ display: inline-block; background: #0f6b5c; color: #ffffff !important; text-decoration: none; padding: 10px 20px; border-radius: 10px; font-size: 13px; font-weight: 600; margin-top: 16px; }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #fde047;">Platform Admin Notice</div>
    <h2 style="margin: 4px 0 0 0; font-size: 18px;">New Reply on Ticket #{short_id}</h2>
    <div style="font-size: 13px; opacity: 0.9; margin-top: 4px;">{ticket.subject}</div>
  </div>
  <div class="content">
    <div style="font-size: 12px; font-weight: 700; color: #64748b; text-transform: uppercase;">Latest Reply from {author_name}:</div>
    <div class="latest-msg">{body}</div>

    <div class="thread-box">
      <div style="font-size: 12px; font-weight: 700; color: #64748b; text-transform: uppercase; margin-bottom: 12px;">Complete Conversation History:</div>
      {thread_html}
    </div>

    <div style="text-align: center; margin-top: 20px;">
      <a href="{admin_ticket_url}" class="btn">Open Ticket in Admin Portal &rarr;</a>
    </div>
  </div>
</div>
</body>
</html>"""

        if admin_emails:
            try:
                send_mail(
                    subject=msg_subject,
                    message=msg_body,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    recipient_list=admin_emails,
                    fail_silently=False,
                    html_message=admin_reply_html,
                )
            except Exception as e:
                logger.error("Failed to notify admins of ticket reply: %s", e)
        if admins:
            notify_users(
                category="support_ticket_reply",
                recipients=admins,
                subject=msg_subject,
                message=f"{author_name} replied to ticket: '{ticket.subject}'.",
                channels=("in_portal",),
            )
    else:
        # Staff replied -> notify ticket submitter
        if ticket.submitter:
            user_subject = f"Update on your Support Ticket [#{short_id}]"
            user_body = (
                f"Hello {getattr(ticket.submitter, 'full_name', 'there')},\n\n"
                f"A support specialist has replied to your ticket '{ticket.subject}':\n\n"
                f"Latest Reply:\n"
                f"\"{body}\"\n\n"
                f"==================================================\n"
                f"COMPLETE CONVERSATION HISTORY\n"
                f"==================================================\n"
                f"{thread_plain}\n\n"
                f"You can view the full thread and reply anytime under Knowledge Base -> My Tickets."
            )
            user_reply_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1e293b; background: #f8fafc; margin: 0; padding: 0; }}
  .card {{ max-width: 620px; margin: 24px auto; background: #ffffff; border-radius: 16px; overflow: hidden; border: 1px solid #e2e8f0; }}
  .header {{ background: linear-gradient(135deg, #0e2b25 0%, #0f6b5c 100%); color: #ffffff; padding: 24px 28px; }}
  .content {{ padding: 28px; }}
  .latest-msg {{ background: #f0fdf4; border: 1px solid #86efac; border-radius: 12px; padding: 16px; margin: 16px 0; font-size: 14px; font-weight: 500; color: #14532d; }}
  .thread-box {{ margin-top: 24px; border-top: 1px solid #e2e8f0; padding-top: 20px; }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #fde047;">Support Specialist Response</div>
    <h2 style="margin: 4px 0 0 0; font-size: 18px;">Ticket #{short_id}: {ticket.subject}</h2>
  </div>
  <div class="content">
    <div style="font-size: 12px; font-weight: 700; color: #64748b; text-transform: uppercase;">Latest Reply:</div>
    <div class="latest-msg">{body}</div>

    <div class="thread-box">
      <div style="font-size: 12px; font-weight: 700; color: #64748b; text-transform: uppercase; margin-bottom: 12px;">Complete Conversation History:</div>
      {thread_html}
    </div>
  </div>
</div>
</body>
</html>"""
            if getattr(ticket.submitter, "email", None):
                try:
                    send_mail(
                        subject=user_subject,
                        message=user_body,
                        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                        recipient_list=[ticket.submitter.email],
                        fail_silently=False,
                        html_message=user_reply_html,
                    )
                except Exception as e:
                    logger.error("Failed to email user ticket reply: %s", e)
            notify_users(
                category="support_ticket_reply",
                recipients=[ticket.submitter],
                subject=user_subject,
                message=user_body,
                channels=("in_portal",),
            )

    return message


def list_ticket_messages(*, actor, ticket_id):
    """
    FR-SUPPORT-003. Returns complete TicketMessage queryset ordered chronologically.
    SECURITY: InternalNote rows are NEVER included here regardless of actor.
    Internal notes are a separate model returned only via list_internal_notes().
    """
    ticket = get_ticket(actor=actor, ticket_id=ticket_id)
    return TicketMessage.objects.filter(ticket=ticket).select_related("author").order_by("created_at")


def add_internal_note(*, actor, ticket_id, body) -> InternalNote:
    """FR-SUPPORT-004. PermissionDenied if not staff."""
    if not _is_staff(actor):
        raise PermissionDenied()
    ticket = _get_ticket_or_404(ticket_id)
    return InternalNote.objects.create(
        ticket=ticket, author=actor, body=body
    )

def list_internal_notes(*, actor, ticket_id):
    """FR-SUPPORT-004. PermissionDenied if not staff."""
    if not _is_staff(actor):
        raise PermissionDenied()
    ticket = _get_ticket_or_404(ticket_id)
    return InternalNote.objects.filter(ticket=ticket).order_by("created_at")

def update_ticket_status(*, actor, ticket_id, new_status) -> Ticket:
    """
    FR-SUPPORT-005. Staff only. Validates transition. Writes StatusHistory and AuditLogEntry.
    Notifies submitter after atomic block (not inside).
    """
    if not _is_staff(actor):
        raise PermissionDenied()
    ticket = _get_ticket_or_404(ticket_id)
    valid_transitions = {
        "open": ["pending_staff", "pending_user", "resolved", "closed"],
        "pending_staff": ["open", "pending_user", "resolved", "closed"],
        "pending_user": ["open", "pending_staff", "resolved", "closed"],
        "resolved": ["closed", "open"],
        "closed": ["open"],
    }
    if new_status not in valid_transitions.get(ticket.status, []):
        raise ValidationError("Invalid status transition.")
    
    old_status = ticket.status
    with transaction.atomic():
        ticket.status = new_status
        ticket.save(update_fields=["status", "updated_at"])
        StatusHistory.objects.create(
            ticket=ticket, from_status=old_status, to_status=new_status, actor=actor
        )
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="ticket_status_updated", target_type="ticket", target_id=str(ticket.id), metadata={"from": old_status, "to": new_status}
        )
    if ticket.submitter:
        notify_users(
            category="support_ticket_updated",
            recipients=[ticket.submitter],
            subject=_("Your support ticket has been updated"),
            message=_("Your support ticket '{subject}' status has been updated to {status}.").format(subject=ticket.subject, status=new_status),
            channels=("in_portal",),
        )
    return ticket

def add_attachment(*, actor, ticket_id, message_id=None, file_url=None, filename=None, file_size=None, content_type=None) -> Attachment:
    """FR-SUPPORT-006. Actor must be ticket owner or staff."""
    ticket = get_ticket(actor=actor, ticket_id=ticket_id)
    message = None
    if message_id:
        message = _get_message_or_404(message_id, ticket)
    return Attachment.objects.create(
        ticket=ticket, message=message, uploader=actor,
        file_url=file_url, filename=filename, file_size=file_size, content_type=content_type
    )

def assign_ticket(*, actor, ticket_id, assignee_id) -> Assignment:
    """
    FR-SUPPORT-007. Staff only. Soft-closes previous active assignment.
    Writes AuditLogEntry.
    """
    if not _is_staff(actor):
        raise PermissionDenied()
    ticket = _get_ticket_or_404(ticket_id)
    with transaction.atomic():
        Assignment.objects.filter(ticket=ticket, unassigned_at__isnull=True).update(unassigned_at=timezone.now())
        assignment = Assignment.objects.create(ticket=ticket, assignee_id=assignee_id, assigned_by=actor)
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="ticket_assigned", target_type="ticket", target_id=str(ticket.id), metadata={"assignee_id": str(assignee_id)}
        )
    return assignment
