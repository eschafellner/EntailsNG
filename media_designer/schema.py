"""Begrenztes, versionsfähiges Schema für druckbare Vorlagen."""

import re

from django.core.exceptions import ValidationError
from configuration.translations import get_translation


PAPER_MM = {
    'A4': (210, 297),
    'A6': (105, 148),
    'A7': (74, 105),
    'A8': (52, 74),
}

FIELD_LABELS = {
    'BADGE': {
        'guest.username': 'Gamer-Tag',
        'guest.clan': 'Clan',
        'guest.seat': 'Sitzplatz',
        'event.title': 'Veranstaltung',
        'event.start_date': 'Beginn (Datum/Uhrzeit)',
        'event.end_date': 'Ende (Datum/Uhrzeit)',
    },
    'CERTIFICATE': {
        'team.name': 'Teamname',
        'team.members': 'Teammitglieder (aktuell)',
        'team.placement': 'Platzierung',
        'award.title': 'Auszeichnung',
        'tournament.title': 'Turnier',
        'event.title': 'Veranstaltung',
        'event.start_date': 'Beginn (Datum/Uhrzeit)',
        'event.end_date': 'Ende (Datum/Uhrzeit)',
    },
}

FIELD_TRANSLATION_KEYS = {
    'guest.username': 'media_field_username',
    'guest.clan': 'media_field_clan',
    'guest.seat': 'media_field_seat',
    'event.title': 'media_field_event',
    'event.start_date': 'media_field_event_start',
    'event.end_date': 'media_field_event_end',
    'team.name': 'media_field_team',
    'team.members': 'media_field_team_members',
    'team.placement': 'media_field_placement',
    'award.title': 'media_field_award',
    'tournament.title': 'media_field_tournament',
}


def translated_field_labels():
    return {
        kind: {
            source: get_translation(FIELD_TRANSLATION_KEYS[source], default)
            for source, default in labels.items()
        }
        for kind, labels in FIELD_LABELS.items()
    }


def default_elements(kind):
    if kind == 'CERTIFICATE':
        return [
            {'source': 'award.title', 'x': 0.12, 'y': 0.24, 'width': 0.76,
             'font_size_mm': 10, 'color': '#172033', 'align': 'center'},
            {'source': 'team.name', 'x': 0.12, 'y': 0.44, 'width': 0.76,
             'font_size_mm': 14, 'color': '#172033', 'align': 'center'},
            {'source': 'team.placement', 'x': 0.25, 'y': 0.62, 'width': 0.5,
             'font_size_mm': 7, 'color': '#172033', 'align': 'center'},
        ]
    return [
        {'source': 'guest.username', 'x': 0.08, 'y': 0.38, 'width': 0.84,
         'font_size_mm': 6, 'color': '#172033', 'align': 'center'},
        {'source': 'guest.seat', 'x': 0.08, 'y': 0.60, 'width': 0.84,
         'font_size_mm': 4, 'color': '#172033', 'align': 'center'},
    ]


def validate_elements(elements, kind):
    if not isinstance(elements, list) or len(elements) > 30:
        raise ValidationError(get_translation('media_error_field_limit', 'Die Vorlage darf höchstens 30 Textfelder enthalten.'))
    allowed = FIELD_LABELS.get(kind, {})
    font_ids = set()
    for index, element in enumerate(elements, 1):
        if not isinstance(element, dict):
            raise ValidationError(get_translation('media_error_field_structure', 'Feld {index}: ungültige Struktur.', index=index))
        source = element.get('source')
        if source != 'static' and source not in allowed:
            raise ValidationError(get_translation('media_error_field_source', 'Feld {index}: unbekannte Datenquelle.', index=index))
        if source == 'static' and (
            not isinstance(element.get('text'), str) or len(element['text']) > 160
        ):
            raise ValidationError(get_translation('media_error_static_length', 'Feld {index}: fester Text darf höchstens 160 Zeichen haben.', index=index))
        for key in ('x', 'y', 'width'):
            value = element.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValidationError(get_translation('media_error_coordinate', 'Feld {index}: {key} muss zwischen 0 und 1 liegen.', index=index, key=key))
        if element['width'] <= 0 or element['x'] + element['width'] > 1.000001:
            raise ValidationError(get_translation('media_error_bounds', 'Feld {index}: Textbereich liegt außerhalb der Seite.', index=index))
        size = element.get('font_size_mm')
        if isinstance(size, bool) or not isinstance(size, (int, float)) or not 1.5 <= size <= 20:
            raise ValidationError(get_translation('media_error_font_size', 'Feld {index}: Schriftgröße muss zwischen 1,5 und 20 mm liegen.', index=index))
        if element.get('align') not in ('left', 'center', 'right'):
            raise ValidationError(get_translation('media_error_align', 'Feld {index}: ungültige Ausrichtung.', index=index))
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(element.get('color', ''))):
            raise ValidationError(get_translation('media_error_color', 'Feld {index}: ungültige Textfarbe.', index=index))
        if 'font_id' in element:
            font_id = element['font_id']
            if isinstance(font_id, bool) or not isinstance(font_id, int) or font_id <= 0:
                raise ValidationError(get_translation('media_error_font_choice', 'Feld {index}: unbekannte Schriftart.', index=index))
            font_ids.add(font_id)
    if font_ids:
        from media_designer.models import MediaFont
        existing_ids = set(MediaFont.objects.filter(pk__in=font_ids).values_list('pk', flat=True))
        if existing_ids != font_ids:
            raise ValidationError(get_translation('media_error_font_missing', 'Eine ausgewählte Schriftart ist nicht mehr verfügbar.'))
