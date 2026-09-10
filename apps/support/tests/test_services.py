import pytest
from rest_framework.exceptions import NotFound, PermissionDenied
from apps.support.services import (
    create_ticket, get_ticket, add_message, add_internal_note, 
    update_ticket_status, assign_ticket
)
from apps.core.models import AuditLogEntry

def test_create_ticket(regular_user):
    ticket = create_ticket(
        actor=regular_user, subject="Help", body="Need help", category="general"
    )
    assert ticket.subject == "Help"
    assert ticket.messages.count() == 1
    assert AuditLogEntry.objects.filter(action="ticket_created").exists()

def test_get_ticket(regular_user, staff_user, ticket):
    assert get_ticket(actor=regular_user, ticket_id=ticket.id) == ticket
    assert get_ticket(actor=staff_user, ticket_id=ticket.id) == ticket
    
    other_user = regular_user # in reality need a different user, wait I'll use staff_user but with is_staff=False
    staff_user.is_staff = False
    staff_user.save()
    with pytest.raises(NotFound):
        get_ticket(actor=staff_user, ticket_id=ticket.id)

def test_add_message(regular_user, staff_user, ticket):
    msg1 = add_message(actor=regular_user, ticket_id=ticket.id, body="Hello")
    assert not msg1.is_staff_reply
    ticket.refresh_from_db()
    assert ticket.status == "pending_staff"
    
    msg2 = add_message(actor=staff_user, ticket_id=ticket.id, body="Hi")
    assert msg2.is_staff_reply
    ticket.refresh_from_db()
    assert ticket.status == "pending_user"

def test_internal_note(regular_user, staff_user, ticket):
    with pytest.raises(PermissionDenied):
        add_internal_note(actor=regular_user, ticket_id=ticket.id, body="Secret")
    
    note = add_internal_note(actor=staff_user, ticket_id=ticket.id, body="Secret")
    assert note.body == "Secret"

def test_update_ticket_status(regular_user, staff_user, ticket):
    with pytest.raises(PermissionDenied):
        update_ticket_status(actor=regular_user, ticket_id=ticket.id, new_status="resolved")
    
    update_ticket_status(actor=staff_user, ticket_id=ticket.id, new_status="resolved")
    ticket.refresh_from_db()
    assert ticket.status == "resolved"
    assert ticket.status_history.count() == 1

def test_assign_ticket(regular_user, staff_user, ticket):
    with pytest.raises(PermissionDenied):
        assign_ticket(actor=regular_user, ticket_id=ticket.id, assignee_id=staff_user.id)
    
    assignment = assign_ticket(actor=staff_user, ticket_id=ticket.id, assignee_id=staff_user.id)
    assert assignment.assignee == staff_user

def test_conversation_history_saved_between_user_and_platform_admin(regular_user, staff_user):
    # Step 1: User submits ticket (Turn 1)
    ticket = create_ticket(
        actor=regular_user,
        subject="Integration Bug",
        body="I cannot complete payment with Telebirr.",
        category="billing",
        priority="high"
    )
    assert ticket.messages.count() == 1
    assert list(ticket.conversation_history)[0].body == "I cannot complete payment with Telebirr."
    assert not list(ticket.conversation_history)[0].is_staff_reply

    # Step 2: Platform Admin replies (Turn 2)
    admin_reply = add_message(
        actor=staff_user,
        ticket_id=ticket.id,
        body="We are looking into the Telebirr gateway. Could you share your transaction ID?"
    )
    assert admin_reply.is_staff_reply
    ticket.refresh_from_db()
    assert ticket.messages.count() == 2
    assert ticket.status == "pending_user"

    # Step 3: User replies back with details (Turn 3)
    user_reply = add_message(
        actor=regular_user,
        ticket_id=ticket.id,
        body="Transaction reference is TXN-998811."
    )
    assert not user_reply.is_staff_reply
    ticket.refresh_from_db()
    assert ticket.messages.count() == 3
    assert ticket.status == "pending_staff"

    # Step 4: Platform Admin resolves and replies (Turn 4)
    admin_reply2 = add_message(
        actor=staff_user,
        ticket_id=ticket.id,
        body="Payment verified and your account is upgraded. Thanks!"
    )
    assert admin_reply2.is_staff_reply
    ticket.refresh_from_db()
    assert ticket.messages.count() == 4

    # Verify complete conversation history integrity
    history = list(ticket.conversation_history)
    assert len(history) == 4
    assert [m.is_staff_reply for m in history] == [False, True, False, True]
    assert [m.author for m in history] == [regular_user, staff_user, regular_user, staff_user]

    formatted_text = ticket.get_conversation_history()
    assert "Integration Bug" in str(ticket)
    assert "Platform Admin" in formatted_text
    assert "TXN-998811" in formatted_text
    assert "Telebirr" in formatted_text

