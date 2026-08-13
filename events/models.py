import uuid
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone


class EventManager(models.Manager):
    def get_active(self):
        """Liefert die aktuell aktive Hauptveranstaltung oder None."""
        return self.filter(is_active=True).first()


# 1. ZUERST DAS EVENT-MODELL DEFINIEREN:
class Event(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Entwurf'
        REGISTRATION_OPEN = 'OPEN', 'Anmeldung geöffnet'
        RUNNING = 'RUNNING', 'Läuft aktuell'
        FINISHED = 'FINISHED', 'Beendet'
        CANCELLED = 'CANCELLED', 'Abgesagt'

    title = models.CharField(max_length=100, verbose_name="Titel")
    slug = models.SlugField(max_length=100, unique=True, verbose_name="URL-Slug")

    #Das Flag für die aktuell aktive Veranstaltung
    is_active = models.BooleanField(
        default=False,
        verbose_name="Aktive Hauptveranstaltung",
        help_text="Nur EINE Veranstaltung sollte gleichzeitig aktiv sein!"
    )
    description = models.TextField(blank=True, verbose_name="Beschreibung")

    location = models.CharField(max_length=200, blank=True, verbose_name="Veranstaltungsort")
    start_date = models.DateTimeField(verbose_name="Startzeitpunkt")
    end_date = models.DateTimeField(verbose_name="Endzeitpunkt")

    max_guests = models.PositiveIntegerField(default=50, verbose_name="Max. Teilnehmer")
    price = models.DecimalField(max_digits=6, decimal_places=2, default=0.00, verbose_name="Ticketpreis (€)")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Status"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Erstellt am")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Zuletzt geändert")

    objects = EventManager()

    class Meta:
        verbose_name = "Veranstaltung"
        verbose_name_plural = "Veranstaltungen"
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    @property
    def effective_status(self):
        """Berechnet den fachlich korrekten Status basierend auf Zeitstempeln und Admin-Status."""
        now = timezone.now()
        if self.status == self.Status.CANCELLED:
            return self.Status.CANCELLED
        if self.status == self.Status.DRAFT:
            return self.Status.DRAFT

        if self.end_date and now > self.end_date:
            return self.Status.FINISHED
        if self.start_date and self.end_date and self.start_date <= now <= self.end_date:
            return self.Status.RUNNING

        return self.status

    @property
    def is_registration_open(self):
        """Prüft, ob Anmeldungen für dieses Event aktuell offen sind."""
        if not self.is_active or self.effective_status != self.Status.REGISTRATION_OPEN:
            return False
        return True

    @property
    def active_registrations_count(self):
        """Liefert die Anzahl der aktiven (nicht stornierten) Anmeldungen."""
        return self.registrations.exclude(payment_status=EventRegistration.PaymentStatus.CANCELLED).count()

    @property
    def is_full(self):
        """Prüft, ob die maximale Teilnehmerzahl erreicht ist."""
        if not self.max_guests:
            return False
        return self.active_registrations_count >= self.max_guests

    def clean(self):
        from django.core.exceptions import ValidationError
        super().clean()
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError({'end_date': 'Das Enddatum muss nach dem Startdatum liegen.'})

        if self.is_active and self.status == self.Status.DRAFT:
            raise ValidationError({'is_active': 'Ein Event im Status "Entwurf" kann nicht als aktive Hauptveranstaltung gesetzt werden.'})

    def save(self, *args, **kwargs):
        from django.db import transaction
        now = timezone.now()

        # Automatischer Statuswechsel auf FINISHED, wenn Enddatum vorüber ist
        if self.end_date and now > self.end_date and self.status not in [self.Status.DRAFT, self.Status.CANCELLED]:
            self.status = self.Status.FINISHED

        with transaction.atomic():
            if self.is_active:
                Event.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
            super().save(*args, **kwargs)



# 2. DANACH DAS TICKET-MODELL (greift auf Event zu):
class TicketType(models.Model):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='ticket_types',
        verbose_name="Veranstaltung"
    )
    name = models.CharField(max_length=50, verbose_name="Kategorie Name")
    price = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="Preis (€)")
    description = models.CharField(max_length=200, blank=True, verbose_name="Hinweis")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")

    class Meta:
        verbose_name = "Ticket-Kategorie"
        verbose_name_plural = "Ticket-Kategorien"

    def __str__(self):
        return f"{self.event.title} - {self.name} ({self.price} €)"


