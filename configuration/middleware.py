import logging
import sys
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.views.debug import technical_500_response
from .models import GeneralConfiguration

logger = logging.getLogger(__name__)


class DynamicDebugMiddleware:
    """
    Ermöglicht das dynamische Auslösen der Django-Debug-Fehlerseite bei Exceptions in Entwicklung/Staging.
    Sicherheitsprüfung:
    1. In Produktion (settings.DEBUG=False) wird technical_500_response NIEMALS im Browser ausgeliefert,
       um Information Leakage (SECRET_KEY, Passwörter, DB-Zugangsdaten) strikt zu verhindern.
       Fehler werden stattdessen ausschließlich sicher im Server-Log protokolliert.
    2. Wenn settings.DEBUG=True aktiv ist, wird die technische Fehlerseite nur an authentifizierte Staff/Superuser
       ausgeliefert, wenn conf.debug_mode aktiv ist.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        # 404 Not Found und 403 Forbidden sind reguläre HTTP-Zustände und keine 500er-Serverfehler
        if isinstance(exception, (Http404, PermissionDenied)):
            return None

        try:
            # 1. In Produktion niemals sensible Debug-Seiten mit Umgebungsvariablen/Secrets im Browser rendern
            if not getattr(settings, 'DEBUG', False):
                logger.error("Serverfehler (500) abgefangen: %s", exception, exc_info=True)
                return None

            # 2. Strikte Autorisierungsprüfung: Nur Staff/Superuser dürfen Debug-Details sehen
            user = getattr(request, 'user', None)
            if not user or not user.is_authenticated or not (user.is_staff or user.is_superuser):
                return None

            conf = GeneralConfiguration.load()
            if conf.debug_mode:
                return technical_500_response(request, *sys.exc_info())
        except Exception as e:
            logger.error("Fehler in DynamicDebugMiddleware: %s", e, exc_info=True)
        return None

