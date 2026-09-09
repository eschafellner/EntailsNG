from decimal import Decimal
import logging
import secrets
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify

from configuration.cache import invalidate_event_capacity_cache
from emails.services import send_system_email

logger = logging.getLogger(__name__)


def generate_short_code(length=8):
    """
    Generiert einen 8-stelligen unerratbaren, verwechslungsfreien Ticket-Kurzcode.
    Alphabet schließt 0/O und 1/I/L aus, um Lesefehler am Einlass zu verhindern.
    """
    alphabet = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


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

    @property
    def price(self):
        """
        Abgeleiteter Anzeigewert: Liefert den Mindestpreis der aktiven Tickets (Single Source of Truth).
        """
        if hasattr(self, '_initial_price'):
            return self._initial_price
        cheapest = self.ticket_types.filter(is_active=True).order_by('price').first()
        return cheapest.price if cheapest else Decimal('0.00')

    @price.setter
    def price(self, value):
        self._initial_price = Decimal(str(value)) if value is not None else Decimal('0.00')

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="Status"
    )

    allow_unpaid_seat_overwrite = models.BooleanField(
        default=True,
        verbose_name="Sitzplatz-Überschreibung nicht bezahlter Gäste",
        choices=[
            (True, "Ja, Überschreibung nicht bezahlter Gäste möglich"),
            (False, "Nein, Überschreibung nicht bezahlter Gäste möglich"),
        ],
        help_text="Legt fest, ob zahlende Gäste vorgemerkte Plätze unbezahlter Teilnehmer übernehmen dürfen.",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Erstellt am")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Zuletzt geändert")

    objects = EventManager()

    class Meta:
        verbose_name = "Veranstaltung"
        verbose_name_plural = "Veranstaltungen"
        ordering = ['-start_date']
        constraints = [
            models.UniqueConstraint(
                fields=['is_active'],
                condition=models.Q(is_active=True),
                name='only_one_active_event',
                violation_error_message="Es kann immer nur genau eine Hauptveranstaltung gleichzeitig aktiv sein."
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F('start_date')),
                name='event_end_date_after_start_date',
                violation_error_message="Das Enddatum muss nach dem Startdatum liegen."
            ),
        ]


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

    def get_effective_status_display(self):
        """Liefert den lesbaren Text des berechneten effektiven Status."""
        for choice_val, choice_label in self.Status.choices:
            if choice_val == self.effective_status:
                return choice_label
        return self.get_status_display()

    def can_register(self, user=None):
        """
        Zentrale fachliche Prüfung (Single Source of Truth), ob eine Neuanmeldung möglich ist.
        Wird konsistent von Service, Model.clean(), Admin und Views verwendet.
        Rückgabe: Tuple (can_register: bool, reason: str)
        """
        now = timezone.now()
        if not self.is_active:
            return False, f"Die Veranstaltung '{self.title}' ist inaktiv."
        if self.end_date and now > self.end_date:
            return False, "Der Anmeldezeitraum für diese Veranstaltung ist bereits verstrichen."
        if self.effective_status != self.Status.REGISTRATION_OPEN:
            return False, f"Eine Anmeldung für '{self.title}' ist derzeit nicht möglich (Status: {self.get_effective_status_display()})."
        if self.is_full:
            return False, f"Die maximale Teilnehmerzahl ({self.max_guests}) für '{self.title}' ist bereits erreicht."
        if user and user.is_authenticated:
            if self.registrations.filter(user=user).exclude(payment_status=EventRegistration.PaymentStatus.CANCELLED).exists():
                return False, f"Der Benutzer '{user.username}' ist bereits für diese Veranstaltung angemeldet."
        return True, ""

    @property
    def is_registration_open(self):
        """Prüft, ob Anmeldungen für dieses Event aktuell offen sind."""
        can_reg, _ = self.can_register()
        return can_reg

    @property
    def is_expired(self):
        """Prüft, ob das Event zeitlich bereits beendet ist."""
        return bool(self.end_date and timezone.now() > self.end_date)



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
        super().clean()
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            raise ValidationError({'end_date': 'Das Enddatum muss nach dem Startdatum liegen.'})
        if self.is_active and self.status == self.Status.DRAFT:
            raise ValidationError({'is_active': 'Ein Event im Status "Entwurf" kann nicht als aktive Hauptveranstaltung gesetzt werden.'})

    def save(self, *args, **kwargs):
        if not self.slug and self.title:
            base_slug = slugify(self.title) or "event"
            slug = base_slug
            count = 1
            while Event.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug

        with transaction.atomic():
            if self.is_active:
                active_events = Event.objects.filter(is_active=True)
                if self.pk:
                    active_events = active_events.exclude(pk=self.pk)
                active_events.update(is_active=False)
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


