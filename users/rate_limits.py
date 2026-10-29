"""Reserve a request before performing side effects, with a fixed expiry window."""
import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)


def reserve_rate_limit(key, *, limit, timeout, fail_open=False):
    """Zählt eine Anfrage und gibt zurück, ob sie innerhalb des Limits liegt.

    Nur öffentliche Cache-API: add() legt den Zähler samt Ablauf atomar an, incr()
    zählt atomar (Redis und LocMem). Entsteht der Zähler nach einem Ablauf erst durch
    incr() neu (Ergebnis 1), setzt touch() den Ablauf, damit kein Dauerzähler bleibt.

    Fail-Policy bei Cache-Fehlern: Standard fail-closed (False, z. B. Mailversand bei
    Passwort-Reset und Aktivierungscodes); fail_open=True nur für Aufrufer, bei denen
    ein Ausfall des Limits unkritischer ist als eine blockierte Aktion.
    """
    try:
        for _ in range(3):
            if cache.add(key, 1, timeout=timeout):
                return True
            try:
                count = cache.incr(key)
            except ValueError:
                # Zwischen add() und incr() abgelaufen; nie per set() überschreiben.
                continue
            if count == 1:
                cache.touch(key, timeout)
            return count <= limit
        return False
    except Exception as exc:
        # Schlüssel enthalten IP- bzw. E-Mail-Adressen und werden nicht geloggt.
        logger.warning('Rate-Limit-Reservierung fehlgeschlagen (%s); %s.', type(exc).__name__,
                       'Anfrage zugelassen' if fail_open else 'Anfrage abgewiesen')
        return fail_open
