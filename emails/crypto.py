import base64
import hashlib
import logging
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _get_fernet_key() -> bytes:
    """Leitet einen 32-Byte URL-sicheren Base64-Schlüssel aus dem Django SECRET_KEY ab."""
    secret = getattr(settings, 'SECRET_KEY', 'default-fallback-insecure-secret-key')
    key = hashlib.sha256(secret.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(key)


def encrypt_smtp_password(raw_password: str) -> str:
    """Verschlüsselt das SMTP-Passwort mit Fernet (AES-128-CBC + HMAC)."""
    if not raw_password:
        return ""
    # Falls das Passwort bereits verschlüsselt ist, nicht doppelt verschlüsseln
    if raw_password.startswith("gAAAAA"):
        try:
            f = Fernet(_get_fernet_key())
            f.decrypt(raw_password.encode('utf-8'))
            return raw_password
        except Exception:
            pass
    try:
        f = Fernet(_get_fernet_key())
        return f.encrypt(raw_password.encode('utf-8')).decode('utf-8')
    except Exception as e:
        logger.error(f"Fehler bei der Verschlüsselung des SMTP-Passworts: {e}")
        return raw_password


def decrypt_smtp_password(cipher_password: str) -> str:
    """Entschlüsselt das SMTP-Passwort zur Laufzeit.
    
    Falls in der DB noch ein unverschlüsselter Altbestand liegt oder die Entschlüsselung
    fehlschlägt, wird der Originalwert zurückgegeben.
    """
    if not cipher_password:
        return ""
    try:
        f = Fernet(_get_fernet_key())
        return f.decrypt(cipher_password.encode('utf-8')).decode('utf-8')
    except InvalidToken:
        return cipher_password
    except Exception as e:
        logger.warning(f"Fehler bei der Entschlüsselung des SMTP-Passworts: {e}")
        return cipher_password
