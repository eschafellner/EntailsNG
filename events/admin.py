from django import forms
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.safestring import mark_safe
from seating.models import SeatingCell, SeatingPlan
from .models import Event, EventRegistration, TicketType


class EventAdminForm(forms.ModelForm):
    clone_seating_from = forms.ModelChoiceField(
        queryset=SeatingPlan.objects.all(),
        required=False,
        label="📋 Sitzplan-Layout übernehmen von",
        help_text=(
            "Optional: Wähle eine bestehende Vorlage oder den Sitzplan eines vergangenen Events. "
            "Das Raumlayout (Wände, Türen, Tische, Sitzplatznummern) wird automatisch mit leeren/freien Plätzen "
            "für dieses Event kopiert."
        ),
    )

    class Meta:
        model = Event
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and hasattr(self.instance, 'seating_plan') and self.instance.seating_plan:
            self.fields['clone_seating_from'].help_text = (
                f"ℹ️ Dieses Event hat bereits einen Sitzplan ('{self.instance.seating_plan.name}'). "
                f"Eine neue Auswahl hier ersetzt den aktuellen Plan durch eine frische Kopie des gewählten Layouts."
            )


class TicketTypeInline(admin.TabularInline):
    model = TicketType
    extra = 1


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    form = EventAdminForm
    list_display = (
        'title',
        'start_date',
        'end_date',
        'location',
        'max_guests',
        'registered_count',
        'is_active',
    )
    list_filter = ('is_active', 'start_date')
    search_fields = ('title', 'location')
    inlines = [TicketTypeInline]

    @admin.display(description="Ang. Teilnehmer")
    def registered_count(self, obj):
        return obj.registrations.count()

    def changelist_view(self, request, extra_context=None):
        _check_overbooking(request)
        return super().changelist_view(request, extra_context=extra_context)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        source_plan = form.cleaned_data.get('clone_seating_from')
        if source_plan:
            if hasattr(obj, 'seating_plan') and obj.seating_plan:
                obj.seating_plan.delete()
            cloned = source_plan.clone_for_event(
                new_event=obj,
                new_name=f"{source_plan.name} ({obj.title})"
            )
            messages.success(
                request,
                f"🎉 Sitzplan-Layout '{source_plan.name}' wurde erfolgreich mit {cloned.cells.count()} leeren Kacheln für '{obj.title}' eingerichtet!"
            )