class EventRegistration(models.Model):
    class PaymentStatus(models.TextChoices):
        UNPAID = 'UNPAID', 'Offen'
        PAID = 'PAID', 'Bezahlt'
        CANCELLED = 'CANCELLED', 'Storniert'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='registrations',
        verbose_name="Benutzer",
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='registrations',
        verbose_name="Veranstaltung",
    )
    ticket_type = models.ForeignKey(
        TicketType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Gewähltes Ticket",
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
        verbose_name="Bezahlstatus",
    )
    paid_amount = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0.00,
        verbose_name="Tatsächlich bezahlter Betrag (€)",
    )
    paid_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Bezahlt am"
    )

    # -------------------------------------------------------------------------
    # CHECK-IN BEREICH
    # -------------------------------------------------------------------------
    is_checked_in = models.BooleanField(
        default=False,
        verbose_name="Eingecheckt (Vor Ort)",
        help_text="Gibt an, ob der Gast vor Ort eingecheckt hat.",
    )
    checked_in_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Check-in Zeitpunkt",
    )

    # <-- HIER PASST ES PERFEKT HIN
    checkin_token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name="Check-in Secret Token",
        help_text="Eindeutiges Token für den QR-Code Einlass-Scan",
    )

    def check_in(self):
        """Hilfsmethode: Checkt den Gast ein und setzt die aktuelle Uhrzeit"""
        if not self.is_checked_in:
            self.is_checked_in = True
            self.checked_in_at = timezone.now()
            self.save(update_fields=['is_checked_in', 'checked_in_at'])

    def check_out(self):
        """Hilfsmethode: Macht den Check-in wieder rückgängig"""
        if self.is_checked_in:
            self.is_checked_in = False
            self.checked_in_at = None
            self.save(update_fields=['is_checked_in', 'checked_in_at'])

    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Angemeldet am"
    )

    class Meta:
        verbose_name = "Anmeldung"
        verbose_name_plural = "Anmeldungen"
        unique_together = ('user', 'event')

    def __str__(self):
        return f"{self.user.username} -> {self.event.title} ({self.get_payment_status_display()})"

    def clean(self):
        from django.core.exceptions import ValidationError
        super().clean()
        if self.pk is None and self.event:
            if not self.event.is_active or self.event.status != Event.Status.REGISTRATION_OPEN:
                raise ValidationError(
                    f"Anmeldung für '{self.event.title}' ist aktuell nicht geöffnet (Status: {self.event.get_status_display()})."
                )
            if self.event.is_full:
                raise ValidationError(f"Event '{self.event.title}' ist ausgebucht ({self.event.max_guests} max).")
            if self.ticket_type and self.ticket_type.event != self.event:
                raise ValidationError("Das ausgewählte Ticket gehört nicht zu diesem Event.")


    def mark_as_paid(self, send_email=True):
        """Explizite Geschäftslogik-Methode: Markiert die Anmeldung als bezahlt."""
        self.payment_status = self.PaymentStatus.PAID
        self.save(send_email=send_email)

    def mark_as_cancelled(self):
        """Explizite Geschäftslogik-Methode: Storniert die Anmeldung und gibt Plätze frei."""
        self.payment_status = self.PaymentStatus.CANCELLED
        self.save(send_email=False)

    def save(self, *args, send_email=True, **kwargs):
        is_new = self.pk is None
        old_payment_status = None
        if not is_new:
            try:
                old_payment_status = EventRegistration.objects.get(pk=self.pk).payment_status
            except EventRegistration.DoesNotExist:
                pass

        if self.payment_status == self.PaymentStatus.PAID and not self.paid_at:
            from django.utils import timezone
            self.paid_at = timezone.now()

        super().save(*args, **kwargs)

        # Automatische Aktualisierung des zugewiesenen Sitzplatzes bei Statusänderung
        for seat in list(self.seats.all()):
            if self.payment_status == self.PaymentStatus.PAID:
                if seat.reservation_status != seat.ReservationStatus.RESERVED:
                    seat.reservation_status = seat.ReservationStatus.RESERVED
                    seat.save(update_fields=['reservation_status'])
            elif self.payment_status == self.PaymentStatus.UNPAID:
                if (
                    seat.reservation_status
                    != seat.ReservationStatus.PRE_RESERVED
                ):
                    seat.reservation_status = (
                        seat.ReservationStatus.PRE_RESERVED
                    )
                    seat.save(update_fields=['reservation_status'])
            elif self.payment_status == self.PaymentStatus.CANCELLED:
                seat.registration = None
                seat.reservation_status = seat.ReservationStatus.FREE
                seat.save(update_fields=['registration', 'reservation_status'])

        # Automatische Zahlungsbestätigungs-E-Mail erst NACH erfolgreichem DB-Commit versenden (transaction.on_commit)
        if send_email and self.payment_status == self.PaymentStatus.PAID and old_payment_status != self.PaymentStatus.PAID:
            transaction.on_commit(self.send_payment_confirmation_email)

    def send_payment_confirmation_email(self):
        """Sendet die automatische E-Mail-Zahlungsbestätigung an den Gast."""
        try:
            from emails.services import send_system_email
            seat = self.seats.first()
            seat_label = seat.seat_label if seat else "Noch kein Sitzplatz"

            context_data = {
                'username': self.user.username,
                'full_name': self.user.get_full_name() or self.user.username,
                'event_title': self.event.title,
                'amount': f"{self.paid_amount:.2f}",
                'payment_reference': getattr(self, 'payment_reference', f"REG-{self.id}"),
                'seat_label': seat_label,
                'ticket_type': self.ticket_type.name if self.ticket_type else "Standard Ticket",
            }
            send_system_email('payment_confirmation', self.user.email, context_data)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Fehler beim Auslösen der Zahlungsbestätigung: {e}")


from django.db.models.signals import pre_delete
from django.dispatch import receiver


@receiver(pre_delete, sender=EventRegistration)
def release_seats_on_registration_delete(sender, instance, **kwargs):
    """Gibt alle verknüpften Sitzplätze frei, wenn eine EventRegistration gelöscht wird."""
    from seating.models import SeatingCell
    SeatingCell.objects.filter(registration=instance).update(
        registration=None,
        reservation_status=SeatingCell.ReservationStatus.FREE
    )


