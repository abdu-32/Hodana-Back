"""
notifications -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here. This is the layer other apps' services.py call into to
satisfy FR-NOTIFY-001 (email + in-app notification per event) and
FR-NOTIFY-002 (SMS fallback for two of those events), instead of each
app hand-rolling its own `send_mail` call.

Design Spec Sec 3.2 describes this module as enqueuing jobs and "never
sending synchronously" via a Celery Background Worker. Celery itself is
explicitly disabled for now (see the commented-out block in
config/settings/base.py: "DISABLED for now. Re-enable when you write the
first task"), so -- same pragmatic choice already made by
apps.registrations.services._send_mail and apps.teams.services._send_mail
-- sending happens synchronously here too, behind the one function
(`_send_email`) that would become a Celery task's body later.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.accounts.models import RoleAssignment

from .models import Notification, NotificationDelivery

# FR-NOTIFY-001: "registration confirmations and deadline reminders cannot
# be opted out of ... required for the participant to exercise their
# rights under the hackathon's rules." Every other category is
# opt-out-able in principle, but apps.accounts.Account has no
# notification-preference storage anywhere in Doc 05 -- there is nothing
# to check an opt-out against yet. Recording that as a known gap (same
# pattern as apps.registrations.services._check_eligibility's age/
# geographic restrictions) rather than inventing a preference table not
# in the DB design: every category is currently sent to every recipient,
# which is the safe direction for a gap to fail in (a user who can't yet
# opt out still gets everything they're entitled to).
CRITICAL_CATEGORIES = {"registration_confirmation", "submission_deadline_reminder"}


def _get_hackathon_or_404(hackathon_id):
    from apps.hackathons.models import Hackathon

    try:
        return Hackathon.objects.get(id=hackathon_id)
    except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _is_organizer_of_hackathon(*, actor, hackathon):
    """Same pattern as apps.hackathons.services._is_organizer_of_org --
    the Organizer role is scoped to the hackathon's host organization,
    not the hackathon row itself (Design Spec Sec 4.3)."""
    return RoleAssignment.objects.filter(
        user=actor, role="organizer", scope_type="organization", scope_id=hackathon.host_org_id,
    ).exists()


def _send_email(*, delivery, subject):
    """The seam that would become a Celery task body once Celery is
    re-enabled (see module docstring). Failure is recorded on the
    delivery row rather than raised, so one bad address in a broadcast
    doesn't take the rest of the fan-out down with it -- the same
    isolation NFR-AVAIL-003 asks for between SMS and email."""
    recipient = delivery.user.contact_email or delivery.user.email
    try:
        send_mail(
            subject=subject,
            message=delivery.notification.message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[recipient],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see docstring
        delivery.status = "failed"
        delivery.failure_reason = str(exc)[:500]
    else:
        delivery.status = "sent"
        delivery.sent_at = timezone.now()
    delivery.save(update_fields=["status", "sent_at", "failure_reason"])


def _create_in_portal_deliveries(*, notification, recipients):
    """Creating the row IS the delivery for in_portal -- there's no
    external gateway step, so these go straight to `sent` and stay
    unread (`read_at=None`) until the recipient opens the notification
    center (FR-NOTIFY-001)."""
    now = timezone.now()
    deliveries = [
        NotificationDelivery(
            notification=notification, user=recipient, channel="in_portal",
            status="sent", sent_at=now,
        )
        for recipient in recipients
    ]
    return NotificationDelivery.objects.bulk_create(deliveries)


def _create_and_send_email_deliveries(*, notification, recipients, subject):
    deliveries = [
        NotificationDelivery(notification=notification, user=recipient, channel="email")
        for recipient in recipients
    ]
    deliveries = NotificationDelivery.objects.bulk_create(deliveries)
    for delivery in deliveries:
        _send_email(delivery=delivery, subject=subject)
    return deliveries


def _send_sms_fallback(*, hackathon, message, recipients):
    """FR-NOTIFY-002: SMS fallback for the deadline-reminder and
    judging-results-published events, to any recipient with a *verified
    Ethiopian phone number*. apps.accounts.Account has no phone number
    field anywhere in Document 05 Sec 4.1 or apps/accounts/models.py, so
    there is no data source to check "has a verified phone number"
    against for any recipient. Flagging as a known gap rather than
    guessing at a field that doesn't exist (same reasoning as
    apps.registrations.services._check_eligibility's unenforced age/
    geographic restrictions) -- no `sms` Notification/NotificationDelivery
    rows are created until that field lands, since a row can't honestly
    claim to have attempted a send with no phone number to send to.
    """
    return []


# ---- Fan-out core -----------------------------------------------------------

def notify_users(*, category, recipients, subject, message, hackathon=None,
                  channels=("email", "in_portal"), sms=False):
    """FR-NOTIFY-001 fan-out: creates one Notification row per requested
    channel and a NotificationDelivery row per recipient per channel
    (DB Design Sec 4.8), then actually sends/records each one.

    This is the one seam every FR-NOTIFY-001-triggering event in the
    codebase should call through, rather than hand-rolling `send_mail`
    the way apps.registrations/apps.teams currently do -- see those
    modules' `_send_mail` docstrings, which already anticipate this.

    `category` is one of the named events from SRS Sec 3.13 (e.g.
    "registration_confirmation", "hackathon_timeline_change") and is
    only used to look up CRITICAL_CATEGORIES; see that constant's
    docstring for why opt-out itself isn't enforced yet.

    Returns the list of created Notification rows (one per channel).
    """
    recipients = list(recipients)
    if not recipients:
        return []

    notifications = []
    with transaction.atomic():
        for channel in channels:
            notification = Notification.objects.create(
                hackathon=hackathon, message=message, channel=channel,
            )
            notifications.append(notification)
            if channel == "email":
                _create_and_send_email_deliveries(
                    notification=notification, recipients=recipients, subject=subject,
                )
            elif channel == "in_portal":
                _create_in_portal_deliveries(notification=notification, recipients=recipients)

    if sms:
        # FR-NOTIFY-002: "SMS delivery failure does not block or delay
        # the corresponding email notification" -- attempted after, and
        # independently of, the channels above for exactly that reason.
        _send_sms_fallback(hackathon=hackathon, message=message, recipients=recipients)

    return notifications


# ---- FR-NOTIFY-001 event wrappers -------------------------------------------
#
# One thin wrapper per named event in SRS Sec 3.13's FR-NOTIFY-001 list,
# each responsible only for resolving "who gets this" and the message
# copy -- the actual send/record work is notify_users' job.

def notify_registration_confirmed(registration):
    """FR-REG-001 / FR-NOTIFY-001: registration confirmation. Cannot be
    opted out of (CRITICAL_CATEGORIES)."""
    hackathon = registration.hackathon
    return notify_users(
        category="registration_confirmation",
        hackathon=hackathon,
        recipients=[registration.user],
        subject=f"You're registered for {hackathon.title}",
        message=f"You have successfully registered for {hackathon.title}.",
    )


def notify_hackathon_timeline_changed(hackathon):
    """FR-HACK-002 / FR-NOTIFY-001: "editing a date after the hackathon
    is published triggers a notification to all registered
    participants." Matches the exact call signature already anticipated
    by the TODO in apps.hackathons.services.update_hackathon."""
    from apps.registrations.models import Registration

    recipients = [
        r.user for r in
        Registration.objects.scoped_to(hackathon.id).filter(withdrawn_at__isnull=True).select_related("user")
    ]
    return notify_users(
        category="hackathon_timeline_change",
        hackathon=hackathon,
        recipients=recipients,
        subject=f"Update to {hackathon.title}'s schedule",
        message=f"The schedule for {hackathon.title} has changed. Please review the updated dates.",
    )


def notify_team_invitation(team_member):
    """FR-TEAM-002 / FR-NOTIFY-001: "the invited user receives a
    notification with accept/decline actions."

    `team_member.user` is null until the invitee has an account of their
    own (DB Design Sec 4.5 -- `invitee_email` is the only guaranteed
    identifier for a not-yet-registered invitee). There is nowhere to
    file a NotificationDelivery row without an Account to key it to
    (`user` is a required FK), so an invitee with no account yet only
    gets the plain email apps.teams.services already sends via its own
    `_send_mail` -- this in-app half of FR-NOTIFY-001 is a known gap for
    that specific case, not a silent skip of the whole event.
    """
    if team_member.user_id is None:
        return []

    team = team_member.team
    return notify_users(
        category="team_invitation",
        hackathon=team.hackathon,
        recipients=[team_member.user],
        subject=f"You've been invited to join {team.team_name}",
        message=f"You have been invited to join the team \"{team.team_name}\" for {team.hackathon.title}.",
    )


def notify_invitation_response(team_member):
    """FR-TEAM-002 / FR-NOTIFY-001: notifies the team leader once an
    invitee accepts or declines."""
    team = team_member.team
    if team.leader_user_id == team_member.user_id:
        return []  # the leader inviting/accepting themself isn't a "response" to notify about

    verb = "accepted" if team_member.join_status == "accepted" else "declined"
    return notify_users(
        category="invitation_response",
        hackathon=team.hackathon,
        recipients=[team.leader_user],
        subject=f"Invitation update for {team.team_name}",
        message=f"Your invitation to join \"{team.team_name}\" was {verb}.",
    )


def notify_submission_deadline_reminder(hackathon):
    """FR-NOTIFY-001/002: sent 24 hours before the submission deadline,
    to every active registrant, with an SMS attempt alongside email/
    in-portal. Cannot be opted out of (CRITICAL_CATEGORIES)."""
    from apps.registrations.models import Registration

    recipients = [
        r.user for r in
        Registration.objects.scoped_to(hackathon.id).filter(withdrawn_at__isnull=True).select_related("user")
    ]
    return notify_users(
        category="submission_deadline_reminder",
        hackathon=hackathon,
        recipients=recipients,
        subject=f"Submission deadline approaching for {hackathon.title}",
        message=f"Submissions for {hackathon.title} close at {hackathon.submission_closes_at:%Y-%m-%d %H:%M %Z}.",
        sms=True,
    )


def notify_eligibility_screening_result(submission):
    """FR-ELIG-001/002 / FR-NOTIFY-001: notifies every accepted member of
    the submitting team once eligibility_status is set."""
    from apps.teams.models import TeamMember

    recipients = [
        m.user for m in
        TeamMember.objects.filter(team=submission.team, join_status="accepted").select_related("user")
        if m.user_id is not None
    ]
    return notify_users(
        category="eligibility_screening_result",
        hackathon=submission.hackathon,
        recipients=recipients,
        subject=f"Eligibility result for {submission.title or 'your submission'}",
        message=(
            f"Your submission's eligibility status for {submission.hackathon.title} "
            f"is now: {submission.get_eligibility_status_display()}."
        ),
    )


def notify_judging_results_published(hackathon):
    """FR-JUDGE-004 / FR-NOTIFY-001/002: "judging results published", to
    every active registrant, with an SMS attempt alongside email/
    in-portal."""
    from apps.registrations.models import Registration

    recipients = [
        r.user for r in
        Registration.objects.scoped_to(hackathon.id).filter(withdrawn_at__isnull=True).select_related("user")
    ]
    return notify_users(
        category="judging_results_published",
        hackathon=hackathon,
        recipients=recipients,
        subject=f"Judging results are in for {hackathon.title}",
        message=f"Judging results for {hackathon.title} have been published. Check the showcase for details.",
        sms=True,
    )


# ---- Organizer-authored announcement (Doc 04 POST /notifications) ----------

def create_announcement(*, actor, hackathon_id, message, channel="email"):
    """POST /notifications -- Doc 04's `createNotification`. An Organizer
    of the hackathon's host organization broadcasts an announcement to
    every actively registered participant, over a single channel picked
    by the caller (Doc 04's NotificationCreateRequest.channel is one of
    email/in_portal -- sms is intentionally not offered here, since it's
    reserved by FR-NOTIFY-002 for the two named system events, not
    organizer-authored broadcasts).
    """
    from apps.registrations.models import Registration

    hackathon = _get_hackathon_or_404(hackathon_id)
    if not _is_organizer_of_hackathon(actor=actor, hackathon=hackathon):
        raise PermissionDenied("Only an Organizer of this hackathon can post an announcement.")

    recipients = [
        r.user for r in
        Registration.objects.scoped_to(hackathon.id).filter(withdrawn_at__isnull=True).select_related("user")
    ]
    notifications = notify_users(
        category="organizer_announcement",
        hackathon=hackathon,
        recipients=recipients,
        subject=f"Announcement: {hackathon.title}",
        message=message,
        channels=(channel,),
    )
    # Doc 04's Notification schema describes a single created resource,
    # not a list -- channels=(channel,) above guarantees exactly one.
    return notifications[0] if notifications else Notification.objects.create(
        hackathon=hackathon, message=message, channel=channel,
    )


# ---- Notification center (FR-NOTIFY-001's in-app half) ----------------------

def list_my_notifications(*, actor, unread_only=False):
    """A user's in-portal notification feed -- FR-NOTIFY-001: "retained
    for 90 days" and "marked unread until the user views the
    notification center." Strictly scoped to the requester, same
    "ownership query" pattern as apps.registrations.services.
    list_my_registrations.
    """
    deliveries = NotificationDelivery.objects.filter(
        user=actor, channel="in_portal",
    ).select_related("notification", "notification__hackathon")
    if unread_only:
        deliveries = deliveries.filter(read_at__isnull=True)
    return deliveries.order_by("-notification__created_at")


def _get_delivery_or_404(*, actor, delivery_id):
    try:
        return NotificationDelivery.objects.get(id=delivery_id, user=actor, channel="in_portal")
    except (NotificationDelivery.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def mark_notification_read(*, actor, delivery_id):
    """FR-NOTIFY-001: marks a single in-portal notification as read.
    Scoped to the requester -- another user's delivery row is a 404, not
    a 403, matching apps.registrations' "don't confirm existence to a
    non-owner" precedent."""
    delivery = _get_delivery_or_404(actor=actor, delivery_id=delivery_id)
    if delivery.read_at is None:
        delivery.read_at = timezone.now()
        delivery.save(update_fields=["read_at"])
    return delivery


def purge_expired_in_app_notifications(*, now=None):
    """FR-NOTIFY-001: in-app notifications are "retained for 90 days."
    No scheduler currently invokes this -- Celery Beat is disabled (see
    module docstring) and no apps/*/management/commands package exists
    yet anywhere in this project to run it another way. Exposed here as
    the concrete, testable unit so wiring it to a management command or
    a re-enabled Celery Beat schedule later is a one-line addition, not
    new logic."""
    from datetime import timedelta

    cutoff = (now or timezone.now()) - timedelta(days=90)
    return NotificationDelivery.objects.filter(
        channel="in_portal", notification__created_at__lt=cutoff,
    ).delete()
