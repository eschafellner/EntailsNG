"""Common lock order for tournament writers: Event -> Tournament -> Match/Team."""
from events.models import Event
from tournaments.models import Tournament


def lock_tournament(tournament_id):
    """Call inside transaction.atomic; return fresh tournament and event state."""
    event_id = Tournament.objects.values_list('event_id', flat=True).get(pk=tournament_id)
    event = Event.objects.select_for_update().get(pk=event_id)
    tournament = Tournament.objects.select_for_update().get(pk=tournament_id)
    tournament.event = event
    return tournament


def event_is_closed(tournament):
    return tournament.event.effective_status in (Event.Status.FINISHED, Event.Status.CANCELLED)
