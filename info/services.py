# info/services.py
from .models import EventInfo


def get_event_info():
    """Liefert die allgemeinen Veranstaltungsinformationen."""
    return EventInfo.objects.first()
