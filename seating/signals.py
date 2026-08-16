from django.db.models.signals import pre_delete
from django.dispatch import receiver


@receiver(pre_delete, sender='events.EventRegistration')
def release_seats_on_registration_delete(sender, instance, **kwargs):
    """Gibt alle verknüpften Sitzplätze frei, wenn eine EventRegistration gelöscht wird."""
    from .models import SeatingCell
    from .services import invalidate_event_capacity_cache

    SeatingCell.objects.filter(registration=instance).update(
        registration=None,
        reservation_status=SeatingCell.ReservationStatus.FREE,
    )
    if instance.event_id:
        invalidate_event_capacity_cache(instance.event_id)
