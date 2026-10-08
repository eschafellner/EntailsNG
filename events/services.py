from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from .models import Event, EventRegistration, TicketType
from .exceptions import (
    RegistrationError,
    EventNotOpenError,
    EventFullError,
    RegistrationDeadlinePassedError,
    InvalidTicketTypeError,
    EventLifecycleError,
)


@dataclass(frozen=True)
class ReadinessCheck:
    label: str
    detail: str
    level: str  # ok, warning, blocker


@dataclass(frozen=True)
class EventReadinessReport:
    checks: tuple[ReadinessCheck, ...]

    @property
    def can_open(self):
        return not any(check.level == 'blocker' for check in self.checks)


class EventLifecycleService:
    @staticmethod
    def registration_readiness(event):
        """Prüft die Voraussetzungen für das Öffnen einer Entwurfsveranstaltung."""
        from configuration.models import GeneralConfiguration
        from emails.models import GeneralEmailSettings
        from seating.models import SeatingCell, SeatingPlan

        checks = []

        def add(label, detail, level='ok'):
            checks.append(ReadinessCheck(label, detail, level))

        if event.status != Event.Status.DRAFT:
            add('Status', 'Nur eine Veranstaltung im Entwurf kann geöffnet werden.', 'blocker')
        else:
            add('Status', 'Die Veranstaltung ist im Entwurf.')

        now = timezone.now()
        if not event.start_date or not event.end_date or event.end_date <= event.start_date or event.start_date <= now:
            add('Zeitraum', 'Beginn muss in der Zukunft liegen; Ende muss nach dem Beginn liegen.', 'blocker')
        else:
            add('Zeitraum', 'Beginn und Ende sind gültig.')

        if not event.location.strip():
            add('Veranstaltungsort', 'Bitte einen Veranstaltungsort eintragen.', 'blocker')
        else:
            add('Veranstaltungsort', event.location)

        if event.max_guests < 1:
            add('Kapazität', 'Bitte eine maximale Teilnehmerzahl größer als null festlegen.', 'blocker')
        else:
            add('Kapazität', f'Maximal {event.max_guests} Gäste.')

        other_active = Event.objects.filter(is_active=True).exclude(pk=event.pk).first()
        if other_active:
            add('Aktive Veranstaltung', f'„{other_active.title}“ ist noch aktiv. Bitte diese Veranstaltung zuerst abschließen oder deaktivieren.', 'blocker')
        else:
            add('Aktive Veranstaltung', 'Keine andere Veranstaltung ist aktiv.')

        tickets = list(event.ticket_types.filter(is_active=True))
        if not tickets:
            add('Tickets', 'Bitte mindestens eine aktive Ticketkategorie anlegen.', 'blocker')
        else:
            add('Tickets', f'{len(tickets)} aktive Ticketkategorie(n).')

        email_settings = GeneralEmailSettings.load()
        if not email_settings.is_operational:
            add('E-Mail-Versand', email_settings.blocking_reason or 'Der E-Mail-Versand ist nicht betriebsbereit.', 'blocker')
        else:
            add('E-Mail-Versand', 'Der Versand für Registrierungs-E-Mails ist konfiguriert.')
            if email_settings.is_sandbox:
                add('E-Mail-Testmodus', email_settings.blocking_reason or 'Der Testmodus ist aktiv.', 'warning')

        if any(ticket.price > 0 for ticket in tickets):
            if not GeneralConfiguration.load().has_payment_details:
                add('Zahlungsdaten', 'Für kostenpflichtige Tickets bitte IBAN und Kontoinhaber hinterlegen.', 'blocker')
            else:
                add('Zahlungsdaten', 'IBAN und Kontoinhaber sind hinterlegt.')

        if not event.description.strip():
            add('Beschreibung', 'Eine Beschreibung für Gäste fehlt.', 'warning')
        else:
            add('Beschreibung', 'Eine Beschreibung ist vorhanden.')

        plan = SeatingPlan.objects.filter(event=event).first()
        if plan is None:
            add('Sitzplan', 'Es ist noch kein Sitzplan eingerichtet.', 'warning')
        else:
            seat_count = SeatingCell.objects.filter(plan=plan, cell_type=SeatingCell.CellType.SEAT).exclude(
                reservation_status=SeatingCell.ReservationStatus.BLOCKED
            ).count()
            if seat_count < event.max_guests:
                add('Sitzplan', f'{seat_count} nutzbare Sitzplätze für {event.max_guests} mögliche Gäste.', 'warning')
            else:
                add('Sitzplan', f'{seat_count} nutzbare Sitzplätze.')

        return EventReadinessReport(tuple(checks))

    @staticmethod
    @transaction.atomic
    def open_registration(event_id):
        event = Event.objects.select_for_update().get(pk=event_id)
        report = EventLifecycleService.registration_readiness(event)
        if not report.can_open:
            reasons = '; '.join(check.detail for check in report.checks if check.level == 'blocker')
            raise EventLifecycleError(f'Anmeldung kann nicht geöffnet werden: {reasons}')
        event.status = Event.Status.REGISTRATION_OPEN
        event.is_active = True
        event.save(update_fields=['status', 'is_active', 'updated_at'])
        return event

    @staticmethod
    @transaction.atomic
    def finish_event(event_id):
        """Beendet ein Event und archiviert seine Teams als einen atomaren Vorgang."""
        from configuration.translations import get_translation
        from tournaments.models import Tournament
        from tournaments.services.registration import archive_teams_for_event

        event = Event.objects.select_for_update().get(pk=event_id)
        if event.status in (Event.Status.DRAFT, Event.Status.CANCELLED):
            raise EventLifecycleError(get_translation(
                'msg_event_finish_invalid_status',
                'Entwürfe und abgesagte Veranstaltungen können nicht abgeschlossen werden.',
            ))
        tournaments = list(
            Tournament.objects.select_for_update()
            .filter(event=event)
            .order_by('pk')
            .values_list('title', 'status')
        )
        open_tournaments = [
            title for title, status in tournaments
            if status not in (Tournament.Status.FINISHED, Tournament.Status.CANCELLED)
        ]
        if open_tournaments:
            names = ', '.join(open_tournaments[:3])
            if len(open_tournaments) > 3:
                names += ', …'
            raise EventLifecycleError(get_translation(
                'msg_event_finish_open_tournaments',
                'Bitte beende oder sage zuerst die offenen Turniere ab: {tournaments}.',
                tournaments=names,
            ))

        if event.status != Event.Status.FINISHED or event.is_active:
            event.status = Event.Status.FINISHED
            event.is_active = False
            event.save(update_fields=['status', 'is_active', 'updated_at'])

        archived_count = archive_teams_for_event(event)
        return event, archived_count


