from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .forms import ClanForm
from .models import Clan


class ClanWebsiteFormTests(SimpleTestCase):
    def test_bare_domains_receive_https_when_creating_and_editing(self):
        for instance in (None, Clan(pk=1, name='Existing Clan')):
            for value, expected in (
                ('www.clan.at', 'https://www.clan.at'),
                ('clan.at', 'https://clan.at'),
                ('  www.clan.at/team?lang=de  ', 'https://www.clan.at/team?lang=de'),
                ('//www.clan.at', 'https://www.clan.at'),
            ):
                with self.subTest(editing=instance is not None, value=value):
                    form = ClanForm(instance=instance)
                    self.assertEqual(form.fields['website'].clean(value), expected)

    def test_explicit_schemes_are_preserved(self):
        field = ClanForm().fields['website']
        for value in ('https://www.clan.at', 'http://www.clan.at'):
            with self.subTest(value=value):
                self.assertEqual(field.clean(value), value)

    def test_website_remains_optional_and_initially_empty(self):
        form = ClanForm()
        self.assertEqual(form.fields['website'].clean(''), '')
        self.assertFalse(form['website'].value())

    def test_invalid_urls_are_still_rejected(self):
        field = ClanForm().fields['website']
        for value in ('not a website', 'https://', 'javascript:alert(1)'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                field.clean(value)

    def test_browser_allows_bare_domains_with_url_keyboard(self):
        widget = str(ClanForm()['website'])
        self.assertIn('type="text"', widget)
        self.assertIn('inputmode="url"', widget)
        self.assertIn('autocapitalize="none"', widget)
        self.assertNotIn('type="url"', widget)
