from django import template
from configuration.context_processors import DEFAULT_TEXTS, _load_translations

register = template.Library()


@register.simple_tag
def t(key, default=None):
    """
    Template-Tag zum Abrufen von Übersetzungen und Systemtexten.
    Verwendung:
        {% t "seat_card_title" %}
        {% t "custom_key" "Mein Fallback-Text" %}
    """
    if not key:
        return ""

    try:
        texts = _load_translations()
        if key in texts and texts[key]:
            return texts[key]
    except Exception:
        pass

    if default is not None:
        return default

    return DEFAULT_TEXTS.get(key, key)
