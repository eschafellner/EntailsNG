from django.contrib import admin, messages
from django.utils import timezone
from django.utils.safestring import mark_safe
from seating.models import SeatingCell
from .models import Event, EventRegistration, TicketType


class TicketTypeInline(admin.TabularInline):
    model = TicketType
    extra = 1


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
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


@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'event', 'price', 'is_active')
    list_filter = ('event', 'is_active')


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = (
        'user',
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
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    readonly_fields = ('assigned_seat_picker', 'checked_in_at')
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
        """Setzt den Zeitstempel automatisch, wenn im Admin das Häkchen manuell gesetzt wird"""
        if obj.is_checked_in and not obj.checked_in_at:
            obj.checked_in_at = timezone.now()
        elif not obj.is_checked_in:
            obj.checked_in_at = None

        super().save_model(request, obj, form, change)

        for seat in obj.seats.all():
            if obj.payment_status == EventRegistration.PaymentStatus.PAID:
                seat.reservation_status = SeatingCell.ReservationStatus.RESERVED
            else:
                seat.reservation_status = (
                    SeatingCell.ReservationStatus.PRE_RESERVED
                )
            seat.save()

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
        for reg in queryset:
            reg.check_in()
        self.message_user(
            request, f"{queryset.count()} Gäste erfolgreich eingecheckt!"
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
            hasattr(obj.event, "seating_plan") and obj.event.seating_plan
        )

        if not has_plan:
            return f"{seat_text} (Für dieses Event existiert noch kein Sitzplan)"

        delete_button_html = ""
        if current_seat:
            delete_button_html = (
                '<button type="button" class="button" style="background: #dc2626; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer;" onclick="deleteSeatAssignment()">'
                "🗑️ Sitzplatzzuweisung löschen"
                "</button>"
            )

        html = """
        <div style="display: flex; align-items: center; gap: 15px;">
            <strong id="current-seat-display" style="font-size: 14px;">{seat_text}</strong>
            <button type="button" class="button" style="background: #2563eb; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer;" onclick="openSeatModal()">
                🪑 Sitzplatz wählen / ändern
            </button>
            {delete_button_html}
        </div>

        <!-- Modal Popup -->
        <div id="seatModal" style="display: none; position: fixed; z-index: 9999; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); align-items: center; justify-content: center;">
            <div style="background: #1e293b; padding: 25px; border-radius: 12px; color: white; max-width: 90vw; max-height: 85vh; overflow: auto; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <h3 style="margin: 0; color: white;">Sitzplatz auswählen für {username}</h3>
                    <button type="button" onclick="closeSeatModal()" style="background: transparent; border: none; color: #94a3b8; font-size: 20px; cursor: pointer;">✖</button>
                </div>

                <div id="modal-grid-container" style="background: #0f172a; padding: 15px; border-radius: 8px; margin-bottom: 15px;">
                    Lade Sitzplan...
                </div>

                <div style="display: flex; gap: 15px; font-size: 12px; color: #cbd5e1;">
                    <span><strong style="color:#22c55e">■</strong> Frei (Klicken zum Buchen)</span>
                    <span><strong style="color:#f97316">■</strong> Vorgemerkt</span>
                    <span><strong style="color:#ef4444">■</strong> Bezahlt</span>
                    <span><strong style="color:#3b82f6">■</strong> Aktuell gewählt</span>
                </div>
            </div>
        </div>

        <script>
            function openSeatModal() {{
                document.getElementById('seatModal').style.display = 'flex';
                loadModalGrid();
            }}

            function closeSeatModal() {{
                document.getElementById('seatModal').style.display = 'none';
            }}

            function loadModalGrid() {{
                const eventId = {event_id};
                const container = document.getElementById('modal-grid-container');

                fetch(`/seating/api/plan/${{eventId}}/`)
                    .then(res => res.json())
                    .then(data => {{
                        if (data.error) {{
                            container.innerHTML = data.error;
                            return;
                        }}

                        let gridHtml = `<div style="display: grid; grid-template-columns: repeat(${{data.columns}}, 32px); gap: 4px;">`;
                        const cellMap = {{}};
                        data.cells.forEach(c => cellMap[`${{c.x}}_${{c.y}}`] = c);

                        for (let y = 1; y <= data.rows; y++) {{
                            for (let x = 1; x <= data.columns; x++) {{
                                const c = cellMap[`${{x}}_${{y}}`];
                                if (!c) {{
                                    gridHtml += `<div style="width:32px; height:32px; background:#1e293b; border-radius:4px;"></div>`;
                                    continue;
                                }}

                                let bg = "#334155";
                                let cursor = "default";
                                let title = `(${{x}},${{y}})`;
                                let content = "";
                                let isClickable = false;

                                if (c.cell_type === 'WALL') bg = "#64748b";
                                else if (c.cell_type === 'DOOR') bg = "#8b5cf6";
                                else if (c.cell_type === 'LABEL') {{ bg = "#0284c7"; content = c.text_label ? c.text_label.substring(0,2) : "T"; }}
                                else if (c.cell_type === 'SEAT') {{
                                    content = c.seat_label || "S";
                                    title = `${{c.seat_label}} (${{c.status}})`;
                                    isClickable = true;
                                    cursor = "pointer";

                                    if (c.occupied_by === "{username}") {{
                                        bg = "#3b82f6";
                                        title += " - Aktueller Platz dieses Users";
                                    }} else if (c.status === 'RESERVED') bg = "#ef4444";
                                    else if (c.status === 'PRE') bg = "#f97316";
                                    else if (c.status === 'BLOCKED') {{ bg = "#000"; isClickable = false; }}
                                    else bg = "#22c55e";
                                }}

                                const clickAttr = isClickable ? `onclick="selectSeatForUser(${{x}}, ${{y}}, '${{c.seat_label || ''}}')"` : '';
                                gridHtml += `<div ${{clickAttr}} title="${{title}}" style="background: ${{bg}}; width: 32px; height: 32px; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: bold; color: white; cursor: ${{cursor}}; user-select: none;">${{content}}</div>`;
                            }}
                        }}

                        gridHtml += '</div>';
                        container.innerHTML = gridHtml;
                    }});
            }}

            function selectSeatForUser(x, y, label) {{
                if (!confirm(`Möchtest du {username} den Platz "${{label || x + ',' + y}}" zuweisen?`)) return;

                const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

                fetch('/seating/admin/assign-seat/', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    }},
                    body: JSON.stringify({{
                        registration_id: {reg_id},
                        x: x,
                        y: y
                    }})
                }})
                .then(res => res.json())
                .then(data => {{
                    if (data.status === 'success') {{
                        location.reload();
                    }} else {{
                        alert("Fehler: " + data.message);
                    }}
                }});
            }}

            function deleteSeatAssignment() {{
                if (!confirm("Möchtest du die Sitzplatzzuweisung für {username} wirklich löschen? Der Platz wird dadurch wieder freigegeben.")) return;

                const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

                fetch('/seating/admin/release-seat/', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    }},
                    body: JSON.stringify({{
                        registration_id: {reg_id}
                    }})
                }})
                .then(res => res.json())
                .then(data => {{
                    if (data.status === 'success') {{
                        location.reload();
                    }} else {{
                        alert("Fehler: " + data.message);
                    }}
                }});
            }}
        </script>
        """.format(
            seat_text=seat_text,
            delete_button_html=delete_button_html,
            username=obj.user.username,
            event_id=obj.event.id,
            reg_id=obj.pk,
        )
        return mark_safe(html)

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

