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

        now = timezone.now()
        # Präzise Datums- & Zeitdifferenz in Tagen (lokale Zeitzone berücksichtigend)
        local_now_date = timezone.localtime(now).date()
        local_event_date = timezone.localtime(upcoming_event.start_date).date()
        days_until_event = (local_event_date - local_now_date).days

        # Wenn der zeitliche Abstand in Tagen größer ist als der konfigurierte Wert X
        if days_until_event > config.ticket_days_before_event:
            return False

        # Zusätzliche Prüfung auf Stunden-Ebene (falls Event in der Zukunft liegt)
        if upcoming_event.start_date > now:
            remaining_seconds = (upcoming_event.start_date - now).total_seconds()
            max_seconds = config.ticket_days_before_event * 86400
            if remaining_seconds > max_seconds:
                return False

    # 3. Prüfen, ob Ticket nur angezeigt wird, wenn der Gast bezahlt hat
    if config.ticket_requires_payment:
        if not user or not user.is_authenticated:
            return False
        if not user_registration or user_registration.payment_status != EventRegistration.PaymentStatus.PAID:
            return False

    return True
