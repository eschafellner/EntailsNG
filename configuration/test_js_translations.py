import re

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from configuration.models import SystemTranslation

User = get_user_model()
TRICKY = "Zeile1\nZeile2 \\ ' \" </script><b>fett</b>"


class TranslationsInInlineScriptsTests(TestCase):
    """F-033: Systemtexte in Inline-Skripten werden JavaScript-sicher eingebettet."""

    def setUp(self):
        cache.clear()

    def set_text(self, key):
        SystemTranslation.objects.update_or_create(key=key, defaults={'text': TRICKY})
        cache.clear()

    def assert_js_safe(self, response):
        scripts = '\n'.join(re.findall(r'<script>(.*?)</script>', response.content.decode(), re.S))
        self.assertNotIn('Zeile1\nZeile2', scripts)
        self.assertIn('Zeile1\\u000AZeile2', scripts)

    def test_sponsor_list(self):
        self.set_text('sponsors_read_more')
        self.assert_js_safe(self.client.get(reverse('sponsor_list')))

    def test_team_detail_copy_feedback(self):
        from tournaments.models import Team
        self.set_text('team_invite_code_copied')
        team = Team.objects.create(name='JS Team', captain=User.objects.create_user('js-captain'))
        response = self.client.get(reverse('team_detail', args=[team.slug]))
        self.assert_js_safe(response)
        # Text darf nicht per innerHTML als Markup eingesetzt werden.
        self.assertNotIn("innerHTML = '✓ <span>", response.content.decode())

    def test_verify_email_countdown(self):
        self.set_text('verify_code_expired_badge')
        user = User.objects.create_user('js-pending', 'js-pending@example.com', 'StrongPass123!', is_active=False)
        session = self.client.session
        session['pending_verification_user_id'] = user.pk
        session.save()
        self.assert_js_safe(self.client.get(reverse('verify_email')))
