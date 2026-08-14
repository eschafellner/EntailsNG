import ipaddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.cache import cache
from django.db.models import Q

User = get_user_model()


def _get_client_ip(request):
    if not request:
        return '127.0.0.1'

    remote_addr = request.META.get('REMOTE_ADDR', '127.0.0.1')
    use_x_forwarded_for = getattr(settings, 'USE_X_FORWARDED_FOR', False)
    num_proxies = getattr(settings, 'NUM_PROXIES', 1)

    if use_x_forwarded_for:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ips = [ip.strip() for ip in x_forwarded_for.split(',') if ip.strip()]
            if len(ips) >= num_proxies:
                candidate_ip = ips[-num_proxies]
                try:
                    ipaddress.ip_address(candidate_ip)
                    return candidate_ip
                except ValueError:
                    pass

    return remote_addr



def _is_ip_rate_limited(ip_address):
    cache_key = f"ip_failed_logins_{ip_address}"
    attempts = cache.get(cache_key, 0)
    return attempts >= 25


def _record_ip_failed_attempt(ip_address):
    cache_key = f"ip_failed_logins_{ip_address}"
    attempts = cache.get(cache_key, 0) + 1
    cache.set(cache_key, attempts, timeout=300)  # 5 Minuten Fenster


class EmailOrUsernameBackend(ModelBackend):
    """
    Authentifizierungs-Backend, das die Anmeldung sowohl per Benutzername
    als auch per E-Mail-Adresse erlaubt, IP-Rate-Limiting (25 Versuche/5min)
    durchführt und die 15-Minuten-Account-Sperre nach 5 Fehlversuchen verwaltet.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        client_ip = _get_client_ip(request)

        # 1. IP-basiertes Rate-Limiting prüfen (25 Versuche pro 5 Minuten pro IP)
        if _is_ip_rate_limited(client_ip):
            if request:
                setattr(request, 'ip_rate_limited', True)
            return None

        # 2. Suche nach Benutzername ODER E-Mail-Adresse (case-insensitive)
        try:
            user = User.objects.get(
                Q(username__iexact=username) | Q(email__iexact=username)
            )
        except User.DoesNotExist:
            _record_ip_failed_attempt(client_ip)
            return None
        except User.MultipleObjectsReturned:
            user = User.objects.filter(
                Q(username__iexact=username) | Q(email__iexact=username)
            ).first()

        # 3. Prüfe, ob Konto aktuell temporär gesperrt ist (15 Minuten Sperre)
        if user.is_locked():
            if request:
                setattr(request, 'account_locked', True)
                setattr(request, 'locked_user', user)
            return None

        # 4. Passwort verifizieren
        if user.check_password(password):
            user.reset_lockout()
            return user
        else:
            _record_ip_failed_attempt(client_ip)
            user.register_failed_login()
            if user.is_locked() and request:
                setattr(request, 'account_locked', True)
                setattr(request, 'locked_user', user)
            return None

