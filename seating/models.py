from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from configuration.cache import invalidate_event_capacity_cache
from emails.services import send_system_email


class SeatingPlan(models.Model):
    """Sitzplan-Raster / Halle für eine Veranstaltung"""

    event = models.OneToOneField(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='seating_plan',  # Singular macht hier jetzt auch mehr Sinn
        null=True,
        blank=True,
        verbose_name="Veranstaltung",
    )
    name = models.CharField(max_length=100, verbose_name="Hallenbezeichnung")

    columns = models.PositiveIntegerField(
        default=20, verbose_name="Spaltenanzahl (X)"
    )
    rows = models.PositiveIntegerField(
        default=15, verbose_name="Zeilenanzahl (Y)"
    )

    location_info = models.TextField(
        blank=True,
        verbose_name="Hallen- & Anfahrts-Infos",
        help_text="Informationen zu Parkplätzen, Strom, Catering etc.",
    )
    is_template = models.BooleanField(
        default=False,
        verbose_name="Ist Vorlage",
        help_text="Kennzeichnet diesen Plan als wiederverwendbare Vorlage ohne feste Event-Zuweisung.",
    )
    version = models.PositiveIntegerField(
        default=1,
        verbose_name="Layout-Version",
        help_text="Inkrementeller Versionszähler für Optimistic Concurrency Control im Editor.",
    )

    class Meta:
        verbose_name = "Sitzplan / Halle"
        verbose_name_plural = "Sitzpläne / Hallen"

    def __str__(self):
        event_title = self.event.title if self.event else "Vorlage"
        return f"{event_title} - {self.name} ({self.columns}x{self.rows})"

    def clean(self):
        super().clean()
        if self.is_template and self.event_id is not None:
            raise ValidationError({
                'event': 'Ein Sitzplan mit zugewiesenem Event kann nicht als Vorlage markiert sein. '
                         'Um einen Plan als Vorlage zu verwenden, darf kein Event ausgewählt sein.'
            })

        if self.pk:
            from .clan_services import live_holds
            old_plan = SeatingPlan.objects.filter(pk=self.pk).first()
            held_cells = self.cells.filter(pk__in=live_holds(old_plan.event_id if old_plan else self.event_id).values('cell_id'))
            if held_cells.filter(models.Q(x__gt=self.columns) | models.Q(y__gt=self.rows)).exists():
                raise ValidationError('Das Raster enthält außerhalb der neuen Größe Clan-Vormerkungen. Bitte zuerst freigeben.')
            if old_plan and old_plan.event_id and self.event_id != old_plan.event_id:
                has_registrations = self.cells.filter(registration__isnull=False).exists() or held_cells.exists()
                if has_registrations:
                    raise ValidationError({
                        'event': (
                            'Dieser Sitzplan enthält bereits Teilnehmer-Reservierungen für eine andere Veranstaltung. '
                            'Um das Layout für ein neues Event zu verwenden, nutze bitte die Funktion '
                            '„Sitzplan klonen“, damit das neue Event mit leeren Sitzplätzen startet.'
                        )
                    })

            # P6: Schutz vor dem Abschneiden belegter Plätze beim Verkleinern des Rasters
            cutoff_seats = self.cells.filter(
                models.Q(x__gt=self.columns) | models.Q(y__gt=self.rows),
                registration__isnull=False
            ).select_related('registration__user')
            if cutoff_seats.exists():
                seat_labels = [c.seat_label or f"Pos ({c.x},{c.y})" for c in cutoff_seats[:5]]
                labels_str = ", ".join(seat_labels)
                total = cutoff_seats.count()
                suffix = f" (und {total - 5} weitere)" if total > 5 else ""
                error_msg = (
                    f"Die Rastergröße kann nicht verkleinert werden, da {total} bereits belegte Plätze "
                    f"außerhalb des neuen Rasters liegen würden: {labels_str}{suffix}. "
                    f"Bitte gib diese Plätze zuerst frei oder wähle eine größere Dimension."
                )
                errors = {}
                if self.cells.filter(x__gt=self.columns, registration__isnull=False).exists():
                    errors['columns'] = error_msg
                if self.cells.filter(y__gt=self.rows, registration__isnull=False).exists():
                    errors['rows'] = error_msg
                raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.event_id is None:
            self.is_template = True
        else:
            self.is_template = False
        super().save(*args, **kwargs)


    def clone_for_event(self, new_event=None, new_name=None):
        """Kopiert diesen Sitzplan ohne User-Reservierungen und optional ohne Event."""
        new_plan = SeatingPlan.objects.create(
            event=new_event,
            name=new_name or f"{self.name} (Vorlage)",
            columns=self.columns,
            rows=self.rows,
            location_info=self.location_info,
        )

        new_cells = []
        for cell in self.cells.all():
            new_status = (
                SeatingCell.ReservationStatus.BLOCKED
                if cell.reservation_status
                == SeatingCell.ReservationStatus.BLOCKED
                else SeatingCell.ReservationStatus.FREE
            )

            new_cells.append(
                SeatingCell(
                    plan=new_plan,
                    x=cell.x,
                    y=cell.y,
                    cell_type=cell.cell_type,
                    seat_label=cell.seat_label,
                    text_label=cell.text_label,
                    reservation_status=new_status,
                )
            )

        SeatingCell.objects.bulk_create(new_cells)
        if new_event:
            invalidate_event_capacity_cache(new_event.id)
        return new_plan



