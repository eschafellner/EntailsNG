"""
Robuste und sichere HTML-, SVG- und CSS-Bereinigung für EntailsNG.
Verhindert XSS, Script-Injections und Entity-Decoding-Bypasses.
"""
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from django.core.exceptions import ValidationError

ALLOWED_SVG_TAGS = {
    'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon',
    'text', 'tspan', 'defs', 'clippath', 'mask', 'use', 'title', 'desc'
}
DISALLOWED_ATTRIBUTES_REGEX = re.compile(r'^(on|data-|formaction)', re.IGNORECASE)
DANGEROUS_PROTOCOLS_REGEX = re.compile(r'^\s*(javascript|data|vbscript|blob|file):', re.IGNORECASE)
DANGEROUS_CSS_PATTERNS = re.compile(
    r'(javascript:|expression\(|@import|<script|</style|behavior:|\bdata:)',
    re.IGNORECASE
)


class SafeHTMLSanitizer(HTMLParser):
    """
    Sicherer HTML-Sanitizer mit strikter Tag- und Attribut-Whitelist.
    Entfernt alle <script>, <iframe>, Inline-Event-Handler (on*) und bösartige URLs.
    Verhindert Entity-Decoding-Bypasses durch sicheres Re-Escaping von Textknoten.
    """
    ALLOWED_TAGS = {
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'br', 'hr',
        'strong', 'b', 'em', 'i', 'u', 's', 'small', 'sub', 'sup',
        'ul', 'ol', 'li', 'blockquote', 'a',
        'table', 'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span',
        'code', 'pre'
    }
    DROP_CONTENT_TAGS = {'script', 'style', 'noscript', 'iframe', 'object', 'embed', 'template'}
    ALLOWED_ATTRS = {'href', 'title', 'target', 'rel', 'class', 'id', 'align'}
    VOID_TAGS = {'br', 'hr'}
    ALLOWED_URL_SCHEMES = {'http', 'https', 'mailto', 'tel'}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.result = []
        self.tag_stack = []
        self.drop_depth = 0

    def _is_safe_url(self, url_str: str) -> bool:
        if not url_str:
            return True
        # Bereinige Whitespace und Steuerzeichen
        clean_url = re.sub(r'[\x00-\x20\s]+', '', str(url_str))
        if DANGEROUS_PROTOCOLS_REGEX.match(clean_url):
            return False
        try:
            parsed = urllib.parse.urlsplit(clean_url)
            scheme = parsed.scheme.lower()
            if scheme:
                return scheme in self.ALLOWED_URL_SCHEMES
            # Relative Pfade
            if clean_url.startswith('//'):
                return False  # Protokoll-relative URLs zu Fremd-Domains abweisen
            return True
        except Exception:
            return False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.DROP_CONTENT_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth > 0:
            return
        if tag not in self.ALLOWED_TAGS:
            return

        cleaned_attrs = []
        has_target_blank = False

        for name, value in attrs:
            name = name.lower()
            if name.startswith('on') or name.startswith('data-') or name.startswith('formaction'):
                continue
            if name not in self.ALLOWED_ATTRS:
                continue
            val_str = str(value) if value is not None else ""
            if name in ('href', 'src'):
                if not self._is_safe_url(val_str):
                    val_str = '#'
            if name == 'target' and val_str.lower() == '_blank':
                has_target_blank = True

            val_escaped = html.escape(val_str, quote=True)
            cleaned_attrs.append(f'{name}="{val_escaped}"')

        # noopener noreferrer für target="_blank"
        if has_target_blank and not any('rel=' in a for a in cleaned_attrs):
            cleaned_attrs.append('rel="noopener noreferrer"')

        attr_str = f" {' '.join(cleaned_attrs)}" if cleaned_attrs else ""
        self.result.append(f"<{tag}{attr_str}>")
        if tag not in self.VOID_TAGS:
            self.tag_stack.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.DROP_CONTENT_TAGS:
            if self.drop_depth > 0:
                self.drop_depth -= 1
            return
        if self.drop_depth > 0:
            return
        if tag in self.tag_stack:
            while self.tag_stack:
                popped = self.tag_stack.pop()
                self.result.append(f"</{popped}>")
                if popped == tag:
                    break

    def handle_data(self, data):
        if self.drop_depth > 0:
            return
        self.result.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        if self.drop_depth > 0:
            return
        self.result.append(f"&{name};")

    def handle_charref(self, name):
        if self.drop_depth > 0:
            return
        self.result.append(f"&#{name};")

    def get_clean_html(self):
        while self.tag_stack:
            self.result.append(f"</{self.tag_stack.pop()}>")
        return "".join(self.result)


