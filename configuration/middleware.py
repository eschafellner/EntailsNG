import logging
import sys
import traceback
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseServerError
from django.template.loader import render_to_string
from django.views.debug import technical_500_response
from .models import GeneralConfiguration

logger = logging.getLogger(__name__)


class RequestCacheMiddleware:
    """
    Verwaltet einen leichtgewichtigen Request-Scoped Cache pro Thread/Request.
    Verhindert mehrfache redundante Cache- und Datenbankabfragen (z. B. Übersetzungen, aktives Event)
    innerhalb desselben HTTP-Requests und bereinigt den Cache im finally-Block.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .cache import init_request_cache, clear_request_cache
        init_request_cache()
        request._cached_translations = None
        try:
            response = self.get_response(request)
            return response
        finally:
            clear_request_cache()


class DynamicDebugMiddleware:
    """
    Ermöglicht das dynamische Auslösen der Django-Debug-Fehlerseite bei Exceptions in Entwicklung/Staging
    und erfasst alle serverseitigen 500er-Fehler persistent im System-Fehlerprotokoll (SystemErrorLog).

    Sicherheitsprüfung:
    1. In Produktion (settings.DEBUG=False) wird technical_500_response NIEMALS im Browser ausgeliefert,
       um Information Leakage (SECRET_KEY, Passwörter, DB-Zugangsdaten) strikt zu verhindern.
       Der Fehler wird sicher in der Datenbank protokolliert und dem Benutzer wird eine sichere 500-Seite
       mit Fehler-Referenz-ID angezeigt.
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

        # 1. System-Fehlerprotokoll in der Datenbank erfassen
        error_log = None
        try:
            from users.auth_backends import get_client_ip
            from .models import SystemErrorLog

            user_str = "Anonym"
            user = getattr(request, 'user', None)
            if user and user.is_authenticated:
                user_str = getattr(user, 'username', str(user))

            tb_str = traceback.format_exc()
            error_log = SystemErrorLog.objects.create(
                path=request.path[:500] if request else "",
                method=request.method if request else "GET",
                exception_type=exception.__class__.__name__,
                error_message=str(exception),
                traceback=tb_str,
                user=user_str,
                ip_address=get_client_ip(request) if request else None,
            )
            if request:
                request.system_error_id = error_log.id
        except Exception as log_err:
            logger.error("Fehler beim Erfassen des SystemErrorLog: %s", log_err)

        try:
            # 2. In Produktion niemals sensible Debug-Seiten mit Umgebungsvariablen/Secrets im Browser rendern
            if not getattr(settings, 'DEBUG', False):
                logger.error("Serverfehler (500) abgefangen: %s", exception, exc_info=True)
                return None

            # 3. Unter DEBUG=True: Strikte Autorisierungsprüfung für technische Debug-Details
            user = getattr(request, 'user', None)
            is_staff_or_super = bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))

            if is_staff_or_super:
                conf = GeneralConfiguration.load()
                if conf.debug_mode:
                    return technical_500_response(request, *sys.exc_info())

            # Nicht autorisierte Besucher oder debug_mode=False:
            # Neutrale Fehlerantwort rendern, um die Offenlegung von Traceback und Secrets bei DEBUG=True zu verhindern
            from django.views.defaults import server_error
            return server_error(request)
        except Exception as e:
            logger.error("Fehler in DynamicDebugMiddleware: %s", e, exc_info=True)
            from django.views.defaults import server_error
            try:
                return server_error(request)
            except Exception:
                return None