class SeatingCell(models.Model):
    """Eine einzelne Kachel im Raster (Sitzplatz, Wand, Tür, Label)"""

    class CellType(models.TextChoices):
        EMPTY = 'EMPTY', 'Freie Fläche / Gang'
        SEAT = 'SEAT', 'Sitzplatz'
        WALL = 'WALL', 'Wand / Hindernis'
        DOOR = 'DOOR', 'Tür / Notausgang'
        LABEL = 'LABEL', 'Beschriftung / Text'

    class ReservationStatus(models.TextChoices):
        FREE = 'FREE', 'Frei'
        PRE_RESERVED = 'PRE', 'Vorgemerkt (Nicht bezahlt)'
        RESERVED = 'RESERVED', 'Fest reserviert (Bezahlt)'
        BLOCKED = 'BLOCKED', 'Vom Admin gesperrt'

    plan = models.ForeignKey(
        SeatingPlan,
        on_delete=models.CASCADE,
        related_name='cells',
        verbose_name="Sitzplan",
    )

    x = models.PositiveIntegerField(verbose_name="Spalte X")
    y = models.PositiveIntegerField(verbose_name="Zeile Y")

    cell_type = models.CharField(
        max_length=10,
        choices=CellType.choices,
        default=CellType.EMPTY,
        verbose_name="Kachel-Typ",
    )

    seat_label = models.CharField(
        max_length=20, blank=True, verbose_name="Sitzplatz-Bezeichnung"
    )
    text_label = models.CharField(
        max_length=50, blank=True, verbose_name="Beschriftungstext"
    )

    registration = models.ForeignKey(
        'events.EventRegistration',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='seats',
        verbose_name="Zugewiesener Teilnehmer",
    )

    reservation_status = models.CharField(
        max_length=10,
        choices=ReservationStatus.choices,
        default=ReservationStatus.FREE,
        verbose_name="Reservierungs-Status",
    )

    class Meta:
        verbose_name = "Raster-Kachel"
        verbose_name_plural = "Raster-Kacheln"
        constraints = [
            models.UniqueConstraint(
                fields=['plan', 'x', 'y'],
                name='unique_cell_coordinate_per_plan'
            ),
            models.CheckConstraint(
                condition=models.Q(x__gte=1) & models.Q(y__gte=1),
                name='seating_cell_coords_positive',
                violation_error_message="Sitzplatz-Koordinaten müssen positiv (>= 1) sein."
            ),
            models.UniqueConstraint(
                fields=['registration'],
                condition=models.Q(registration__isnull=False),
                name='unique_seat_per_registration',
                violation_error_message="Ein Teilnehmer kann maximal einen Sitzplatz gleichzeitig reservieren."
            ),
        ]

        indexes = [
            models.Index(fields=['plan', 'cell_type', 'reservation_status'], name='seating_plan_type_res_idx'),
            models.Index(fields=['registration'], name='seating_cell_reg_idx'),
        ]

    def clean(self):
        super().clean()
        if self.pk:
            from .clan_services import live_holds, check_clan_access
            if live_holds().filter(cell_id=self.pk).exists():
                old = SeatingCell.objects.get(pk=self.pk)
                if self.plan_id != old.plan_id or self.cell_type != self.CellType.SEAT or self.reservation_status == self.ReservationStatus.BLOCKED:
                    raise ValidationError('Bitte die Clan-Vormerkung vor dieser Änderung ausdrücklich freigeben.')
                if self.registration:
                    allowed, reason = check_clan_access(old, self.registration.user)
                    if not allowed:
                        raise ValidationError({'registration': reason})
        if self.registration and self.plan_id and self.plan and self.plan.event_id:
            if self.registration.event_id != self.plan.event_id:
                raise ValidationError({
                    'registration': (
                        f'Die Registrierung gehört zu Event "{self.registration.event}", '
                        f'der Sitzplan gehört jedoch zu Event "{self.plan.event}".'
                    )
                })



    def __str__(self):
        return f"{self.seat_label or f'({self.x},{self.y})'} - {self.get_reservation_status_display()}"


    def can_reserve_for_user(self, registration):
        """
        Prüft vorab, ob ein Sitzplatz für den angegebenen Benutzer reserviert werden kann,
        ohne den Zustand der Kachel oder bisheriger Sitze zu verändern.
        """
        from events.models import Event, EventRegistration

        if not registration:
            return False, "Keine gültige Anmeldung vorhanden."

        if registration.payment_status == EventRegistration.PaymentStatus.CANCELLED:
            return False, "Deine Anmeldung ist storniert. Bitte melde dich erneut an."

        event = registration.event
        if event and hasattr(event, 'effective_status'):
            if event.effective_status in (Event.Status.CANCELLED, Event.Status.FINISHED, Event.Status.DRAFT):
                return False, "Für diese Veranstaltung können keine Plätze mehr gewählt werden."

        if self.cell_type != self.CellType.SEAT:
            return False, "Dies ist kein gültiger Sitzplatz."

        if self.reservation_status == self.ReservationStatus.BLOCKED:
            return False, "Dieser Platz ist vom Admin gesperrt."

        from .clan_services import check_clan_access
        allowed, reason = check_clan_access(self, registration.user)
        if not allowed:
            return False, reason

        if self.reservation_status == self.ReservationStatus.RESERVED and self.registration != registration:
            return False, "Dieser Platz ist bereits fest reserviert und bezahlt."

        has_paid = (
            getattr(registration, 'payment_status', None) == 'PAID'
        )

        if self.reservation_status == self.ReservationStatus.PRE_RESERVED and self.registration != registration:
            event = getattr(self.plan, 'event', None)
            allow_overwrite = getattr(event, 'allow_unpaid_seat_overwrite', True) if event else True
            if not allow_overwrite:
                return False, "Dieser Platz ist bereits vorgemerkt. Eine Überschreibung ist bei dieser Veranstaltung nicht gestattet."
            if not has_paid:
                return False, "Platz bereits vorgemerkt. Nur zahlende Gäste können ihn überschreiben."

        return True, ""


    def reserve_for_user(self, registration):
        from django.contrib.auth import get_user_model
        from events.models import Event, EventRegistration
        from .clan_services import lock_configuration
        with transaction.atomic():
            lock_configuration()
            get_user_model().objects.select_for_update().get(pk=registration.user_id)
            Event.objects.select_for_update().get(pk=registration.event_id)
            registration = EventRegistration.objects.select_for_update().get(pk=registration.pk)
            locked = SeatingCell.objects.select_for_update().get(pk=self.pk)
            result = locked._reserve_for_user(registration)
            self.registration = locked.registration
            self.reservation_status = locked.reservation_status
            return result

    def _reserve_for_user(self, registration):
        can_res, msg = self.can_reserve_for_user(registration)
        if not can_res:
            return False, msg

        has_paid = (
            getattr(registration, 'payment_status', None) == 'PAID'
        )

        overwritten_registration = None
        if self.registration and self.registration != registration:
            overwritten_registration = self.registration

        self.registration = registration
        if has_paid:
            self.reservation_status = self.ReservationStatus.RESERVED
            msg = "Platz erfolgreich fest reserviert!"
        else:
            self.reservation_status = self.ReservationStatus.PRE_RESERVED
            msg = "Platz erfolgreich vorgemerkt."

        self.save()

        if (
            overwritten_registration
            and overwritten_registration.user
            and overwritten_registration.user.email
        ):
            target_user = overwritten_registration.user
            event = getattr(self.plan, 'event', None)
            event_title = event.title if event else "LAN-Party"
            seat_label = self.seat_label or f"({self.x}, {self.y})"
            context_data = {
                'username': target_user.username,
                'full_name': target_user.get_full_name() or target_user.username,
                'event_title': event_title,
                'seat_label': seat_label,
                'seating_url': '/seating/',
            }
            transaction.on_commit(
                lambda u=target_user, ctx=context_data: send_system_email(
                    'seat_overwritten', u.email, ctx
                )
            )

        return True, msg

    def release_seat(self, registration=None, is_admin=False):
        if is_admin or self.registration == registration:
            self.registration = None
            self.reservation_status = self.ReservationStatus.FREE
            self.save()
            return True, "Freigegeben."
        return False, "Du kannst nur deinen eigenen Sitzplatz freigeben."

    def toggle_admin_block(self, block=True):
        if block:
            self.registration = None
            self.reservation_status = self.ReservationStatus.BLOCKED
        else:
            self.reservation_status = self.ReservationStatus.FREE
        self.save()


class ClanSeatAllocation(models.Model):
    clan = models.ForeignKey('clans.Clan', on_delete=models.CASCADE, related_name='seat_allocations')
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='clan_seat_allocations')
    created_by = models.ForeignKey('users.User', null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now)
    duration = models.CharField(max_length=5)
    expires_at = models.DateTimeField(db_index=True)
    reminder_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['clan', 'event'], name='unique_clan_event_allocation')]


class ClanSeatHold(models.Model):
    class State(models.TextChoices):
        OPEN = 'OPEN', 'Offen'
        CLAIMED = 'CLAIMED', 'Übernommen'
        RELEASED = 'RELEASED', 'Freigegeben'

    allocation = models.ForeignKey(ClanSeatAllocation, on_delete=models.CASCADE, related_name='holds')
    cell = models.ForeignKey(SeatingCell, null=True, on_delete=models.SET_NULL, related_name='clan_holds')
    seat_label = models.CharField(max_length=40)
    state = models.CharField(max_length=8, choices=State.choices, default=State.OPEN)
    protection_active = models.BooleanField(default=True)
    claimed_by = models.ForeignKey('users.User', null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['cell'], condition=models.Q(protection_active=True), name='unique_protected_clan_seat')]
