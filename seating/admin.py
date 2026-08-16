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
    list_filter = ('is_template', 'event')
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

        from django.template.loader import render_to_string

        cells = {
            (c.x, c.y): c
            for c in obj.cells.select_related('registration__user').all()
        }

        grid_rows = []
        event_id = obj.event.id if obj.event else 0

        for y in range(1, obj.rows + 1):
            row = []
            for x in range(1, obj.columns + 1):
                cell = cells.get((x, y))
                bg_color = "#334155"
                content = ""
                tooltip = None
                click_handler = ""
                cursor = "default"
                is_blocked = False

                if cell:
                    if cell.cell_type == SeatingCell.CellType.WALL:
                        bg_color = "#64748b"
                    elif cell.cell_type == SeatingCell.CellType.DOOR:
                        bg_color = "#8b5cf6"
                    elif cell.cell_type == SeatingCell.CellType.LABEL:
                        bg_color = "#0284c7"
                        content = cell.text_label[:2] if cell.text_label else "T"
                    elif cell.cell_type == SeatingCell.CellType.SEAT:
                        content = cell.seat_label or "S"
                        cursor = "pointer"
                        status_info = cell.get_reservation_status_display()
                        user_info = "<i>Niemand</i>"
                        username_clean = ""

                        if cell.registration and cell.registration.user:
                            u = cell.registration.user
                            username_clean = u.username
                            user_info = f"<b>{u.username}</b> ({u.get_full_name()})"

                        if cell.registration:
                            click_handler = f'onclick="releaseOccupiedSeat({event_id}, {x}, {y}, \'{username_clean}\', \'{cell.seat_label or "P"}\')"'
                        else:
                            click_handler = f'onclick="toggleBlockSeat({event_id}, {x}, {y})"'

                        if cell.reservation_status == SeatingCell.ReservationStatus.RESERVED:
                            if cell.registration and cell.registration.is_checked_in:
                                bg_color = "#991b1b"
                            else:
                                bg_color = "#ef4444"
                        elif cell.reservation_status == SeatingCell.ReservationStatus.PRE_RESERVED:
                            bg_color = "#f97316"
                        elif cell.reservation_status == SeatingCell.ReservationStatus.BLOCKED:
                            bg_color = "#000000"
                            is_blocked = True
                        else:
                            bg_color = "#22c55e"

                        action_hint = "💡 Klicken zum Freigeben" if cell.registration else "💡 Klicken zum Sperren/Freigeben"
                        tooltip = {
                            'seat_label': cell.seat_label or "Unbenannt",
                            'status_info': status_info,
                            'user_info': user_info,
                            'action_hint': action_hint,
                        }

                row.append({
                    'bg_color': bg_color,
                    'cursor': cursor,
                    'content': content,
                    'click_handler': click_handler,
                    'tooltip': tooltip,
                    'is_blocked': is_blocked,
                })
            grid_rows.append(row)

        context = {
            'plan': obj,
            'grid_rows': grid_rows,
        }
        return mark_safe(render_to_string('admin/seating/live_preview.html', context))


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
