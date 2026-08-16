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
