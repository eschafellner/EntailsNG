"""Validation for explicitly trusted, external HTTPS frame sources."""
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from configuration.translations import get_translation


def https_origin(value):
    if not value or any(char.isspace() or ord(char) < 32 for char in value) or '\\' in value:
        raise ValidationError(get_translation('info_embed_invalid_url'))
    URLValidator(schemes=['https'])(value)
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError(get_translation('info_embed_url_credentials'))
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValidationError(get_translation('info_embed_url_port')) from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValidationError(get_translation('info_embed_url_port'))
    host = parsed.hostname.encode('idna').decode('ascii').lower()
    if ':' in host:
        host = f'[{host}]'
    return f'https://{host}' + (f':{port}' if port and port != 443 else '')


def validate_embed_origin(value):
    origin = https_origin(value)
    if value != origin:
        raise ValidationError(get_translation('info_embed_invalid_origin'))
