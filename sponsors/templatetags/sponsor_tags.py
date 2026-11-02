from django import template

from configuration.models import GeneralConfiguration
from sponsors.services import get_random_active_sponsor

register = template.Library()


@register.simple_tag
def subpage_sponsor():
    """Liefert einen zufälligen aktiven Sponsor für Unterseiten (Gästeliste, Teams, Sitzplan).

    Gibt None zurück, wenn der Schalter „Sponsor auf Unterseiten anzeigen“ in der
    Allgemeinen Konfiguration aus ist oder kein Sponsor aktiv ist.

    Verwendung:
        {% load sponsor_tags %}
        {% subpage_sponsor as page_sponsor %}
        {% include 'sponsors/includes/sponsor_banner.html' with sponsor=page_sponsor %}
    """
    if not GeneralConfiguration.load().subpage_sponsor_enabled:
        return None
    return get_random_active_sponsor()