class RegistrationService:

    @staticmethod
    @transaction.atomic
    def register_user(user, event_id: int, ticket_type_id: int = None, *, clan_seat_hold_id=None):
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

        from django.contrib.auth import get_user_model
        from configuration.translations import get_translation
        user = get_user_model().objects.select_for_update(no_key=True).get(pk=user.pk)
        if user.is_banned:
            raise RegistrationError(get_translation('ban_access_failed'))
        if user.deleted_at or not user.is_active:
            raise RegistrationError(get_translation('account_deleted_registration_blocked'))

        # 1. Event abrufen und per DB-Lock sperren
        try:
            event = Event.objects.select_for_update().get(pk=event_id, is_active=True)
        except Event.DoesNotExist:
            raise EventNotOpenError("Das angeforderte Event existiert nicht oder ist inaktiv.")

        reserved_clan_slot = False
        if clan_seat_hold_id is not None:
            from seating.models import ClanSeatHold
            reserved_clan_slot = ClanSeatHold.objects.filter(pk=clan_seat_hold_id,
                allocation__event=event, payment__status='PAID', funded_registration__isnull=True,
                protection_active=True).exists()
            if not reserved_clan_slot:
                raise RegistrationError(get_translation('clan_payment_not_paid'))

        # 2. Idempotenz: Bestehende Registrierung prüfen
        existing_reg = EventRegistration.objects.filter(user=user, event=event).first()
        if existing_reg and existing_reg.payment_status != EventRegistration.PaymentStatus.CANCELLED:
            return existing_reg, False, False

        # 3. Zentrale fachliche Prüfung via Single Source of Truth
        can_reg, reason = event.can_register(user=None)
        if reserved_clan_slot and event.is_active and event.effective_status in (Event.Status.REGISTRATION_OPEN, Event.Status.RUNNING) and not event.is_expired:
            # This registration consumes a prepaid slot, rather than a new slot.
            from seating.clan_payments import reserved_ticket_count
            can_reg = event.active_registrations_count + reserved_ticket_count(event.pk) <= event.max_guests
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
                ticket_query = TicketType.objects.filter(pk=ticket_type_id_int, event=event)
                if reserved_clan_slot:
                    if not ClanSeatHold.objects.filter(pk=clan_seat_hold_id, payment__ticket_type_id=ticket_type_id_int).exists():
                        raise InvalidTicketTypeError(get_translation('clan_payment_ticket_mismatch'))
                else:
                    ticket_query = ticket_query.filter(is_active=True)
                selected_ticket = ticket_query.first()
                if not selected_ticket:
                    raise InvalidTicketTypeError("Der gewählte Tickettyp existiert nicht oder ist für dieses Event inaktiv.")
            except (ValueError, TypeError):
                raise InvalidTicketTypeError("Ungültige Ticketkategorie übergeben.")
        else:
            active_tickets = list(event.ticket_types.filter(is_active=True))
            if len(active_tickets) >= 1:
                selected_ticket = active_tickets[0]

        booking_price = selected_ticket.price if selected_ticket else None

        # 7. Registrierung erstellen oder stornierte Registrierung reaktivieren
        if existing_reg:
            existing_reg.payment_status = EventRegistration.PaymentStatus.UNPAID
            existing_reg.ticket_type = selected_ticket
            existing_reg.booking_price = booking_price
            existing_reg.paid_amount = 0.00
            existing_reg.paid_at = None
            existing_reg.cancelled_at = None
            existing_reg.is_checked_in = False
            existing_reg.checked_in_at = None
            existing_reg.save()
            return existing_reg, False, True

        registration = EventRegistration.objects.create(
            user=user,
            event=event,
            ticket_type=selected_ticket,
            booking_price=booking_price,
        )
        return registration, True, False


