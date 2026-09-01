# seating/services.py
from django.core.cache import cache
from configuration.cache import invalidate_event_capacity_cache
from .models import SeatingCell, SeatingPlan

CAPACITY_CACHE_KEY_PREFIX = 'event_capacity_stats_'
CACHE_SECONDS = 300


def get_event_capacity_stats(upcoming_event):
    """
    Ermittelt Sitzplatzstatistiken (total, reserved, percent) mit Smart Caching.
    Wird bei jeder Sitzplatz-Statusänderung automatisch invalidiert.
    """
    if not upcoming_event:
        return {'total_seats': 0, 'reserved_seats': 0, 'capacity_percent': 0}

    event_id = getattr(upcoming_event, 'id', upcoming_event)
    cache_key = f"{CAPACITY_CACHE_KEY_PREFIX}{event_id}"
    stats = cache.get(cache_key)
    if stats is None:
        seat_cells = SeatingCell.objects.filter(
            plan__event_id=event_id,
            cell_type=SeatingCell.CellType.SEAT,
        )
        total_seats = seat_cells.count()
        reserved_seats = seat_cells.filter(
            reservation_status__in=[
                SeatingCell.ReservationStatus.PRE_RESERVED,
                SeatingCell.ReservationStatus.RESERVED,
            ]
        ).count()
        capacity_percent = (
            int((reserved_seats / total_seats) * 100) if total_seats > 0 else 0
        )
        stats = {
            'total_seats': total_seats,
            'reserved_seats': reserved_seats,
            'capacity_percent': capacity_percent,
        }
        cache.set(cache_key, stats, CACHE_SECONDS)
    return stats


def get_user_seat_map(event, user_ids):
    """
    Liefert ein Dictionary {user_id: seat_label} für alle angegebenen User auf dem Event-Sitzplan.
    Verhindert N+1-Abfragen für Clan-Listen, Profile und Teilnehmerlisten.
    """
    if not event or not user_ids:
        return {}

    event_id = getattr(event, 'id', event)
    seats = (
        SeatingCell.objects.filter(
            plan__event_id=event_id,
            registration__user_id__in=user_ids,
        )
        .select_related('registration')
        .values('registration__user_id', 'seat_label', 'x', 'y')
    )

    result = {}
    for s in seats:
        uid = s['registration__user_id']
        if uid:
            result[uid] = s['seat_label'] or f"Pos ({s['x']},{s['y']})"
    return result


def sync_seat_status_with_payment(registration):
    """
    Synchronisiert den Reservierungsstatus aller Plätze einer Registrierung
    mit deren Bezahlstatus (PAID -> RESERVED, sonst -> PRE_RESERVED).
    """
    if not registration or not registration.pk:
        return

    is_paid = getattr(registration, 'payment_status', None) == 'PAID'
    new_status = (
        SeatingCell.ReservationStatus.RESERVED
        if is_paid
        else SeatingCell.ReservationStatus.PRE_RESERVED
    )

    for seat in registration.seats.all():
        if seat.reservation_status != new_status:
            seat.reservation_status = new_status
            seat.save(update_fields=['reservation_status'])


def clone_seating_plan(source_plan, target_event, new_name=None):
    """Klont ein bestehendes Raum-Layout für eine neue Veranstaltung."""
    if not source_plan:
        return None
    return source_plan.clone_for_event(new_event=target_event, new_name=new_name)


class SeatingPlanValidationError(Exception):
    """Fehler bei der Validierung von Sitzplan-Rasterdaten."""
    pass


