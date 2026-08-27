from typing import Optional
from .models import Sponsor


def get_active_sponsors():
    """
    Liefert alle aktuell aktiven Sponsoren, sortiert nach Rang (aufsteigend)
    und bei gleichem Rang älterer Eintrag (erstellt_am) zuerst.
    """
    return Sponsor.objects.aktiv().order_by('rang', 'erstellt_am')


def get_random_active_sponsor() -> Optional[Sponsor]:
    """
    Liefert genau einen zufälligen, aktuell aktiven Sponsor für das Startseiten-Modul.
    Gibt None zurück, falls keine aktiven Sponsoren vorhanden sind.
    """
    return Sponsor.objects.aktiv().order_by('?').first()