class PaymentService:
    """
    Zentraler Service für Zahlungs- und Stornierungs-Orchestrierung.
    Kapselt Statusänderungen, Sitzplatz-Updates, Cache-Invalidierung und E-Mail-Versand.
    """

    @staticmethod
    @transaction.atomic
    def mark_paid(registration, amount=None, send_email=True, allow_overbooking=False, *, clan_seat_hold_id=None):
        from seating.models import SeatingCell
        from configuration.cache import invalidate_event_capacity_cache
        from django.contrib.auth import get_user_model
        from django.core.exceptions import ValidationError
        from configuration.translations import get_translation

        # Robustness: Ensure registration is persisted before locking
        if not registration.pk:
            registration.save()

        # Gleiche Reihenfolge wie Selbstlöschung: User -> Event -> Anmeldung.
        user_id, event_id = EventRegistration.objects.values_list('user_id', 'event_id').get(pk=registration.pk)
        owner = get_user_model().objects.select_for_update(no_key=True).get(pk=user_id)
        if owner.deleted_at:
            raise ValidationError(get_translation('account_deleted_registration_blocked'))
        Event.objects.select_for_update().get(pk=event_id)
        reg = EventRegistration.objects.select_for_update().get(pk=registration.pk)
        from seating.models import ClanSeatHold
        funding = ClanSeatHold.objects.filter(funded_registration=reg).select_related('payment').first()
        if funding and funding.pk != clan_seat_hold_id:
            raise ValidationError(get_translation('clan_payment_managed_hint'))
        if clan_seat_hold_id is not None and (not funding or funding.payment.status != 'PAID' or amount != funding.payment.unit_price):
            raise ValidationError(get_translation('clan_payment_not_paid'))

        # Überbuchungsschutz: Reaktivierung einer stornierten Anmeldung prüft Kapazität
        if reg.payment_status == EventRegistration.PaymentStatus.CANCELLED and reg.event_id:
            event = Event.objects.select_for_update().get(pk=reg.event_id)
            if event.is_full and not allow_overbooking and not funding:
                raise EventFullError(
                    f"Die Veranstaltung '{event.title}' ist mit {event.max_guests} Teilnehmern bereits ausgebucht. "
                    f"Die stornierte Anmeldung von {reg.user.username} kann nicht als bezahlt reaktiviert werden."
                )

        reg.payment_status = EventRegistration.PaymentStatus.PAID
        if not reg.paid_at:
            reg.paid_at = funding.payment.received_at if funding else timezone.now()
        if amount is not None:
            reg.paid_amount = amount
        elif not reg.paid_amount or reg.paid_amount == 0:
            if reg.booking_price is not None:
                reg.paid_amount = reg.booking_price
            elif reg.ticket_type:
                reg.paid_amount = reg.ticket_type.price
        reg.cancelled_at = None
        reg.save()

        # In-Memory-Objekt synchronisieren
        registration.payment_status = reg.payment_status
        registration.paid_at = reg.paid_at
        registration.paid_amount = reg.paid_amount
        registration.cancelled_at = reg.cancelled_at

        # Sitzplätze synchronisieren (Bulk Update ohne N+1 mit Enum)
        reg.seats.filter(
            reservation_status=SeatingCell.ReservationStatus.PRE_RESERVED
        ).update(reservation_status=SeatingCell.ReservationStatus.RESERVED)

        if reg.event_id:
            invalidate_event_capacity_cache(reg.event_id)

        # E-Mail erst NACH erfolgreichem DB-Commit versenden
        if send_email:
            transaction.on_commit(reg.send_payment_confirmation_email)

        return reg

    @staticmethod
    @transaction.atomic
    def mark_cancelled(registration):
        from seating.models import SeatingCell
        from configuration.cache import invalidate_event_capacity_cache

        # Robustness: Ensure registration is persisted before locking
        if not registration.pk:
            registration.save()

        from django.contrib.auth import get_user_model
        user_id, event_id = EventRegistration.objects.values_list('user_id', 'event_id').get(pk=registration.pk)
        get_user_model().objects.select_for_update(no_key=True).get(pk=user_id)
        Event.objects.select_for_update().get(pk=event_id)
        reg = EventRegistration.objects.select_for_update().get(pk=registration.pk)
        from seating.models import ClanSeatHold
        from seating.clan_payments import log
        funding = ClanSeatHold.objects.filter(funded_registration=reg).select_related('payment').first()
        if funding:
            log(funding.payment, None, 'TICKET_CANCELLED', details={'registration_id': reg.pk, 'hold_id': funding.pk})
            ClanSeatHold.objects.filter(pk=funding.pk).update(funded_registration=None,
                registration_snapshot={}, state='OPEN', claimed_by=None)
            reg.paid_amount = 0
            reg.paid_at = None
        reg.payment_status = EventRegistration.PaymentStatus.CANCELLED
        reg.is_checked_in = False
        reg.checked_in_at = None
        reg.cancelled_at = timezone.now()
        reg.save()

        # In-Memory-Objekt synchronisieren
        registration.payment_status = reg.payment_status
        registration.is_checked_in = reg.is_checked_in
        registration.checked_in_at = reg.checked_in_at
        registration.cancelled_at = reg.cancelled_at

        # Sitzplätze atomar freigeben (Bulk Update mit Enum)
        reg.seats.update(
            registration=None,
            reservation_status=SeatingCell.ReservationStatus.FREE
        )
        if reg.event_id:
            invalidate_event_capacity_cache(reg.event_id)

        return reg


