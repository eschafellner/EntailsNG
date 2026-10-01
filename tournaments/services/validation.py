"""Strict form/service validation, also independent of the database backend."""
import re
from configuration.translations import get_translation
from tournaments.exceptions import TournamentError


def integer(value, *, minimum=0, maximum=2**31-1, error=TournamentError, label='Wert'):
    if isinstance(value, bool) or not (isinstance(value, int) or
        isinstance(value, str) and re.fullmatch(r'[+-]?\d+', value.strip())):
        raise error(get_translation('audit_numeric_invalid', '{label} muss eine ganze Zahl sein.', label=label))
    try:
        result = int(value)
    except (ValueError, TypeError):
        raise error(get_translation('audit_numeric_invalid', '{label} muss eine ganze Zahl sein.', label=label))
    if not minimum <= result <= maximum:
        raise error(get_translation('audit_numeric_range', '{label} muss zwischen {minimum} und {maximum} liegen.', label=label, minimum=minimum, maximum=maximum))
    return result


def identifier(value, *, error=TournamentError):
    return integer(value, minimum=1, maximum=2**63-1, error=error, label='ID')


def note(value, *, error=TournamentError):
    result = str(value).strip() if value is not None else ''
    if len(result) > 255:
        raise error(get_translation('audit_note_length', 'Die Begründung darf höchstens 255 Zeichen enthalten.'))
    return result