class SeatingPlanService:
    """Zentraler Service für die Validierung und Persistenz von Sitzplan-Rasterdaten."""

    @staticmethod
    def save_grid(plan, cells_data):
        """
        Validiert und speichert ein Zellraster atomar für den angegebenen Sitzplan.
        Schützt belegte Plätze vor Löschung und Typ-Änderung.

        Rückgabe: Tuple (success: bool, message: str) oder wirft SeatingPlanValidationError
        """
        from django.db import transaction

        if not isinstance(cells_data, list):
            raise SeatingPlanValidationError('Ungültiges Datenformat: "cells" muss eine Liste sein.')

        valid_cell_types = set(SeatingCell.CellType.values)
        sent_coords = {}

        for idx, c in enumerate(cells_data):
            if not isinstance(c, dict):
                raise SeatingPlanValidationError(f'Ungültiger Kacheleintrag an Index {idx}.')

            # 1. Koordinaten validieren
            try:
                x = int(c.get('x'))
                y = int(c.get('y'))
            except (ValueError, TypeError):
                raise SeatingPlanValidationError(f'Ungültige Koordinaten an Index {idx}.')

            if not (1 <= x <= plan.columns and 1 <= y <= plan.rows):
                raise SeatingPlanValidationError(
                    f'Koordinaten ({x},{y}) liegen außerhalb des Rasters ({plan.columns}x{plan.rows}).'
                )

            # 2. Zelltyp validieren
            cell_type = c.get('cell_type', SeatingCell.CellType.EMPTY)
            if cell_type not in valid_cell_types:
                raise SeatingPlanValidationError(
                    f'Ungültiger Zelltyp "{cell_type}" an Position ({x},{y}).'
                )

            # 3. Feldlängen validieren
            seat_label = str(c.get('seat_label', '') or '')[:20]
            text_label = str(c.get('text_label', '') or '')[:50]

            sent_coords[(x, y)] = {
                'cell_type': cell_type,
                'seat_label': seat_label,
                'text_label': text_label,
            }

        with transaction.atomic():
            existing_cells = {
                (cell.x, cell.y): cell
                for cell in SeatingCell.objects.filter(plan=plan).select_related('registration__user')
            }

            # 4. Schutz belegter / reservierter Plätze vor Löschung
            coords_to_delete = set(existing_cells.keys()) - set(sent_coords.keys())
            for coord in coords_to_delete:
                cell = existing_cells[coord]
                if cell.registration is not None or cell.reservation_status in [
                    SeatingCell.ReservationStatus.RESERVED,
                    SeatingCell.ReservationStatus.PRE_RESERVED,
                ]:
                    user_name = cell.registration.user.username if cell.registration else "einem Teilnehmer"
                    raise SeatingPlanValidationError(
                        f'Kachel an Position ({coord[0]},{coord[1]}) kann nicht gelöscht werden, da sie aktuell von {user_name} belegt/reserviert ist.'
                    )

            if coords_to_delete:
                pks_to_delete = [existing_cells[coord].pk for coord in coords_to_delete]
                SeatingCell.objects.filter(pk__in=pks_to_delete).delete()

            cells_to_create = []
            cells_to_update = []

            # 5. Bestehende Kacheln updaten oder neue zur Bulk-Erstellung sammeln
            for coord, cdata in sent_coords.items():
                x, y = coord
                cell_type = cdata['cell_type']
                seat_label = cdata['seat_label']
                text_label = cdata['text_label']

                if coord in existing_cells:
                    cell = existing_cells[coord]

                    # Schutz vor destruktiver Typ-Änderung belegter Plätze
                    if cell.registration is not None and cell_type != SeatingCell.CellType.SEAT:
                        user_name = cell.registration.user.username
                        raise SeatingPlanValidationError(
                            f'Sitzplatz ({x},{y}) kann nicht in "{cell_type}" umgewandelt werden, da er von {user_name} belegt ist.'
                        )

                    if (cell.cell_type != cell_type or
                        cell.seat_label != seat_label or
                        cell.text_label != text_label):
                        cell.cell_type = cell_type
                        cell.seat_label = seat_label
                        cell.text_label = text_label
                        cells_to_update.append(cell)
                else:
                    cells_to_create.append(
                        SeatingCell(
                            plan=plan,
                            x=x,
                            y=y,
                            cell_type=cell_type,
                            seat_label=seat_label,
                            text_label=text_label,
                        )
                    )

            if cells_to_create:
                SeatingCell.objects.bulk_create(cells_to_create, batch_size=500)
            if cells_to_update:
                SeatingCell.objects.bulk_update(
                    cells_to_update,
                    fields=['cell_type', 'seat_label', 'text_label'],
                    batch_size=500
                )

            # Einmalige Cache-Invalidierung nach DB-Commit (über transaction.on_commit in invalidate_event_capacity_cache)
            if plan.event_id:
                invalidate_event_capacity_cache(plan.event_id)

        return True, "Sitzplan erfolgreich gespeichert!"