class CheckInResult(tuple):
    """
    Ergebnisobjekt der Einlassprüfung.
    Rückwärtskompatibel als 2-Tupel (allowed: bool, reason: str) entpackbar,
    bietet aber zusätzlich .allowed, .reason und .code für APIs.
    """
    def __new__(cls, allowed: bool, reason: str = "", code: str = "ok"):
        instance = super().__new__(cls, (allowed, reason))
        instance.allowed = allowed
        instance.reason = reason
        instance.code = code
        return instance


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
        help_text="Wird bei Bezahlung automatisch mit dem Ticketpreis initialisiert, falls nicht manuell angegeben.",
    )
    paid_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Bezahlt am"
    )
    cancelled_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Storniert am"
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
    short_code = models.CharField(
        max_length=12,
        default=generate_short_code,
        unique=True,
        db_index=True,
        editable=False,
        verbose_name="Ticket-Kurzcode",
        help_text="8-stelliger unerratbarer Code für die manuelle Einlass-Eingabe",
    )

    def can_check_in(self, target_event=None, actor=None):
        """
        Zentrale fachliche Prüfung, ob der Gast für das Event eingecheckt werden darf.
        Rückgabe: CheckInResult (entpackbar als: allowed, reason) mit .code
        """
        if self.payment_status != self.PaymentStatus.PAID:
            return CheckInResult(
                False,
                f"ABGELEHNT: Die Anmeldung von {self.user.username} ist noch NICHT BEZAHLT.",
                code="unpaid"
            )
        if self.event and self.event.status == Event.Status.CANCELLED:
            return CheckInResult(
                False,
                f"Check-in abgelehnt: Die Veranstaltung '{self.event.title}' wurde abgesagt.",
                code="event_cancelled"
            )

        active_event = target_event or Event.objects.get_active()
        if active_event and self.event_id != active_event.id:
            return CheckInResult(
                False,
                f"ABGELEHNT: Dieses Ticket gehört zur Veranstaltung '{self.event.title}' "
                f"und ist für die aktuelle Veranstaltung '{active_event.title}' nicht gültig!",
                code="event_mismatch"
            )
        return CheckInResult(True, "", code="ok")

    def check_in(self, target_event=None, actor=None):
        """
        Zentrale Methode zum Einchecken des Gastes (Single Source of Truth).
        Prüft zwingend den Bezahlstatus und die Gültigkeit der Anmeldung vor der Zustandsänderung.
        """
        result = self.can_check_in(target_event=target_event)
        if not result.allowed:
            raise ValidationError(result.reason)

        if not self.is_checked_in:
            self.is_checked_in = True
            self.checked_in_at = timezone.now()
            self.save(update_fields=['is_checked_in', 'checked_in_at'])
        return True

    def check_out(self):
        """Hilfsmethode: Macht den Check-in wieder rückgängig"""
        if self.is_checked_in:
            self.is_checked_in = False
            self.checked_in_at = None
            self.save(update_fields=['is_checked_in', 'checked_in_at'])

    @property
    def status_step(self):
        """Ermittelt den 4-Stufen-Statusfortschritt des Teilnehmers (1-4)."""
        if self.is_checked_in:
            return 4
        if self.payment_status == self.PaymentStatus.PAID:
            return 3
        return 2

    @property
    def seat_label(self):
        """Liefert die Bezeichnung des ersten zugewiesenen Sitzplatzes oder None."""
        seat = self.seats.first()
        if seat:
            return seat.seat_label or f'Pos ({seat.x},{seat.y})'
        return None

    @property
    def can_show_payment_qr(self):
        """Prüft, ob für diese Anmeldung ein GiroCode / Zahlungs-QR angezeigt werden kann."""
        if self.payment_status != self.PaymentStatus.UNPAID:
            return False
        from configuration.models import GeneralConfiguration
        config = GeneralConfiguration.load()
        if not config.has_payment_details:
            return False
        ticket_price = self.ticket_type.price if self.ticket_type else None
        return ticket_price is None or ticket_price > 0

    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Angemeldet am"
    )

    class Meta:
        verbose_name = "Anmeldung"
        verbose_name_plural = "Anmeldungen"
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'event'],
                name='unique_user_event_registration'
            ),
        ]

    def __str__(self):
        return f"{self.user.username} -> {self.event.title} ({self.get_payment_status_display()})"

    def clean(self):
        super().clean()
        if self.pk is None and self.event_id:
            can_reg, reason = self.event.can_register(user=self.user if self.user_id else None)
            if not can_reg:
                raise ValidationError({'event': reason})
        if self.ticket_type and self.event_id and self.ticket_type.event_id != self.event_id:
            raise ValidationError({'ticket_type': "Das ausgewählte Ticket gehört nicht zu diesem Event."})
        if self.ticket_type and not self.ticket_type.is_active:
            raise ValidationError({'ticket_type': "Die ausgewählte Ticketkategorie ist inaktiv."})

    def mark_as_paid(self, amount=None, send_email=True):
        """Delegiert an PaymentService zur Entkopplung von Persistenz und Seiteneffekten."""
        from .services import PaymentService
        return PaymentService.mark_paid(self, amount=amount, send_email=send_email)

    def mark_as_cancelled(self):
        """Delegiert an PaymentService zur Entkopplung von Persistenz und Seiteneffekten."""
        from .services import PaymentService
        return PaymentService.mark_cancelled(self)

    def save(self, *args, **kwargs):
        """
        Schlanke Persistenzmethode:
        Erzeugt ggf. den kryptografischen short_code mit Kollisionsschutz.
        """
        if not self.short_code:
            code = generate_short_code()
            while EventRegistration.objects.filter(short_code=code).exists():
                code = generate_short_code()
            self.short_code = code

        super().save(*args, **kwargs)

    def send_payment_confirmation_email(self):
        """Sendet die automatische E-Mail-Zahlungsbestätigung an den Gast."""
        try:
            seat = self.seats.first()
            seat_label = seat.seat_label if seat else "Noch kein Sitzplatz"

            context_data = {
                'username': self.user.username,
                'full_name': self.user.get_full_name() or self.user.username,
                'event_title': self.event.title,
                'amount': f"{self.paid_amount:.2f}",
                'payment_reference': f"REG-{self.id}",
                'seat_label': seat_label,
                'ticket_type': self.ticket_type.name if self.ticket_type else "Standard Ticket",
            }
            send_system_email('payment_confirmation', self.user.email, context_data)
        except Exception as e:
            logger.exception("Fehler beim Auslösen der Zahlungsbestätigung für Anmeldung %s: %s", self.id, e)






