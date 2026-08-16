from django.db.models.signals import pre_delete
from django.dispatch import receiver
from configuration.cache import invalidate_event_capacity_cache


@receiver(pre_delete, sender='events.EventRegistration')
def release_seats_on_registration_delete(sender, instance, **kwargs):
    """
    Gibt alle verknüpften Sitzplätze frei, wenn eine EventRegistration gelöscht wird.
    Hinweis: on_delete=models.SET_NULL auf dem ForeignKey setzt lediglich 'registration' auf None.
    Dieser Receiver ist zwingend erforderlich, um auch den fachlichen Status 'reservation_status'
    wieder auf FREE zurückzusetzen und den Kapazitäts-Cache des Events zu invalidieren.
    """
    from .models import SeatingCell

    SeatingCell.objects.filter(registration=instance).update(
        registration=None,
        reservation_status=SeatingCell.ReservationStatus.FREE,
    )
    if instance.event_id:
        invalidate_event_capacity_cache(instance.event_id)
