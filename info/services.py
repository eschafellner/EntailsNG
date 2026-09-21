# info/services.py
from .models import EventInfo


def get_event_info(user=None):
    """
    Liefert die primäre aktive Inhaltsseite nach Reihenfolge.
    Berücksichtigt für nicht angemeldete Benutzer, ob Seiten loginpflichtig sind.
    """
    qs = EventInfo.objects.filter(is_active=True).order_by('order', 'id')
    if user is not None and not user.is_authenticated:
        qs = qs.filter(login_required=False)
    return qs.first()
