from django.db import transaction
from django.utils import timezone
from .models import Event, EventRegistration, TicketType
from .exceptions import (
    RegistrationError,
    EventNotOpenError,
    EventFullError,
    RegistrationDeadlinePassedError,
    InvalidTicketTypeError,
)


class RegistrationService:

    @staticmethod
    @transaction.atomic
    def register_user(user, event_id: int, ticket_type_id: int = None):
        """
        Meldet den Benutzer für ein Event an.
        Prüft alle geschäftlichen Regeln:
        - Event existiert und is_active=True
        - Event-Status ist REGISTRATION_OPEN
        - Anmeldefrist / Event-Enddatum nicht überschritten
        - Freie Plätze vorhanden (max_guests nicht überschritten)
        - Tickettyp gültig und aktiv (falls angegeben oder zwingend erforderlich)

        Nutzt select_for_update() für DB-Level Transaktionssicherheit gegen Überbuchung.
        Rückgabe: tuple (EventRegistration, created: bool)
        """
        if not user or not user.is_authenticated:
            raise RegistrationError("Du musst angemeldet sein, um dich zu registrieren.")

        # 1. Event abrufen und per DB-Lock sperren
        try:
            event = Event.objects.select_for_update().get(pk=event_id, is_active=True)
        except Event.DoesNotExist:
            raise EventNotOpenError("Das angeforderte Event existiert nicht oder ist inaktiv.")

        # 2. Idempotenz: Bestehende Registrierung prüfen
        existing_reg = EventRegistration.objects.filter(user=user, event=event).first()
        if existing_reg and existing_reg.payment_status != EventRegistration.PaymentStatus.CANCELLED:
            return existing_reg, False

        # 3. Zentrale fachliche Prüfung via Single Source of Truth
        can_reg, reason = event.can_register(user=None)
        if not can_reg:
            now = timezone.now()
            if event.end_date and now > event.end_date:
                raise RegistrationDeadlinePassedError(reason)
            elif event.is_full:
                raise EventFullError(reason)
            else:
                raise EventNotOpenError(reason)


        # 6. Tickettyp validieren
        selected_ticket = None
        if ticket_type_id:
            try:
                ticket_type_id_int = int(ticket_type_id)
                selected_ticket = TicketType.objects.filter(
                    pk=ticket_type_id_int, event=event, is_active=True
                ).first()
                if not selected_ticket:
                    raise InvalidTicketTypeError("Der gewählte Tickettyp existiert nicht oder ist für dieses Event inaktiv.")
            except (ValueError, TypeError):
                raise InvalidTicketTypeError("Ungültige Ticketkategorie übergeben.")
        else:
            active_tickets = list(event.ticket_types.filter(is_active=True))
            if len(active_tickets) >= 1:
                selected_ticket = active_tickets[0]

        # 7. Registrierung erstellen oder stornierte Registrierung reaktivieren
        if existing_reg:
            existing_reg.payment_status = EventRegistration.PaymentStatus.UNPAID
            existing_reg.ticket_type = selected_ticket
            existing_reg.paid_amount = 0.00
            existing_reg.paid_at = None
            existing_reg.cancelled_at = None
            existing_reg.is_checked_in = False
            existing_reg.checked_in_at = None
            existing_reg.save()
            return existing_reg, True

        registration = EventRegistration.objects.create(
            user=user,
            event=event,
            ticket_type=selected_ticket
        )

        return registration, True

