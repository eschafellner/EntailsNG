from django import template
from configuration.translations import DEFAULT_TEXTS, _load_translations, get_translation

register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, key, default=None, **kwargs):
    """
    Template-Tag zum Abrufen von Übersetzungen und Systemtexten.
    Verwendung:
        {% t "seat_card_title" %}
        {% t "custom_key" "Mein Fallback-Text" %}
    """
    request = context.get('request') if hasattr(context, 'get') else getattr(context, 'request', None)
    return get_translation(key, default=default, request=request, **kwargs)


