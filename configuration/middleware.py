import sys
from django.views.debug import technical_500_response
from .models import GeneralConfiguration


class DynamicDebugMiddleware:
    """
    Ermöglicht das dynamische Auslösen der Django-Debug-Fehlerseite bei Exceptions,
    wenn im Backend unter 'Allgemeine Konfiguration' der Debug-Modus aktiviert ist.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        try:
            conf = GeneralConfiguration.load()
            if conf.debug_mode:
                return technical_500_response(request, *sys.exc_info())
        except Exception:
            pass
        return None
