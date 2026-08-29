import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger(__name__)

FERNET_PREFIX = 'gAAAAA'


class SecretUnreadable(Exception):
    """Ein gespeichertes Secret kann mit dem aktuellen Schlüssel nicht gelesen werden."""


def _get_fernet_key() -> bytes:
    """
    Leitet den Fernet-Schlüssel ab.

    Bevorzugt FIELD_ENCRYPTION_KEY. Fällt nur ersatzweise auf SECRET_KEY zurück,
    damit Altbestände lesbar bleiben. Ein Wechsel des SECRET_KEY — wie im
    README für die Produktion empfohlen — macht sonst alle Passwörter unlesbar.
    """
    key_material = os.environ.get('FIELD_ENCRYPTION_KEY') or getattr(settings, 'FIELD_ENCRYPTION_KEY', '')
    if not key_material:
        key_material = getattr(settings, 'SECRET_KEY', '')
        logger.warning(
            "FIELD_ENCRYPTION_KEY ist nicht gesetzt. Es wird ersatzweise der "
            "SECRET_KEY verwendet. Wird der SECRET_KEY geändert, sind "
            "gespeicherte SMTP-Passwörter nicht mehr lesbar."
        )
    if not key_material:
        raise SecretUnreadable("Kein Schlüsselmaterial verfügbar.")

    digest = hashlib.sha256(key_material.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(raw: str) -> str:
    """Verschlüsselt einen Klartextwert. Bereits verschlüsselte Werte bleiben unverändert."""
    if not raw:
        return ''
    if raw.startswith(FERNET_PREFIX) and is_readable(raw):
        return raw
    return Fernet(_get_fernet_key()).encrypt(raw.encode('utf-8')).decode('utf-8')


def decrypt_secret(cipher: str) -> str:
    """
    Entschlüsselt einen Wert.

    Wirft SecretUnreadable, statt den Ciphertext zurückzugeben. Ein an
    den SMTP-Server gesendeter Ciphertext erzeugt sonst einen '535
    Authentication failed', der wie ein Zugangsdatenproblem aussieht,
    tatsächlich aber ein Schlüsselproblem ist.
    """
    if not cipher:
        return ''

    # Altbestand: unverschlüsselt in der DB (kein Fernet-Prefix)
    if not cipher.startswith(FERNET_PREFIX):
        logger.warning("SMTP-Passwort liegt unverschlüsselt in der Datenbank.")
        return cipher

    try:
        return Fernet(_get_fernet_key()).decrypt(cipher.encode('utf-8')).decode('utf-8')
    except InvalidToken as exc:
        raise SecretUnreadable(
            "Das gespeicherte SMTP-Passwort kann nicht entschlüsselt werden. "
            "Wurde FIELD_ENCRYPTION_KEY oder SECRET_KEY geändert? "
            "Bitte das Passwort im Admin neu eingeben."
        ) from exc


def is_readable(cipher: str) -> bool:
    """Prüft ohne Exception, ob ein Wert entschlüsselbar ist."""
    if not cipher:
        return True
    try:
        decrypt_secret(cipher)
        return True
    except SecretUnreadable:
        return False


# Rückwärtskompatible Aliase — bestehende Aufrufer brechen nicht
encrypt_smtp_password = encrypt_secret
decrypt_smtp_password = decrypt_secret
