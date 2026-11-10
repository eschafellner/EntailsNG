"""Inhalt von Infoseiten: HTML-Bereinigung mit lokalen Bildern und Bild-Uploads."""
import html
import re
import uuid
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageOps, UnidentifiedImageError

from configuration.sanitizer import SafeHTMLSanitizer
from configuration.translations import get_translation

IMAGE_DIR = 'info/images'
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
# Pillow-Format -> (Dateiendung, Speicheroptionen)
IMAGE_FORMATS = {
    'PNG': ('png', {'optimize': True}),
    'JPEG': ('jpg', {'quality': 90, 'optimize': True}),
    'WEBP': ('webp', {'quality': 90}),
}


def image_url_pattern():
    prefix = re.escape(f'{settings.MEDIA_URL}{IMAGE_DIR}/')
    return re.compile(rf'^{prefix}[0-9a-f]{{32}}\.(?:png|jpg|webp)$')


class InfoSanitizer(SafeHTMLSanitizer):
    """Wie SafeHTMLSanitizer, erlaubt aber <img> mit über den Admin hochgeladenen Bildern."""

    def __init__(self):
        super().__init__()
        self.image_url = image_url_pattern()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_starttag(self, tag, attrs):
        if tag.lower() != 'img':
            return super().handle_starttag(tag, attrs)
        if self.drop_depth:
            return
        attributes = dict(attrs)
        source = (attributes.get('src') or '').strip()
        if not self.image_url.fullmatch(source):
            return
        safe = {'src': source, 'alt': attributes.get('alt') or ''}
        for dimension in ('width', 'height'):
            value = attributes.get(dimension) or ''
            if value.isdecimal() and len(value) <= 4 and 0 < int(value) <= 4096:
                safe[dimension] = value
        self.result.append('<img' + ''.join(
            f' {key}="{html.escape(value, quote=True)}"' for key, value in safe.items()) + '>')


def sanitize_info_html(html_code):
    if not html_code or not html_code.strip():
        return ''
    sanitizer = InfoSanitizer()
    sanitizer.feed(html_code)
    sanitizer.close()
    return sanitizer.get_clean_html()


def store_image(upload):
    """Prüft ein hochgeladenes Bild, kodiert es neu (ohne Metadaten) und gibt die URL zurück."""
    invalid = ValidationError(get_translation(
        'info_image_invalid', 'Bitte ein PNG-, JPG- oder WebP-Bild mit höchstens 10 MB hochladen.'))
    if not upload or upload.size > MAX_IMAGE_BYTES:
        raise invalid
    try:
        with Image.open(upload) as probe:
            if probe.format not in IMAGE_FORMATS or probe.width * probe.height > MAX_IMAGE_PIXELS:
                raise invalid
            probe.verify()
        upload.seek(0)
        with Image.open(upload) as image:
            image_format = image.format
            image = ImageOps.exif_transpose(image)
            if image_format == 'JPEG' and image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')
            extension, options = IMAGE_FORMATS[image_format]
            output = BytesIO()
            image.save(output, format=image_format, **options)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise invalid from exc
    name = default_storage.save(f'{IMAGE_DIR}/{uuid.uuid4().hex}.{extension}', ContentFile(output.getvalue()))
    return default_storage.url(name)
