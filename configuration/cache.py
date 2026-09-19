"""
Zentrales, abhängigkeitsfreies Cache-Management-Modul für EntailsNG.
Verhindert zirkuläre Importe zwischen events, seating, configuration und context_processors.
Fängt Verbindungsfehler (z. B. temporärer Redis-Ausfall) robust ab.
"""
import logging
from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)


def safe_cache_get(key, default=None):
    """Liest einen Wert aus dem Cache. Fängt Redis-Ausfälle sicher ab und liefert default."""
    try:
        return cache.get(key, default)
    except Exception as e:
        logger.warning("Cache-Lesezugriff fehlgeschlagen für Key '%s': %s", key, e)
        return default


def safe_cache_set(key, value, timeout=None):
    """Schreibt einen Wert in den Cache. Fängt Redis-Ausfälle sicher ab."""
    try:
        cache.set(key, value, timeout)
        return True
    except Exception as e:
        logger.warning("Cache-Schreibzugriff fehlgeschlagen für Key '%s': %s", key, e)
        return False


def safe_cache_get_or_set(key, default_callable, timeout=None):
    """Liest aus dem Cache oder berechnet den Wert via default_callable und cacht ihn.
    Bei Cache-Ausfall wird default_callable ausgeführt und der berechnete Wert direkt
    zurückgegeben (Graceful Database Fallback).
    """
    try:
        val = cache.get(key)
        if val is not None:
            return val
    except Exception as e:
        logger.warning("Cache-Lesezugriff (get_or_set) fehlgeschlagen für Key '%s': %s. Fallback auf Datenquelle.", key, e)
        val = None

    # Wert aus Callback (z. B. Datenbankabfrage) ermitteln
    computed = default_callable() if callable(default_callable) else default_callable

    try:
        cache.set(key, computed, timeout)
    except Exception as e:
        logger.warning("Cache-Speichern (get_or_set) fehlgeschlagen für Key '%s': %s", key, e)

    return computed


def safe_cache_delete(key):
    """Löscht einen Cache-Schlüssel und fängt Redis-Verbindungsfehler sicher ab."""
    try:
        cache.delete(key)
    except Exception as e:
        logger.warning("Cache-Löschung fehlgeschlagen für Key '%s': %s", key, e)


def safe_cache_delete_many(keys):
    """Löscht mehrere Cache-Schlüssel und fängt Redis-Verbindungsfehler sicher ab."""
    try:
        cache.delete_many(keys)
    except Exception as e:
        logger.warning("Cache-Löschung (delete_many) fehlgeschlagen für Keys %s: %s", keys, e)


def invalidate_event_capacity_cache(event_id):
    """Invalidiert die aggregierten Kapazitätsstatistiken eines Events garantiert erst nach DB-Commit."""
    if event_id:
        cache_key = f'event_capacity_stats_{event_id}'
        transaction.on_commit(lambda: safe_cache_delete(cache_key))


def invalidate_navigation_cache():
    """Invalidiert den Cache für die Hauptnavigation."""
    transaction.on_commit(lambda: safe_cache_delete('navigation_items'))


def invalidate_site_customization_cache():
    """Invalidiert den Cache für Theme und Branding."""
    transaction.on_commit(lambda: safe_cache_delete('site_customization'))


def invalidate_system_translations_cache():
    """Invalidiert den Cache für System-Übersetzungen."""
    transaction.on_commit(lambda: safe_cache_delete('system_translations'))


def invalidate_feature_flags_cache():
    """Invalidiert den Cache für Feature Flags."""
    transaction.on_commit(lambda: safe_cache_delete('feature_flags_dict'))


def invalidate_general_configuration_cache():
    """Invalidiert den Cache für die allgemeine Systemkonfiguration."""
    transaction.on_commit(lambda: safe_cache_delete('general_configuration'))


import threading

_request_local = threading.local()


def get_request_cache():
    """Gibt das Request-Cache-Dictionary für den aktuellen Thread zurück (oder None)."""
    return getattr(_request_local, 'cache', None)


def init_request_cache():
    """Initialisiert einen neuen Request-Cache für den aktuellen Thread."""
    _request_local.cache = {}
    return _request_local.cache


def clear_request_cache():
    """Bereinigt den Request-Cache des aktuellen Threads."""
    if hasattr(_request_local, 'cache'):
        del _request_local.cache


def invalidate_active_event_cache():
    """Invalidiert den Cache für die aktive Hauptveranstaltung."""
    safe_cache_delete('active_main_event_id')
    req_cache = get_request_cache()
    if req_cache is not None and 'active_event' in req_cache:
        del req_cache['active_event']


