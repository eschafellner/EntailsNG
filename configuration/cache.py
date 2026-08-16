"""
Zentrales, abhängigkeitsfreies Cache-Management-Modul für EntailsNG.
Verhindert zirkuläre Importe zwischen events, seating, configuration und context_processors.
"""
from django.core.cache import cache


def invalidate_event_capacity_cache(event_id):
    """Invalidiert die aggregierten Kapazitätsstatistiken eines Events."""
    if event_id:
        cache.delete(f'event_capacity_stats_{event_id}')


def invalidate_navigation_cache():
    """Invalidiert den Cache für die Hauptnavigation."""
    cache.delete('navigation_items')


def invalidate_site_customization_cache():
    """Invalidiert den Cache für Theme und Branding."""
    cache.delete('site_customization')


def invalidate_system_translations_cache():
    """Invalidiert den Cache für System-Übersetzungen."""
    cache.delete('system_translations')


def invalidate_feature_flags_cache():
    """Invalidiert den Cache für Feature Flags."""
    cache.delete('feature_flags_dict')


def invalidate_general_configuration_cache():
    """Invalidiert den Cache für die allgemeine Systemkonfiguration."""
    cache.delete('general_configuration')
