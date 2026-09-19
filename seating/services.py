# seating/services.py
from django.core.cache import cache
from configuration.cache import invalidate_event_capacity_cache, safe_cache_get_or_set
from .models import SeatingCell, SeatingPlan

CAPACITY_CACHE_KEY_PREFIX = 'event_capacity_stats_'
CACHE_SECONDS = 300


def get_event_capacity_stats(upcoming_event):
    """
    Ermittelt Sitzplatzstatistiken (total, reserved, percent) mit Smart Caching.
    Wird bei jeder Sitzplatz-Statusänderung automatisch invalidiert.
    Fällt bei Redis-Ausfall transparent auf die Datenbank zurück.
    """
    if not upcoming_event:
        return {'total_seats': 0, 'reserved_seats': 0, 'capacity_percent': 0}

    event_id = getattr(upcoming_event, 'id', upcoming_event)
    cache_key = f"{CAPACITY_CACHE_KEY_PREFIX}{event_id}"

    def _calculate():
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
        return {
            'total_seats': total_seats,
            'reserved_seats': reserved_seats,
            'capacity_percent': capacity_percent,
        }

    return safe_cache_get_or_set(cache_key, _calculate, CACHE_SECONDS)


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
    def save_grid(plan, cells_data, expected_version=None):
        """
        Validiert und speichert ein Zellraster atomar für den angegebenen Sitzplan.
        Schützt belegte Plätze vor Löschung und Typ-Änderung.
        Nutzt Zeilensperren (select_for_update) auf Kacheln und Sitzplan sowie
        optionale Plan-Versionierung gegen konkurrierende Layoutänderungen.

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
            raw_res_status = c.get('reservation_status')
            reservation_status = (
                SeatingCell.ReservationStatus.BLOCKED
                if raw_res_status == SeatingCell.ReservationStatus.BLOCKED
                else SeatingCell.ReservationStatus.FREE
            )

            sent_coords[(x, y)] = {
                'cell_type': cell_type,
                'seat_label': seat_label,
                'text_label': text_label,
                'reservation_status': reservation_status,
            }

        with transaction.atomic():
            # 1. Gemeinsame Plansperre für konkurrierende Layoutänderungen
            locked_plan = SeatingPlan.objects.select_for_update().get(pk=plan.pk)

            # 2. Optimistische Versionsprüfung
            if expected_version is not None:
                try:
                    expected_ver_int = int(expected_version)
                    if locked_plan.version != expected_ver_int:
                        raise SeatingPlanValidationError(
                            f'Der Sitzplan wurde zwischenzeitlich von einem anderen Administrator geändert '
                            f'(aktuelle Version {locked_plan.version} vs. gesendete Version {expected_ver_int}). '
                            f'Bitte lade die Seite neu, um die aktuellen Änderungen zu sehen.'
                        )
                except (ValueError, TypeError):
                    raise SeatingPlanValidationError('Ungültige Planversion übermittelt.')

            # 3. Bestehende Kacheln VOR der Belegungsprüfung mit DB-Zeilensperre laden
            existing_cells = {
                (cell.x, cell.y): cell
                for cell in SeatingCell.objects.select_for_update().filter(plan=locked_plan).order_by('id')
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
                res_status = cdata['reservation_status']

                if coord in existing_cells:
                    cell = existing_cells[coord]

                    # Schutz vor destruktiver Typ-Änderung belegter Plätze
                    if cell.registration is not None and cell_type != SeatingCell.CellType.SEAT:
                        user_name = cell.registration.user.username
                        raise SeatingPlanValidationError(
                            f'Sitzplatz ({x},{y}) kann nicht in "{cell_type}" umgewandelt werden, da er von {user_name} belegt ist.'
                        )

                    # Status nur ändern, wenn kein User registriert ist
                    target_res_status = cell.reservation_status
                    if cell.registration is None and cell_type == SeatingCell.CellType.SEAT:
                        target_res_status = res_status

                    if (cell.cell_type != cell_type or
                        cell.seat_label != seat_label or
                        cell.text_label != text_label or
                        cell.reservation_status != target_res_status):
                        cell.cell_type = cell_type
                        cell.seat_label = seat_label
                        cell.text_label = text_label
                        cell.reservation_status = target_res_status
                        cells_to_update.append(cell)
                else:
                    cells_to_create.append(
                        SeatingCell(
                            plan=locked_plan,
                            x=x,
                            y=y,
                            cell_type=cell_type,
                            seat_label=seat_label,
                            text_label=text_label,
                            reservation_status=res_status if cell_type == SeatingCell.CellType.SEAT else SeatingCell.ReservationStatus.FREE,
                        )
                    )

            if cells_to_create:
                SeatingCell.objects.bulk_create(cells_to_create, batch_size=500)
            if cells_to_update:
                SeatingCell.objects.bulk_update(
                    cells_to_update,
                    fields=['cell_type', 'seat_label', 'text_label', 'reservation_status'],
                    batch_size=500
                )

            # 6. Plan-Version inkrementieren
            locked_plan.version += 1
            locked_plan.save(update_fields=['version'])
            plan.version = locked_plan.version

            # Einmalige Cache-Invalidierung nach DB-Commit (über transaction.on_commit in invalidate_event_capacity_cache)
            if locked_plan.event_id:
                invalidate_event_capacity_cache(locked_plan.event_id)

        return True, "Sitzplan erfolgreich gespeichert!"

