"""Validate user-facing tournament links without contacting the provider."""
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from configuration.translations import get_translation


def validate_external_tournament_url(value):
    if not value or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value) or '\\' in value:
        raise ValidationError(get_translation('external_tournament_url_invalid'))
    try:
        URLValidator(schemes=['https'])(value)
        parsed = urlsplit(value)
        port = parsed.port
    except (ValidationError, ValueError) as exc:
        raise ValidationError(get_translation('external_tournament_url_invalid')) from exc
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError(get_translation('external_tournament_url_credentials'))
    if port is not None and not 1 <= port <= 65535:
        raise ValidationError(get_translation('external_tournament_url_invalid'))
