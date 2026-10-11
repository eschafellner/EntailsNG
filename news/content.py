"""Article HTML allowlist, including safe embedded images and table cells."""
import html
from urllib.parse import urlsplit

from configuration.sanitizer import SafeHTMLSanitizer


class NewsSanitizer(SafeHTMLSanitizer):
    ALLOWED_ATTRS = SafeHTMLSanitizer.ALLOWED_ATTRS | {'colspan', 'rowspan'}

    def handle_starttag(self, tag, attrs):
        if tag.lower() != 'img':
            return super().handle_starttag(tag, attrs)
        if self.drop_depth:
            return
        attributes = dict(attrs)
        source = attributes.get('src') or ''
        if not source or not self._is_safe_url(source):
            return
        try:
            if urlsplit(source).scheme.lower() not in ('', 'http', 'https'):
                return
        except ValueError:
            return
        safe = {'src': source, 'alt': attributes.get('alt') or ''}
        for dimension in ('width', 'height'):
            value = attributes.get(dimension) or ''
            if value.isascii() and value.isdecimal() and len(value) <= 4 and 0 < int(value) <= 4096:
                safe[dimension] = value
        self.result.append('<img' + ''.join(f' {key}="{html.escape(value, quote=True)}"' for key, value in safe.items()) + '>')


def sanitize_news_html(content):
    sanitizer = NewsSanitizer()
    sanitizer.feed(content or '')
    sanitizer.close()
    return sanitizer.get_clean_html()
