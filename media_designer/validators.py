from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

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
