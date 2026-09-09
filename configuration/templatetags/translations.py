from django import template
from configuration.translations import DEFAULT_TEXTS, _load_translations, get_translation

register = template.Library()


@register.simple_tag
def t(key, default=None, **kwargs):
    """
    Template-Tag zum Abrufen von Übersetzungen und Systemtexten.
    Verwendung:
        {% t "seat_card_title" %}
        {% t "custom_key" "Mein Fallback-Text" %}
    """
    return get_translation(key, default=default, **kwargs)

