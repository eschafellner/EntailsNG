"""Local image previews for existing rich-text news articles."""
from html.parser import HTMLParser
from html import unescape
import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError


def validate_news_image_size(image):
    if image.size > 10 * 1024 * 1024:
        raise ValidationError("Das Titelbild darf maximal 10 MB groß sein.")


class _ImageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.image = None

    def handle_starttag(self, tag, attrs):
        if tag != "img" or self.image:
            return
        attrs = dict(attrs)
        source = (attrs.get("src") or "").strip()
        parsed = urlsplit(source)
        # Keep previews offline-capable; never introduce third-party requests.
        if parsed.scheme or parsed.netloc or source.startswith("//") or "\\" in source:
            return
        if source.startswith(("/media/", "/static/", "media/", "static/")):
            self.image = {"url": "/" + source.lstrip("/"), "alt": attrs.get("alt") or ""}


def get_embedded_image(content):
    parser = _ImageParser()
    try:
        parser.feed(content)
    except ValueError:
        # Malformed old markup should not prevent rendering the dashboard.
        pass
    return parser.image


def get_preview_text(content):
    from django.utils.html import strip_tags
    # Preserve word boundaries between paragraphs, list items and line breaks.
    spaced = re.sub(r'</(?:p|div|h[1-6]|li|tr)>|<br\s*/?>', ' ', content, flags=re.IGNORECASE)
    return ' '.join(unescape(strip_tags(spaced)).split())
