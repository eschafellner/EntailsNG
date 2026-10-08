from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.safestring import mark_safe
from configuration.cache import invalidate_active_event_cache
from configuration.translations import get_translation
from seating.models import SeatingCell, SeatingPlan
from .models import Event, EventRegistration, TicketType
from .exceptions import EventFullError, EventLifecycleError
from .services import EventLifecycleService


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
    clone_tickets_from = forms.ModelChoiceField(
        queryset=Event.objects.all(),
        required=False,
        label="🎟️ Ticket-Kategorien übernehmen von",
        help_text="Optional: Kopiert alle Ticket-Kategorien (Namen, Preise, Hinweise) eines anderen Events für dieses Event.",
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
        if self.instance and self.instance.pk and self.instance.ticket_types.exists():
            count = self.instance.ticket_types.count()
            self.fields['clone_tickets_from'].help_text = (
                f"ℹ️ Dieses Event hat bereits {count} Ticket-Kategorie(n). "
                f"Eine Auswahl hier kopiert zusätzliche Ticketkategorien aus dem gewählten Event hinzu."
            )
        if 'allow_unpaid_seat_overwrite' in self.fields:
            self.fields['allow_unpaid_seat_overwrite'].required = False

    def clean_allow_unpaid_seat_overwrite(self):
        val = self.cleaned_data.get('allow_unpaid_seat_overwrite')
        if val is None or val == '':
            if self.instance and self.instance.pk and self.instance.allow_unpaid_seat_overwrite is not None:
                return self.instance.allow_unpaid_seat_overwrite
            return True
        return val

    def clean_status(self):
        status = self.cleaned_data['status']
        old_status = (
            Event.objects.filter(pk=self.instance.pk).values_list('status', flat=True).first()
            if self.instance.pk else None
        )
        if status == Event.Status.REGISTRATION_OPEN and old_status != Event.Status.REGISTRATION_OPEN:
            raise forms.ValidationError(get_translation(
                'msg_event_open_use_action',
                'Bitte öffne die Anmeldung über die Aktion „Anmeldung öffnen“ in der Eventliste.',
            ))
        if status == Event.Status.FINISHED:
            if old_status != Event.Status.FINISHED:
                raise forms.ValidationError(get_translation(
                    'msg_event_finish_use_action',
                    'Bitte schließe die Veranstaltung über die Aktion „Veranstaltung abschließen“ in der Eventliste ab.',
                ))
        elif old_status == Event.Status.FINISHED:
            raise forms.ValidationError(get_translation(
                'msg_event_finish_no_reopen',
                'Eine abgeschlossene Veranstaltung kann nicht über dieses Formular wieder geöffnet werden.',
            ))
        return status

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('status') == Event.Status.FINISHED and cleaned_data.get('is_active'):
            self.add_error('is_active', get_translation(
                'msg_event_finish_no_reactivate',
                'Eine abgeschlossene Veranstaltung kann nicht als aktive Hauptveranstaltung gesetzt werden.',
            ))
        return cleaned_data


class TicketTypeInline(admin.TabularInline):
    model = TicketType
    extra = 1


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    form = EventAdminForm
    list_display = (
        'title',
        'status',
        'start_date',
        'end_date',
        'location',
        'max_guests',
        'registered_count',
        'last_payment_check',
        'is_active',
    )
    list_filter = ('status', 'is_active', 'start_date')
    search_fields = ('title', 'location')
    inlines = [TicketTypeInline]
    actions = ['action_open_registration', 'action_set_payment_check_now', 'action_finish_event']

    @admin.action(description="📋 Bereitschaft prüfen und Anmeldung öffnen", permissions=['change'])
    def action_open_registration(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                get_translation('msg_event_open_select_one', 'Bitte wähle genau eine Veranstaltung aus.'),
                level=messages.ERROR,
            )
            return None

        event = queryset.get()
        if request.POST.get('confirm_open'):
            try:
                EventLifecycleService.open_registration(event.pk)
            except EventLifecycleError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
                event.refresh_from_db()
            else:
                self.message_user(
                    request,
                    get_translation('msg_event_open_success', 'Anmeldung für „{event_title}“ geöffnet.', event_title=event.title),
                    level=messages.SUCCESS,
                )
                return None

        report = EventLifecycleService.registration_readiness(event)
        return TemplateResponse(request, 'admin/events/open_registration.html', {
            **self.admin_site.each_context(request),
            'title': get_translation('event_open_title', 'Bereitschaftsprüfung vor Anmeldestart'),
            'event': event,
            'report': report,
            'opts': self.model._meta,
        })

    @admin.action(description="🏁 Veranstaltung abschließen", permissions=['change'])
    def action_finish_event(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                get_translation('msg_event_finish_select_one', 'Bitte wähle genau eine Veranstaltung aus.'),
                level=messages.ERROR,
            )
            return None

        event = queryset.get()
        if not request.POST.get('confirm_finish'):
            if event.status in (Event.Status.DRAFT, Event.Status.CANCELLED):
                self.message_user(
                    request,
                    get_translation(
                        'msg_event_finish_invalid_status',
                        'Entwürfe und abgesagte Veranstaltungen können nicht abgeschlossen werden.',
                    ),
                    level=messages.ERROR,
                )
                return None
            from tournaments.models import Tournament
            open_tournaments = event.tournaments.exclude(
                status__in=[Tournament.Status.FINISHED, Tournament.Status.CANCELLED]
            ).order_by('title')
            return TemplateResponse(request, 'admin/events/finish_event.html', {
                **self.admin_site.each_context(request),
                'title': get_translation('event_finish_title', 'Veranstaltung abschließen'),
                'event': event,
                'open_tournaments': open_tournaments,
                'opts': self.model._meta,
            })

        try:
            _, archived_count = EventLifecycleService.finish_event(event.pk)
        except EventLifecycleError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
        else:
            self.message_user(
                request,
                get_translation(
                    'msg_event_finish_success',
                    'Veranstaltung „{event_title}“ abgeschlossen. {count} Teams archiviert.',
                    event_title=event.title,
                    count=archived_count,
                ),
                level=messages.SUCCESS,
            )
        return None

    @admin.action(description="🏦 Letzten Kontocheck für ausgewählte Events auf JETZT setzen")
    def action_set_payment_check_now(self, request, queryset):
        now = timezone.now()
        updated = queryset.update(last_payment_check=now)
        invalidate_active_event_cache()
        self.message_user(
            request,
            f"Zeitpunkt des letzten Kontochecks für {updated} Event(s) auf {now.strftime('%d.%m.%Y, %H:%M Uhr')} gesetzt.",
            level=messages.SUCCESS,
        )

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

        source_ticket_event = form.cleaned_data.get('clone_tickets_from')
        if source_ticket_event:
            copied_count = 0
            for tt in source_ticket_event.ticket_types.all():
                TicketType.objects.create(
                    event=obj,
                    name=tt.name,
                    price=tt.price,
                    description=tt.description,
                    is_active=tt.is_active,
                )
                copied_count += 1
            if copied_count > 0:
                messages.success(
                    request,
                    f"🎟️ {copied_count} Ticket-Kategorie(n) von '{source_ticket_event.title}' erfolgreich für '{obj.title}' übernommen!"
                )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        # Inlines sind erst jetzt gespeichert. Ein Standardticket nur ohne Kategorien anlegen.
        if not obj.ticket_types.exists():
            TicketType.objects.create(
                event=obj,
                name="Standard",
                price=obj.price,
                description="",
                is_active=True,
            )



@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'event', 'price', 'is_active')
    list_filter = ('event', 'is_active')


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        from seating.models import ClanSeatHold
        if obj and ClanSeatHold.objects.filter(funded_registration=obj).exists():
            return tuple(dict.fromkeys((*fields, 'user', 'event', 'ticket_type', 'booking_price', 'payment_status', 'paid_amount')))
        return fields

    def has_delete_permission(self, request, obj=None):
        from seating.models import ClanSeatHold
        if obj and ClanSeatHold.objects.filter(funded_registration=obj).exists():
            return False
        return super().has_delete_permission(request, obj)

    list_display = (
        'user',
        'short_code',
        'event',
        'ticket_type',
        'booking_price',
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
    actions = ['action_mark_as_paid', 'action_check_in_guests', 'action_check_out_guests', 'export_as_csv']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('clan_funding__payment')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "ticket_type":
            object_id = request.resolver_match.kwargs.get('object_id') if request.resolver_match else None
            if object_id:
                try:
                    reg = self.get_object(request, object_id)
                    if reg and reg.event:
                        kwargs["queryset"] = TicketType.objects.filter(event=reg.event)
                except Exception:
                    pass
            else:
                active = Event.objects.get_active()
                if active:
                    kwargs["queryset"] = TicketType.objects.filter(event=active)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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
            'Clan-Zahlungsreferenz (zugeordneter Ticketanteil)',
        ])

        for reg in queryset.select_related('user', 'event', 'ticket_type', 'clan_funding__payment').prefetch_related('seats'):
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
                reg.clan_funding.payment.reference if hasattr(reg, 'clan_funding') else '',
            ])

        return response

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        """Prüft Orga-Sperren, Check-in und Zahlungsstatus unter derselben Usersperre."""
        from django.contrib.auth import get_user_model
        owner = get_user_model().objects.select_for_update(no_key=True).get(pk=obj.user_id)
        if owner.is_banned and obj.is_checked_in:
            messages.error(request, get_translation('ban_checkin_failed'))
            obj.is_checked_in = False
            obj.checked_in_at = None
        became_paid = (
            obj.payment_status == EventRegistration.PaymentStatus.PAID
            and (not change or 'payment_status' in form.changed_data)
        )
        became_cancelled = (
            obj.payment_status == EventRegistration.PaymentStatus.CANCELLED
            and (not change or 'payment_status' in form.changed_data)
        )

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

        # Immer zuerst speichern, damit neue Objekte (change=False) eine Primärschlüssel-ID (pk) erhalten
        super().save_model(request, obj, form, change)

        if became_paid:
            try:
                obj.mark_as_paid(amount=obj.paid_amount or None, send_email=True)
                self.message_user(
                    request,
                    f"Zahlungsbestätigung für '{obj.user.username}' wurde erfolgreich verbucht und per E-Mail versendet.",
                    level=messages.SUCCESS,
                )
            except EventFullError as e:
                self.message_user(request, str(e), level=messages.ERROR)
        elif became_cancelled:
            obj.mark_as_cancelled()
        else:
            from seating.services import sync_seat_status_with_payment
            sync_seat_status_with_payment(obj)

    @admin.action(description="💶 Ausgewählte Anmeldungen als BEZAHLT markieren (inkl. E-Mail)")
    def action_mark_as_paid(self, request, queryset):
        success_count = 0
        skipped_count = 0
        for reg in queryset:
            if reg.payment_status != EventRegistration.PaymentStatus.PAID:
                try:
                    reg.mark_as_paid(send_email=True)
                    success_count += 1
                except EventFullError as e:
                    skipped_count += 1
                    self.message_user(request, str(e), level=messages.ERROR)
        if success_count > 0:
            self.message_user(
                request,
                f"{success_count} Anmeldung(en) erfolgreich als bezahlt markiert und Zahlungsbestätigung per E-Mail versendet.",
                level=messages.SUCCESS,
            )
        elif skipped_count == 0:
            self.message_user(
                request,
                "Alle ausgewählten Anmeldungen waren bereits als bezahlt markiert.",
                level=messages.INFO,
            )


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
                reg.check_in()
                success_count += 1
            except ValidationError as exc:
                failed_users.append(f'{reg.user.username}: {"; ".join(exc.messages)}')

        if success_count > 0:
            self.message_user(
                request, f"{success_count} Gäste erfolgreich eingecheckt!", level=messages.SUCCESS
            )
        if failed_users:
            self.message_user(
                request,
                f"Check-in für folgende {len(failed_users)} Gast/Gäste verweigert: {', '.join(failed_users)}.",
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