class CheckInService:
    """
    Zentraler Service für Einlass und Check-in.
    Schützt durch transaktionale Row-Locks (select_for_update) vor Race Conditions
    zwischen gleichzeitigem Check-in und Stornierungen.
    """

    @staticmethod
    @transaction.atomic
    def check_in(registration_id: int, target_event=None, actor=None):
        from django.core.exceptions import ValidationError
        from django.contrib.auth import get_user_model
        user_id = EventRegistration.objects.values_list('user_id', flat=True).get(pk=registration_id)
        get_user_model().objects.select_for_update(no_key=True).get(pk=user_id)
        event_id = EventRegistration.objects.values_list('event_id', flat=True).get(pk=registration_id)
        Event.objects.select_for_update().get(pk=event_id)
        reg = EventRegistration.objects.select_for_update(of=('self',)).select_related('event', 'user').get(pk=registration_id)
        result = reg.can_check_in(target_event=target_event, actor=actor)
        if not result.allowed:
            raise ValidationError(result.reason)

        if not reg.is_checked_in:
            reg.is_checked_in = True
            reg.checked_in_at = timezone.now()
            reg.save(update_fields=['is_checked_in', 'checked_in_at'])
        return reg

    @staticmethod
    @transaction.atomic
    def check_out(registration_id: int):
        reg = EventRegistration.objects.select_for_update().get(pk=registration_id)
        if reg.is_checked_in:
            reg.is_checked_in = False
            reg.checked_in_at = None
            reg.save(update_fields=['is_checked_in', 'checked_in_at'])
        return reg
