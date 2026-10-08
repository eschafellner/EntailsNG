from django.db.models.signals import post_delete, post_save, pre_delete
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


@receiver([post_save, post_delete], sender='seating.SeatingPlan')
def invalidate_cache_on_plan_change(sender, instance, **kwargs):
    """Invalidiert den Kapazitäts-Cache, wenn ein Sitzplan gespeichert oder gelöscht wird."""
    if instance.event_id:
        invalidate_event_capacity_cache(instance.event_id)


@receiver([post_save, post_delete], sender='seating.SeatingCell')
def invalidate_cache_on_cell_change(sender, instance, **kwargs):
    """Invalidiert den Kapazitäts-Cache bei Änderungen oder Löschungen an einzelnen Sitzplätzen."""
    if instance.plan_id:
        try:
            event_id = instance.plan.event_id
            if event_id:
                invalidate_event_capacity_cache(event_id)
        except Exception:
            pass



@receiver(post_save, sender='seating.SeatingCell')
def record_clan_seat_claim(sender, instance, **kwargs):
    if instance.registration_id:
        from .clan_services import claim_hold
        claim_hold(instance)


@receiver(post_save, sender='events.Event')
def close_clan_holds_with_event(sender, instance, raw=False, **kwargs):
    if raw:
        return
    from django.db import transaction
    from django.utils import timezone
    from events.models import Event
    from .models import ClanSeatAllocation
    from .clan_services import expire_allocation
    if not instance.is_active or instance.effective_status in (Event.Status.FINISHED, Event.Status.CANCELLED):
        with transaction.atomic():
            from .clan_payments import process_payments
            process_payments(event_id=instance.pk)
            for allocation in ClanSeatAllocation.objects.select_for_update().filter(event=instance, expired_at__isnull=True):
                expire_allocation(allocation, timezone.now())