@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'event', 'price', 'is_active')
    list_filter = ('event', 'is_active')


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'short_code',
        'event',
        'ticket_type',
        'payment_status_badge',
        'check_in_badge',  # <-- NEU: Badge für Check-in
        'assigned_seat',
        'created_at',
    )
    list_filter = (
        'event',
        'is_checked_in',
        'payment_status',
        'ticket_type',
    )  # <-- NEU: Filter nach Check-in
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'short_code')
    readonly_fields = ('short_code', 'checkin_token', 'assigned_seat_picker', 'checked_in_at', 'paid_at', 'cancelled_at')
    actions = ['action_check_in_guests', 'action_check_out_guests', 'export_as_csv']


    @admin.action(description="📊 CSV-Export für Kasse / Einlass (Excel-kompatibel)")
    def export_as_csv(self, request, queryset):
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="teilnehmerliste.csv"'
        response.write('\ufeff'.encode('utf-8'))

        writer = csv.writer(response, delimiter=';')
        writer.writerow([
            'Username',
            'Ticket-Code',
            'Vorname',
            'Nachname',
            'E-Mail',
            'Veranstaltung',
            'Ticket',
            'Bezahlstatus',
            'Sitzplatz',
            'Eingecheckt',
            'Check-in Zeit',
            'Angemeldet am',
        ])

        for reg in queryset.select_related('user', 'event', 'ticket_type').prefetch_related('seats'):
            seat = reg.seats.first()
            seat_label = (
                seat.seat_label or f'Pos ({seat.x},{seat.y})'
                if seat
                else 'Kein Platz'
            )
            checked_in_time = (
                reg.checked_in_at.strftime('%Y-%m-%d %H:%M:%S')
                if reg.checked_in_at
                else ''
            )

            writer.writerow([
                reg.user.username,
                reg.short_code,
                reg.user.first_name,
                reg.user.last_name,
                reg.user.email,
                reg.event.title,
                reg.ticket_type.name if reg.ticket_type else 'Standard',
                reg.get_payment_status_display(),
                seat_label,
                'Ja' if reg.is_checked_in else 'Nein',
                checked_in_time,
                reg.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            ])

        return response

    def save_model(self, request, obj, form, change):
        """Setzt den Zeitstempel automatisch, wenn im Admin das Häkchen manuell gesetzt wird, und prüft den Bezahlstatus."""
        if obj.is_checked_in and obj.payment_status != EventRegistration.PaymentStatus.PAID:
            messages.error(
                request,
                f"Check-in für '{obj.user.username}' verweigert: Die Anmeldung ist nicht bezahlt (Status: {obj.get_payment_status_display()})."
            )
            obj.is_checked_in = False
            obj.checked_in_at = None
        elif obj.is_checked_in and not obj.checked_in_at:
            obj.checked_in_at = timezone.now()
        elif not obj.is_checked_in:
            obj.checked_in_at = None

        super().save_model(request, obj, form, change)

        from seating.services import sync_seat_status_with_payment
        sync_seat_status_with_payment(obj)


    @admin.display(description="Einlass-Status", ordering="is_checked_in")
    def check_in_badge(self, obj):
        """Rendert ein Badge für den Check-in Status"""
        if obj.is_checked_in:
            time_str = (
                obj.checked_in_at.strftime("%H:%M")
                if obj.checked_in_at
                else ""
            )
            return mark_safe(
                f'<span style="background-color: #dbeafe; color: #1e40af; padding: 3px 8px; border-radius: 12px; font-weight: bold; font-size: 12px; display: inline-flex; align-items: center; gap: 4px;">'
                f'🎧 Eingecheckt {f"({time_str})" if time_str else ""}</span>'
            )
        else:
            return mark_safe(
                '<span style="background-color: #f3f4f6; color: #6b7280; padding: 3px 8px; border-radius: 12px; font-weight: bold; font-size: 12px;">'
                '⏳ Ausstehend</span>'
            )

    @admin.action(description="🎧 Ausgewählte Gäste EINCHECKENT")
    def action_check_in_guests(self, request, queryset):
        from django.core.exceptions import ValidationError
        success_count = 0
        failed_users = []

        for reg in queryset:
            try:
                reg.check_in(actor=request.user)
                success_count += 1
            except ValidationError:
                failed_users.append(reg.user.username)

        if success_count > 0:
            self.message_user(
                request, f"{success_count} Gäste erfolgreich eingecheckt!", level=messages.SUCCESS
            )
        if failed_users:
            self.message_user(
                request,
                f"Check-in für folgende {len(failed_users)} Gast/Gäste verweigert (nicht bezahlt): {', '.join(failed_users)}.",
                level=messages.ERROR
            )

    @admin.action(description="⏳ Ausgewählten Check-in RÜCKGÄNGIG machen")
    def action_check_out_guests(self, request, queryset):
        for reg in queryset:
            reg.check_out()
        self.message_user(
            request,
            f"Check-in für {queryset.count()} Gäste wieder aufgehoben.",
        )


    @admin.display(description="Sitzplatz")
    def assigned_seat(self, obj):
        seat = obj.seats.first()
        if seat:
            return f"🪑 {seat.seat_label or f'Pos ({seat.x},{seat.y})'}"
        return "Kein Platz"

    @admin.display(description="Sitzplatz-Zuweisung")
    def assigned_seat_picker(self, obj):
        """Rendert den aktuellen Platz + Buttons für Auswahl & Löschen"""
        if not obj.pk:
            return "Bitte speichere die Anmeldung zuerst ab."

        current_seat = obj.seats.first()
        seat_text = (
            f"🪑 {current_seat.seat_label or f'Pos ({current_seat.x},{current_seat.y})'}"
            if current_seat
            else "Kein Sitzplatz zugewiesen"
        )

        has_plan = (
            hasattr(obj.event, "seating_plan") and bool(obj.event.seating_plan)
        )

        if not has_plan:
            return f"{seat_text} (Für dieses Event existiert noch kein Sitzplan)"

        from django.template.loader import render_to_string
        context = {
            'obj': obj,
            'current_seat': current_seat,
            'seat_text': seat_text,
            'has_plan': has_plan,
            'event_id': obj.event.id if obj.event else None,
        }
        return mark_safe(render_to_string('admin/events/assigned_seat_picker.html', context))


    @admin.display(description="Bezahlstatus", ordering="payment_status")
    def payment_status_badge(self, obj):
        if obj.payment_status == EventRegistration.PaymentStatus.PAID:
            return mark_safe(
                '<span style="background-color: #dcfce7; color: #166534; padding: 3px 8px; border-radius: 12px; font-weight: bold; font-size: 12px; display: inline-flex; align-items: center; gap: 4px;">'
                '✔ Bezahlt</span>'
            )
        elif obj.payment_status == EventRegistration.PaymentStatus.UNPAID:
            return mark_safe(
                '<span style="background-color: #fee2e2; color: #991b1b; padding: 3px 8px; border-radius: 12px; font-weight: bold; font-size: 12px; display: inline-flex; align-items: center; gap: 4px;">'
                '✖ Offen</span>'
            )
        else:
            return mark_safe(
                f'<span style="background-color: #f3f4f6; color: #374151; padding: 3px 8px; border-radius: 12px; font-weight: bold; font-size: 12px;">'
                f'{obj.get_payment_status_display()}</span>'
            )


def _check_overbooking(request):
    overbooked_events = []
    for event in Event.objects.filter(is_active=True):
        if event.effective_status in [Event.Status.FINISHED, Event.Status.CANCELLED]:
            continue
        if event.max_guests and event.registrations.count() > event.max_guests:
            overbooked_events.append(
                f"'{event.title}' ({event.registrations.count()}/{event.max_guests} Plätze)"
            )

    if overbooked_events:
        messages.warning(
            request,
            f"⚠️ Achtung! Es wurden mehr Plätze gebucht als Kapazität vorhanden: "
            f"{', '.join(overbooked_events)}. Bitte prüfen!",
        )

