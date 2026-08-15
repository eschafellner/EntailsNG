from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import SeatingPlan, SeatingCell


class SeatingCellInline(admin.TabularInline):
    model = SeatingCell
    extra = 0
    fields = (
        'x',
        'y',
        'cell_type',
        'seat_label',
        'text_label',
        'reservation_status',
        'registration',
    )


@admin.register(SeatingPlan)
class SeatingPlanAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'plan_type_badge',
        'event',
        'columns',
        'rows',
        'occupied_info',
        'editor_button',
    )
    list_filter = ('event',)
    search_fields = ('name', 'event__title')
    readonly_fields = ('live_occupancy_preview',)
    fields = (
        'event',
        'name',
        'columns',
        'rows',
        'location_info',
        'live_occupancy_preview',
    )
    actions = ['duplicate_seating_plan']

    @admin.display(description="Typ / Status")
    def plan_type_badge(self, obj):
        if obj.event:
            return format_html(
                '<span style="background: #1e3a8a; color: #93c5fd; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">📅 Event-Sitzplan</span>'
            )
        return format_html(
            '<span style="background: #14532d; color: #86efac; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">⭐ Master-Vorlage</span>'
        )

    @admin.display(description="Belegung")
    def occupied_info(self, obj):
        if not obj.pk:
            return "-"
        total_seats = obj.cells.filter(cell_type=SeatingCell.CellType.SEAT).count()
        occupied = obj.cells.filter(cell_type=SeatingCell.CellType.SEAT, registration__isnull=False).count()
        return f"{occupied} / {total_seats} belegt"

    @admin.display(description="Aktionen")
    def editor_button(self, obj):
        if not obj.pk:
            return ""
        url = reverse('seating_editor', args=[obj.pk])
        return format_html(
            '<a class="button" style="background: #2563eb; color: white; padding: 4px 10px; border-radius: 4px; text-decoration: none;" href="{}">🎨 Editor öffnen</a>',
            url,
        )


    @admin.display(
        description="Aktuelle Belegung & Sperrungen (Klicken zum Verwalten)"
    )
    def live_occupancy_preview(self, obj):
        """Generiert ein klickbares CSS-Grid für Admins"""
        if not obj.pk:
            return "Bitte speichere den Sitzplan zuerst."

        cells = {
            (c.x, c.y): c
            for c in obj.cells.select_related('registration__user').all()
        }

        html = [
            '<style>'
            '.seat-preview-container { display: inline-block; background: #0f172a; padding: 15px; border-radius: 8px; }'
            f'.seat-grid {{ display: grid; grid-template-columns: repeat({obj.columns}, 30px); gap: 3px; }}'
            '.preview-cell { width: 30px; height: 30px; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: bold; position: relative; user-select: none; color: white; font-family: monospace; }'
            '.preview-cell .tooltip { visibility: hidden; width: 180px; background-color: #1e293b; color: #f8fafc; text-align: left; border-radius: 6px; padding: 8px; position: absolute; z-index: 100; bottom: 125%; left: 50%; transform: translateX(-50%); opacity: 0; transition: opacity 0.2s; box-shadow: 0 4px 12px rgba(0,0,0,0.5); border: 1px solid #475569; font-family: sans-serif; font-size: 11px; font-weight: normal; pointer-events: none; }'
            '.preview-cell:hover .tooltip { visibility: visible; opacity: 1; }'
            '</style>'
            '<div class="seat-preview-container"><div class="seat-grid">'
        ]

        for y in range(1, obj.rows + 1):
            for x in range(1, obj.columns + 1):
                cell = cells.get((x, y))
                bg_color = "#334155"
                content = ""
                tooltip_html = ""
                click_handler = ""
                cursor = "default"

                if cell:
                    if cell.cell_type == SeatingCell.CellType.WALL:
                        bg_color = "#64748b"
                    elif cell.cell_type == SeatingCell.CellType.DOOR:
                        bg_color = "#8b5cf6"
                    elif cell.cell_type == SeatingCell.CellType.LABEL:
                        bg_color = "#0284c7"
                        content = (
                            cell.text_label[:2] if cell.text_label else "T"
                        )
                    elif cell.cell_type == SeatingCell.CellType.SEAT:
                        content = cell.seat_label or "S"
                        cursor = "pointer"

                        status_info = cell.get_reservation_status_display()
                        user_info = "<i>Niemand</i>"
                        username_clean = ""

                        if cell.registration and cell.registration.user:
                            u = cell.registration.user
                            username_clean = u.username
                            user_info = (
                                f"<b>{u.username}</b> ({u.get_full_name()})"
                            )

                        if cell.registration:
                            click_handler = f'onclick="releaseOccupiedSeat({obj.event.id if obj.event else 0}, {x}, {y}, \'{username_clean}\', \'{cell.seat_label or "P"}\')"'
                        else:
                            click_handler = f'onclick="toggleBlockSeat({obj.event.id if obj.event else 0}, {x}, {y})"'

