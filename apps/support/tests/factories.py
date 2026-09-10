import factory
from factory.django import DjangoModelFactory
from apps.support.models import Ticket, TicketMessage

class TicketFactory(DjangoModelFactory):
    class Meta:
        model = Ticket
    subject = factory.Sequence(lambda n: f"Ticket {n}")
    status = "open"
    priority = "normal"
    category = "general"

class TicketMessageFactory(DjangoModelFactory):
    class Meta:
        model = TicketMessage
    ticket = factory.SubFactory(TicketFactory)
    body = "Test message body."
