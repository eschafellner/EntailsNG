import ipaddress
import logging
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.cache import cache
from django.db.models import Q

logger = logging.getLogger(__name__)

User = get_user_model()


def get_client_ip(request):
    """Ermittelt die IP-Adresse des Clients sicher, auch hinter Reverse-Proxies und Cloudflare."""
    if not request:
        return '127.0.0.1'

    behind_proxy = getattr(settings, 'BEHIND_PROXY', False)
    use_x_forwarded_for = getattr(settings, 'USE_X_FORWARDED_FOR', behind_proxy)
    num_proxies = getattr(settings, 'NUM_PROXIES', 1)
    trust_cloudflare = getattr(settings, 'TRUST_CLOUDFLARE', False)

    if behind_proxy or use_x_forwarded_for:
        # 1. Cloudflare Edge liefert die reale Client-IP in CF-Connecting-IP (nur wenn TRUST_CLOUDFLARE aktiviert)
        if trust_cloudflare:
            cf_ip = request.META.get('HTTP_CF_CONNECTING_IP')
            if cf_ip:
                candidate = cf_ip.strip()
                try:
                    ipaddress.ip_address(candidate)
                    return candidate
                except ValueError:
                    pass

        # 2. Reverse Proxy (Nginx) liefert X-Real-IP
        real_ip = request.META.get('HTTP_X_REAL_IP')
        if real_ip:
            candidate = real_ip.strip()
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                pass

        # 3. Standard X-Forwarded-For Kette
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

    return request.META.get('REMOTE_ADDR', '127.0.0.1')


_get_client_ip = get_client_ip




def _is_ip_rate_limited(ip_address):
    cache_key = f"ip_failed_logins_{ip_address}"
    try:
        attempts = cache.get(cache_key, 0)
        return (attempts or 0) >= 25
    except Exception as e:
        logger.warning(
            "IP-Rate-Limit Cache-Prüfung fehlgeschlagen für IP '%s': %s. Fail-Open aktiv.",
            ip_address, e
        )
        return False


def _record_ip_failed_attempt(ip_address):
    cache_key = f"ip_failed_logins_{ip_address}"
    try:
        # Atomare Inkrementierung (verhindert Race Conditions bei parallelen Login-Requests)
        if cache.add(cache_key, 1, timeout=300):
            return 1
        return cache.incr(cache_key)
    except (ValueError, TypeError):
        try:
            cache.set(cache_key, 1, timeout=300)
            return 1
        except Exception:
            return 1
    except Exception as e:
        logger.warning(
            "IP-Rate-Limit Inkrementierung fehlgeschlagen für IP '%s': %s",
            ip_address, e
        )
        return 1


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

        # 2. Suche nach Benutzer:
        # Falls Eingabe ein '@' enthält, suchen wir primär nach E-Mail-Adresse.
        # Falls kein '@' enthalten ist, suchen wir primär nach Benutzername, Fallback auf E-Mail.
        user = None
        clean_input = username.strip()
        if '@' in clean_input:
            user = User.objects.filter(email__iexact=clean_input).first()
            if not user:
                user = User.objects.filter(username__iexact=clean_input).first()
        else:
            user = User.objects.filter(username__iexact=clean_input).first()
            if not user:
                user = User.objects.filter(email__iexact=clean_input).first()

        if not user:
            # Timing-Attack Mitigation: Konstante Laufzeit sicherstellen (Dummy-Hashing)
            User().set_password(password)
            _record_ip_failed_attempt(client_ip)
            return None

        # 3. Inaktive Konten (z. B. vor Double Opt-In E-Mail-Verifizierung)
        if not user.is_active:
            if user.check_password(password):
                # Wenn Passswort stimmt: Prüfen, ob Konto noch unbestätigt ist (Session-Wiederaufnahme)
                has_pending_verification = user.verification_codes.filter(
                    new_email__isnull=True, is_used=False
                ).exists()
                if has_pending_verification and request:
                    setattr(request, 'unverified_user', user)
            return None

        # 4. Prüfe, ob Konto aktuell temporär gesperrt ist (15 Minuten Sperre)
        # Abgelaufene Sperren atomar unter Zeilensperre zurücksetzen
        if user.locked_until:
            user.reset_expired_lockout()

        if user.is_locked():
            if request:
                setattr(request, 'account_locked', True)
                setattr(request, 'locked_user', user)
            return None

        # 5. Passwort verifizieren
        if user.check_password(password):
            # Vor erfolgreichem Login prüfen, ob zwischenzeitlich durch parallele Requests gesperrt wurde
            user.refresh_from_db(fields=['locked_until', 'failed_login_attempts'])
            if user.locked_until:
                user.reset_expired_lockout()
            if user.is_locked():
                if request:
                    setattr(request, 'account_locked', True)
                    setattr(request, 'locked_user', user)
                return None
            user.reset_lockout()
            return user
        else:
            _record_ip_failed_attempt(client_ip)
            user.register_failed_login()
            if user.is_locked() and request:
                setattr(request, 'account_locked', True)
                setattr(request, 'locked_user', user)
            return None