def sanitize_html(html_code: str) -> str:
    """Bereinigt HTML-Texte (wie Impressum/Datenschutz) strikt vor XSS und Script-Injections."""
    if not html_code or not html_code.strip():
        return ""
    sanitizer = SafeHTMLSanitizer()
    sanitizer.feed(html_code)
    sanitizer.close()
    return sanitizer.get_clean_html()


def validate_custom_css(css_code: str):
    """Validiert benutzerdefiniertes CSS auf bösartige Injection-Konstrukte."""
    if not css_code or not css_code.strip():
        return
    if DANGEROUS_CSS_PATTERNS.search(css_code):
        raise ValidationError({
            'custom_css': "CSS enthält nicht erlaubte Ausdrücke (z. B. JavaScript, @import oder Script-Tags)."
        })


def sanitize_and_validate_svg(svg_code: str) -> str:
    """
    Validiert und bereinigt SVG-Code vor dem Speichern.
    Verhindert Stored-XSS, Script-Injections und gefährliche Attribute im Template (|safe).
    """
    if not svg_code or not svg_code.strip():
        return ""

    raw = svg_code.strip()

    # Schutz vor XXE / DTD Injections
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():
        raise ValidationError({'icon_svg': "SVG darf keine DOCTYPE- oder ENTITY-Deklarationen enthalten."})

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValidationError({'icon_svg': f"Ungültiger SVG/XML-Code: {e}"})

    def clean_tag(tag):
        if '}' in tag:
            return tag.split('}', 1)[1].lower()
        return tag.lower()

    if clean_tag(root.tag) != 'svg':
        raise ValidationError({'icon_svg': "Wurzelelement muss ein <svg>-Tag sein."})

    for elem in root.iter():
        tag_name = clean_tag(elem.tag)
        if tag_name not in ALLOWED_SVG_TAGS:
            raise ValidationError({'icon_svg': f"Nicht erlaubtes SVG-Tag '<{tag_name}>' im Icon-Code gefunden."})

        for attr, val in list(elem.attrib.items()):
            attr_clean = clean_tag(attr)
            if DISALLOWED_ATTRIBUTES_REGEX.match(attr_clean) or attr_clean == 'style':
                raise ValidationError({'icon_svg': f"Nicht erlaubtes Attribut '{attr}' im SVG gefunden."})
            if attr_clean in ('href', 'xlink:href', 'src') and DANGEROUS_PROTOCOLS_REGEX.match(str(val)):
                raise ValidationError({'icon_svg': f"Gefährliche URI im Attribut '{attr}' gefunden."})
            if attr_clean in ('href', 'src') and not str(val).strip().startswith('#'):
                raise ValidationError({'icon_svg': f"Im Attribut '{attr}' sind nur Verweise innerhalb des Icons (#id) erlaubt."})

    # Nicht den Rohstring zurückgeben: ElementTree verwirft Kommentare und Processing
    # Instructions, die der HTML-Parser des Browsers anders liest (Bypass über '<?…>').
    return _serialize_svg(root)


SVG_NAMESPACE = 'http://www.w3.org/2000/svg'
_SVG_ATTRIBUTE_PREFIXES = {
    'http://www.w3.org/1999/xlink': 'xlink',
    'http://www.w3.org/XML/1998/namespace': 'xml',
}


def _split_name(name):
    if name.startswith('{'):
        namespace, local = name[1:].split('}', 1)
        return namespace, local
    return None, name


def _serialize_svg(elem, is_root=True):
    """Serialisiert den validierten Baum; Attribute fremder Namespaces entfallen."""
    namespace, tag = _split_name(elem.tag)
    parts = ['<', tag]
    if is_root:
        if namespace == SVG_NAMESPACE:
            parts.append(f' xmlns="{SVG_NAMESPACE}"')
        used = {_split_name(attr)[0] for node in elem.iter() for attr in node.attrib}
        for ns_uri, prefix in _SVG_ATTRIBUTE_PREFIXES.items():
            if ns_uri in used and prefix != 'xml':
                parts.append(f' xmlns:{prefix}="{ns_uri}"')
    for name, value in elem.attrib.items():
        attr_ns, local = _split_name(name)
        if attr_ns is not None:
            if attr_ns not in _SVG_ATTRIBUTE_PREFIXES:
                continue
            local = f'{_SVG_ATTRIBUTE_PREFIXES[attr_ns]}:{local}'
        parts.append(f' {local}="{html.escape(value, quote=True)}"')
    children = list(elem)
    if not children and not elem.text:
        parts.append('/>')
        return ''.join(parts)
    parts.append('>')
    if elem.text:
        parts.append(html.escape(elem.text, quote=False))
    for child in children:
        parts.append(_serialize_svg(child, is_root=False))
        if child.tail:
            parts.append(html.escape(child.tail, quote=False))
    parts.append(f'</{tag}>')
    return ''.join(parts)
