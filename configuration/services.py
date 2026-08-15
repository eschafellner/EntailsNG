from django.utils import timezone
from events.models import Event, EventRegistration
from .models import GeneralConfiguration


def should_show_onboarding_ticket(user=None, upcoming_event=None, user_registration=None, feature_flags_dict=None) -> bool:
    """
    Prüft alle Bedingungen aus FeatureFlag & GeneralConfiguration, um zu entscheiden,
    ob die Ticket-Karte auf dem Dashboard angezeigt werden soll.
    Verwendet das gecachte Feature-Flag-Dictionary zur Vermeidung redundanter DB-Queries.
    """
    # 0. Prüfen, ob das Feature-Flag "onboarding_ticket" in den Feature-Flags aktiviert ist
    if feature_flags_dict is None:
        from .context_processors import _load_feature_flags
        feature_flags_dict = _load_feature_flags()

    if not feature_flags_dict.get('onboarding_ticket', True):
        return False

    # 1. Globale Ticket-Anzeige Schalter aus Allgemeine Konfiguration
    config = GeneralConfiguration.load()
    if not config.ticket_enabled:
        return False

    if upcoming_event is None:
        upcoming_event = Event.objects.get_active()

    # 2. Ist überhaupt ein Event vorhanden?
    if not upcoming_event or not upcoming_event.start_date:
        return False

    now = timezone.now()

    # Prüfen, ob das Event bereits beendet ist (end_date überschritten)
    if upcoming_event.end_date and now > upcoming_event.end_date:
        if config.expired_ticket_mode == GeneralConfiguration.ExpiredTicketMode.HIDE:
            return False  # Mode "Event beendet": Sofort ausblenden
        # Mode "WORN": Ticket bleibt sichtbar (wird im Template als entwertet dargestellt)

    # 3. Prüfen, ob Ticket nur X Tage vor Event-Start angezeigt werden soll (wenn X > 0)
    if config.ticket_days_before_event > 0:
        # Wenn das Event in der Zukunft liegt:
        if upcoming_event.start_date > now:
            time_until_start = upcoming_event.start_date - now
            days_until_start = time_until_start.total_seconds() / 86400.0

            # Das Ticket darf erst angezeigt werden, wenn der Abstand <= X Tage ist!
            # Ist das Event noch weiter als X Tage entfernt (z. B. 2,7 Tage bei X = 1), wird das Ticket verborgen.
            if days_until_start > float(config.ticket_days_before_event):
                return False

    # 4. Prüfen, ob Ticket nur angezeigt wird, wenn der Gast bezahlt hat
    if config.ticket_requires_payment:
        if not user or not user.is_authenticated:
            return False
        if not user_registration or user_registration.payment_status != EventRegistration.PaymentStatus.PAID:
            return False

    return True

