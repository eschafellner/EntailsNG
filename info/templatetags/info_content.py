from django import template
from django.utils.safestring import mark_safe

from info.content import sanitize_info_html

register = template.Library()


@register.filter
def info_html(value):
    """Bereinigt Infoseiten-Inhalt beim Anzeigen; hochgeladene Bilder bleiben erhalten."""
    return mark_safe(sanitize_info_html(str(value or '')))
