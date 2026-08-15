import logging
import sys
from django.views.debug import technical_500_response
from .models import GeneralConfiguration

logger = logging.getLogger(__name__)


class DynamicDebugMiddleware:
    """
    Ermöglicht das dynamische Auslösen der Django-Debug-Fehlerseite bei Exceptions.
    Sicherheitsprüfung: Wird AUSSCHLIESSLICH an authentifizierte Superuser/Staff ausgeliefert,
    um Information Leakage (SECRET_KEY, Passwörter, DB-Zugangsdaten) im Produktivbetrieb zu verhindern.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        try:
            # Strikte Autorisierungsprüfung: Nur Staff/Superuser dürfen Debug-Details sehen
            user = getattr(request, 'user', None)
            if not user or not user.is_authenticated or not (user.is_staff or user.is_superuser):
                return None

            conf = GeneralConfiguration.load()
            if conf.debug_mode:
                return technical_500_response(request, *sys.exc_info())
        except Exception as e:
            logger.error("Fehler in DynamicDebugMiddleware: %s", e, exc_info=True)
        return None

