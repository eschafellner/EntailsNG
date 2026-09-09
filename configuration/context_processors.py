from django.core.cache import cache
from django.utils.functional import SimpleLazyObject

from configuration.models import NavigationItem, SiteCustomization
from events.models import Event, EventRegistration
from seating.services import (
    get_event_capacity_stats,
    invalidate_event_capacity_cache,
    CAPACITY_CACHE_KEY_PREFIX,
)  # Re-Export für Rückwärtskompatibilität
from .translations import (
    DEFAULT_TEXTS,
    TRANSLATION_CACHE_KEY,
    _load_translations,
    get_translation,
)

FEATURE_FLAGS_CACHE_KEY = 'feature_flags_dict'
NAV_CACHE_KEY = 'navigation_items'
CACHE_SECONDS = 300


def _get_active_event():
    return Event.objects.get_active()


def _get_user_registration(request):
    if not request.user.is_authenticated:
        return None
    event = _get_active_event()
    if not event:
        return None
    return (
        EventRegistration.objects.filter(event=event, user=request.user)
        .select_related('user', 'ticket_type')
        .prefetch_related('seats')
        .first()
    )


def feature_flags(request):
    """
    Schlanker Context Processor:
    Stellt Navigations-Items und Site-Customization bereit.
    upcoming_event und user_registration werden lazy über SimpleLazyObject aufgelöst (0 DB-Queries bei Seiten ohne Event-Bezug).
    """
    nav_items = cache.get_or_set(
        NAV_CACHE_KEY,
        lambda: list(
            NavigationItem.objects.filter(is_active=True).order_by(
                'order', 'id'
            )
        ),
        CACHE_SECONDS,
    )

    site_customization = SiteCustomization.load()
    css_vars = site_customization.get_css_variables()
    theme_css_inline = "\n".join([f"  {k}: {v};" for k, v in css_vars.items()])

    return {
        'nav_items': nav_items,
        'features': {},
        'feature_flags': {},
        'site_customization': site_customization,
        'theme_css_vars': theme_css_inline,
        'custom_css': site_customization.custom_css,
        'upcoming_event': SimpleLazyObject(_get_active_event),
        'user_registration': SimpleLazyObject(lambda: _get_user_registration(request)),
    }
