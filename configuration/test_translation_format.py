from django.core.cache import cache
from django.template import Context, Template
from django.test import TestCase

from .models import SystemTranslation
from .translations import get_translation


class _Secretive:
    """Steht für ein Model-Objekt, dessen Attribute nicht im Text landen dürfen."""
    secret = 'GEHEIM'

    def __str__(self):
        return 'Anzeigename'

    def save(self):
        pass


class TranslationPlaceholderFormattingTests(TestCase):
    """F-009: Platzhalter in editierbaren Texten dürfen keine Attribute oder Indizes auflösen."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _translate(self, text, **kwargs):
        SystemTranslation.objects.update_or_create(key='f009_probe', defaults={'text': text})
        cache.clear()
        return get_translation('f009_probe', **kwargs)

    def test_simple_placeholders_still_work(self):
        self.assertEqual(self._translate('Team {team_name} ({count})', team_name='Alpha', count=3), 'Team Alpha (3)')
        self.assertEqual(self._translate('{{literal}} {name}', name='x'), '{literal} x')

    def test_objects_are_formatted_as_their_string(self):
        self.assertEqual(self._translate('Team {x}', x=_Secretive()), 'Team Anzeigename')

    def test_attribute_access_is_not_resolved(self):
        for text in ('{x.__class__}', '{x.secret}', '{x.save.__globals__}', '{x.__init__.__globals__[settings]}'):
            with self.subTest(text=text):
                result = self._translate(text, x=_Secretive())
                self.assertNotIn('GEHEIM', result)
                self.assertNotIn('class', result.replace(text, ''))
                self.assertNotIn('settings', result.replace(text, ''))
                self.assertNotIn('_Secretive', result)
                self.assertEqual(result, text)

    def test_index_and_positional_access_is_not_resolved(self):
        self.assertEqual(self._translate('{x[0]}', x='abc'), '{x[0]}')
        self.assertEqual(self._translate('{0}', x='abc'), '{0}')

    def test_template_tag_does_not_resolve_attributes(self):
        SystemTranslation.objects.update_or_create(key='f009_probe', defaults={'text': 'Leak: {x.secret} {x.__class__}'})
        cache.clear()
        rendered = Template('{% t "f009_probe" x=obj %}').render(Context({'obj': _Secretive()}))
        self.assertNotIn('GEHEIM', rendered)
        self.assertNotIn('_Secretive', rendered)

    def test_format_specs_are_not_applied(self):
        self.assertEqual(self._translate('{x:>99999}', x='abc'), '{x:>99999}')
