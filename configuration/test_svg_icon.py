from html.parser import HTMLParser

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from .models import NavigationItem
from .sanitizer import sanitize_and_validate_svg

PI_BYPASS = '<svg xmlns="http://www.w3.org/2000/svg"><?x </svg><img src=x onerror=alert(1)>?></svg>'


class _StartTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def html_start_tags(markup):
    parser = _StartTags()
    parser.feed(markup)
    return parser.tags


class SvgIconSanitizerTests(SimpleTestCase):
    """F-011: Ausgegeben wird nur, was validiert wurde."""

    def test_processing_instruction_cannot_smuggle_markup(self):
        cleaned = sanitize_and_validate_svg(PI_BYPASS)
        self.assertNotIn('<img', cleaned)
        self.assertNotIn('<?', cleaned)
        self.assertEqual([tag for tag, _ in html_start_tags(cleaned)], ['svg'])

    def test_comments_and_xml_declaration_are_dropped(self):
        cleaned = sanitize_and_validate_svg(
            '<?xml version="1.0" encoding="UTF-8"?>\n<!-- Generator: Editor --><svg viewBox="0 0 24 24">'
            '<!-- </svg><img src=x onerror=alert(1)> --><path d="M0 0h24"/></svg>'
        )
        self.assertEqual(cleaned, '<svg viewBox="0 0 24 24"><path d="M0 0h24"/></svg>')

    def test_namespaces_and_case_survive_reserialization(self):
        cleaned = sanitize_and_validate_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 24 24">'
            '<defs><clipPath id="c"><rect width="24" height="24"/></clipPath></defs>'
            '<use xlink:href="#c"/><text x="1">A &amp; B &lt;</text></svg>'
        )
        self.assertEqual(cleaned, (
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 24 24">'
            '<defs><clipPath id="c"><rect width="24" height="24"/></clipPath></defs>'
            '<use xlink:href="#c"/><text x="1">A &amp; B &lt;</text></svg>'
        ))
        self.assertEqual(sanitize_and_validate_svg(cleaned), cleaned)

    def test_style_attribute_and_external_references_are_rejected(self):
        for svg in (
            '<svg style="position:fixed;inset:0"><path d="M0 0"/></svg>',
            '<svg><use href="https://attacker.example/x.svg#a"/></svg>',
            '<svg xmlns:xlink="http://www.w3.org/1999/xlink"><use xlink:href="//attacker.example/x.svg#a"/></svg>',
        ):
            with self.subTest(svg=svg), self.assertRaises(ValidationError):
                sanitize_and_validate_svg(svg)


class NavigationItemSvgSaveTests(TestCase):
    def test_save_validates_custom_icon_without_clean(self):
        item = NavigationItem(title='Bypass', url_name='dashboard', icon_name=NavigationItem.IconChoices.CUSTOM,
                              icon_svg=PI_BYPASS)
        item.save()
        item.refresh_from_db()
        self.assertNotIn('<img', item.icon_svg)
        with self.assertRaises(ValidationError):
            NavigationItem(title='Script', url_name='dashboard', icon_name=NavigationItem.IconChoices.CUSTOM,
                           icon_svg='<svg><script>alert(1)</script></svg>').save()
        self.assertFalse(NavigationItem.objects.filter(title='Script').exists())
