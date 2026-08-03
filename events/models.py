import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


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

    class Meta:
        verbose_name = "Veranstaltung"
        verbose_name_plural = "Veranstaltungen"
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

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

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        # Automatische Aktualisierung des zugewiesenen Sitzplatzes bei Statusänderung
        for seat in self.seats.all():
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
