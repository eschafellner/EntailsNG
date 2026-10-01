import html
import re
from html.parser import HTMLParser

from configuration.sanitizer import SafeHTMLSanitizer


IMAGE_URL = re.compile(r'^/knowledge/attachments/[0-9a-f-]{36}/\?inline=1$')


class KnowledgeSanitizer(SafeHTMLSanitizer):
    ALLOWED_ATTRS = SafeHTMLSanitizer.ALLOWED_ATTRS | {'colspan', 'rowspan'}

    def handle_data(self, data):
        if not self.drop_depth:
            self.result.append(html.escape(data, quote=False))

    def handle_starttag(self, tag, attrs):
        if tag.lower() != 'img':
            return super().handle_starttag(tag, attrs)
        if self.drop_depth:
            return
        attributes = dict(attrs)
        source = attributes.get('src') or ''
        if not IMAGE_URL.fullmatch(source):
            return
        safe = {'src': source, 'alt': attributes.get('alt') or ''}
        for dimension in ('width', 'height'):
            value = attributes.get(dimension) or ''
            if value.isdecimal() and len(value) <= 4 and 0 < int(value) <= 4096:
                safe[dimension] = value
        self.result.append('<img' + ''.join(f' {key}="{html.escape(value, quote=True)}"' for key, value in safe.items()) + '>')


def sanitize_content(content):
    sanitizer = KnowledgeSanitizer()
    sanitizer.feed(content or '')
    return sanitizer.get_clean_html()


class TextContent(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in ('p', 'li', 'h1', 'h2', 'h3', 'h4', 'pre', 'tr', 'div', 'blockquote'):
            self.parts.append('\n')

    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'hr'):
            self.parts.append('\n')
        elif tag == 'img':
            self.parts.append(dict(attrs).get('alt') or '')


def content_text(content):
    parser = TextContent()
    parser.feed(content or '')
    return ''.join(parser.parts).strip()
