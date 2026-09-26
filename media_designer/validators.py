from django.core.exceptions import ValidationError
from io import BytesIO

from PIL import Image, ImageFont, UnidentifiedImageError

from configuration.translations import get_translation


def validate_background_image(upload):
    if not upload or not hasattr(upload, 'size'):
        return
    if upload.size > 10 * 1024 * 1024:
        raise ValidationError(get_translation('media_error_image_size', 'Das Hintergrundbild darf höchstens 10 MB groß sein.'))
    try:
        upload.seek(0)
        with Image.open(upload) as image:
            if image.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValidationError(get_translation('media_error_image_format', 'Erlaubt sind JPG, PNG und WebP.'))
            if image.width * image.height > 25_000_000:
                raise ValidationError(get_translation('media_error_image_pixels', 'Das Hintergrundbild darf höchstens 25 Megapixel haben.'))
            image.verify()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError(get_translation('media_error_image_invalid', 'Das Hintergrundbild ist beschädigt oder ungültig.')) from exc
    finally:
        upload.seek(0)


def validate_font_file(upload):
    if not upload or not hasattr(upload, 'size'):
        return
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError(get_translation('media_error_font_file_size', 'Die Schriftdatei darf höchstens 5 MB groß sein.'))
    suffix = upload.name.rsplit('.', 1)[-1].lower()
    signatures = {
        'ttf': b'\x00\x01\x00\x00',
        'otf': b'OTTO',
        'woff2': b'wOF2',
    }
    if suffix not in signatures:
        raise ValidationError(get_translation('media_error_font_file_format', 'Erlaubt sind TTF, OTF und WOFF2.'))
    try:
        upload.seek(0)
        content = upload.read()
        if not content.startswith(signatures[suffix]):
            raise ValueError('Font signature does not match its extension')
        ImageFont.truetype(BytesIO(content), size=16).getbbox('Test 123')
    except (OSError, ValueError) as exc:
        raise ValidationError(get_translation('media_error_font_file_invalid', 'Die Schriftdatei ist beschädigt oder ungültig.')) from exc
    finally:
        upload.seek(0)
