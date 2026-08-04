from django.utils import timezone
from events.models import EventRegistration
from .models import GeneralConfiguration


def should_show_onboarding_ticket(user=None, upcoming_event=None, user_registration=None) -> bool:
    """
    Prüft alle Bedingungen aus der GeneralConfiguration, um zu entscheiden,
    ob die Ticket-Karte auf dem Dashboard angezeigt werden soll.
    """
    config = GeneralConfiguration.load()

    # 1. Globale Ticket-Anzeige Schalter
    if not config.ticket_enabled:
        return False

    # 2. Prüfen, ob Ticket nur X Tage vor Event-Start angezeigt werden soll (wenn > 0)
    if config.ticket_days_before_event > 0:
        if not upcoming_event or not upcoming_event.start_date:
            return False
        days_until_event = (upcoming_event.start_date.date() - timezone.now().date()).days
        if days_until_event > config.ticket_days_before_event:
            return False

    # 3. Prüfen, ob Ticket nur angezeigt wird, wenn der Gast bezahlt hat
    if config.ticket_requires_payment:
        if not user or not user.is_authenticated:
            return False
        if not user_registration or user_registration.payment_status != EventRegistration.PaymentStatus.PAID:
            return False

    return True