# Status-Farben inkl. Check-in (Dunkelrot)
                        if (
                            cell.reservation_status
                            == SeatingCell.ReservationStatus.RESERVED
                        ):
                            if (
                                cell.registration
                                and cell.registration.is_checked_in
                            ):
                                bg_color = (
                                    "#991b1b"  # Dunkelrot = Bezahlt + Eingecheckt!
                                )
                            else:
                                bg_color = (
                                    "#ef4444"  # Hellrot = Bezahlt (Noch nicht da)
                                )
                        elif (
                            cell.reservation_status
                            == SeatingCell.ReservationStatus.PRE_RESERVED
                        ):
                            bg_color = "#f97316"  # Orange = Vorgemerkt
                        elif (
                            cell.reservation_status
                            == SeatingCell.ReservationStatus.BLOCKED
                        ):
                            bg_color = "#000000"  # Schwarz = Gesperrt
                        else:
                            bg_color = "#22c55e"  # Grün = Frei

                        action_hint = (
                            "💡 Klicken zum Freigeben"
                            if cell.registration
                            else "💡 Klicken zum Sperren/Freigeben"
                        )

                        tooltip_html = (
                            f'<div class="tooltip">'
                            f'<div><b>Platz:</b> {cell.seat_label or "Unbenannt"}</div>'
                            f'<div><b>Status:</b> {status_info}</div>'
                            f'<div><b>Inhaber:</b> {user_info}</div>'
                            f'<div style="color:#94a3b8; margin-top:4px;">{action_hint}</div>'
                            f'</div>'
                        )

                html.append(
                    f'<div class="preview-cell" {click_handler} style="background: {bg_color}; cursor: {cursor}; border: {"1px solid #ef4444" if bg_color == "#000000" else "none"};">'
                    f'{content}{tooltip_html}</div>'
                )

        html.append('</div></div>')

        js_code = """
        <script>
            function toggleBlockSeat(eventId, x, y) {
                if (!eventId) {
                    alert("Diesem Sitzplan ist noch keine Veranstaltung zugewiesen.");
                    return;
                }

                const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

                fetch('/seating/admin/toggle-block-seat/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify({ event_id: eventId, x: x, y: y })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'success') {
                        location.reload();
                    } else {
                        alert("Fehler: " + data.message);
                    }
                });
            }

            function releaseOccupiedSeat(eventId, x, y, username, seatLabel) {
                if (!confirm(`Möchtest du den Platz "${seatLabel}" von User "${username}" wirklich freigeben?`)) {
                    return;
                }

                const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

                fetch('/seating/admin/release-seat/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify({ event_id: eventId, x: x, y: y })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'success') {
                        location.reload();
                    } else {
                        alert("Fehler: " + data.message);
                    }
                });
            }
        </script>
        """

        legend = """
        <div style="margin-top: 10px; font-size: 12px; display: flex; gap: 15px; flex-wrap: wrap;">
            <span><strong style="color:#22c55e">■</strong> Frei</span>
            <span><strong style="color:#f97316">■</strong> Vorgemerkt</span>
            <span><strong style="color:#ef4444">■</strong> Bezahlt (Noch nicht da)</span>
            <span><strong style="color:#991b1b">■</strong> Eingecheckt (Vor Ort)</span>
            <span><strong style="color:#000000; background:#000; border:1px solid #ef4444; padding:0 2px;">■</strong> Gesperrt</span>
            <span><strong style="color:#64748b">■</strong> Wand</span>
        </div>
        """
        return mark_safe("".join(html) + js_code + legend)

    @admin.action(
        description="Ausgewählte Sitzpläne klonen (ohne Event-Zuordnung)"
    )
    def duplicate_seating_plan(self, request, queryset):
        for plan in queryset:
            plan.clone_for_event(
                new_event=None, new_name=f"{plan.name} (Kopie / Vorlage)"
            )
        self.message_user(
            request,
            "Sitzplan erfolgreich geklont! Er hat keine Event-Zuordnung und kann neu zugewiesen werden.",
        )


@admin.register(SeatingCell)
class SeatingCellAdmin(admin.ModelAdmin):
    list_display = (
        'plan',
        'x',
        'y',
        'cell_type',
        'seat_label',
        'reservation_status',
        'registration',
    )
    list_filter = ('plan__event', 'cell_type', 'reservation_status')
    search_fields = (
        'seat_label',
        'text_label',
        'registration__user__username',
    )
