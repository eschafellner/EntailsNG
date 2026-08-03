from datetime import timedelta
from django.utils import timezone
from events.models import Event
from .models import FeatureConfig


def should_show_onboarding_ticket(user) -> bool:
    """
    Prüft alle Bedingungen aus der FeatureConfig, um zu entscheiden,
    ob das Onboarding-Ticket gerendert werden soll.
    """
    # 1. Ist die globale Funktion überhaupt aktiviert?
    config = FeatureConfig.load()
    if not config.onboarding_ticket_enabled:
        return False

    # 2. Prüfen, ob eine Event-Abhängigkeit besteht
    if config.onboarding_ticket_event_dependent:
        now = timezone.now()

        # Wir suchen das nächste aktive Event, dessen Enddatum (oder Startdatum) in der Zukunft liegt
        # (Passe 'start_date' ggf. an dein Feld im Event-Modell an)
        upcoming_event = (
            Event.objects.filter(is_active=True, start_date__gte=now)
            .order_by('start_date')
            .first()
        )

        # Wenn kein zukünftiges Event existiert, Ticket nicht anzeigen
        if not upcoming_event:
            return False

        # 3. Prüfen, ob die dynamische Anzeige (Tage-Countdown) aktiv ist
        if config.onboarding_ticket_dynamic_display:
            days_until_event = (upcoming_event.start_date - now).days

            # Ist der Abstand zum Event größer als der konfigurierte Schwellenwert?
            if days_until_event > config.onboarding_ticket_days_before_event:
                return False

    # Wenn alle aktiven Prüfungen bestanden wurden: Ticket anzeigen!
    return True
