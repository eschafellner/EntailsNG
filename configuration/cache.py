"""
Zentrales, abhängigkeitsfreies Cache-Management-Modul für EntailsNG.
Verhindert zirkuläre Importe zwischen events, seating, configuration und context_processors.
"""
from django.core.cache import cache
from django.db import transaction


def invalidate_event_capacity_cache(event_id):
    """Invalidiert die aggregierten Kapazitätsstatistiken eines Events garantiert erst nach DB-Commit."""
    if event_id:
        cache_key = f'event_capacity_stats_{event_id}'
        transaction.on_commit(lambda: cache.delete(cache_key))


def invalidate_navigation_cache():
    """Invalidiert den Cache für die Hauptnavigation."""
    transaction.on_commit(lambda: cache.delete('navigation_items'))


def invalidate_site_customization_cache():
    """Invalidiert den Cache für Theme und Branding."""
    transaction.on_commit(lambda: cache.delete('site_customization'))


def invalidate_system_translations_cache():
    """Invalidiert den Cache für System-Übersetzungen."""
    transaction.on_commit(lambda: cache.delete('system_translations'))


def invalidate_feature_flags_cache():
    """Invalidiert den Cache für Feature Flags."""
    transaction.on_commit(lambda: cache.delete('feature_flags_dict'))


def invalidate_general_configuration_cache():
    """Invalidiert den Cache für die allgemeine Systemkonfiguration."""
    transaction.on_commit(lambda: cache.delete('general_configuration'))

