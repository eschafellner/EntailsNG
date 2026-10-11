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




@register.filter
def safe_html(value):
    """Sanitize at output too, including content stored before security fixes."""
    from django.utils.safestring import mark_safe
    from configuration.sanitizer import sanitize_html
    return mark_safe(sanitize_html(str(value or '')))
