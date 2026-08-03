from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from configuration.models import FeatureFlag, NavigationItem, SystemTranslation

User = get_user_model()


class ConfigurationModelTests(TestCase):

    def test_navigation_item_url(self):
        item = NavigationItem.objects.create(
            title='Sitzplan', url_name='seating_plan', order=1
        )
        self.assertEqual(item.get_url(), '/seating/')

    def test_navigation_item_alias_url(self):
        item = NavigationItem.objects.create(
            title='Sitzplan', url_name='seating', order=1
        )
        self.assertEqual(item.get_url(), '/seating/')

    def test_system_translation_cache(self):
        translation = SystemTranslation.objects.create(
            key='test_key', text='Test Text'
        )
        self.assertEqual(translation.key, 'test_key')
        self.assertIn('test_key', str(translation))

    def test_feature_flag_creation(self):
        flag = FeatureFlag.objects.create(
            name='Test Feature', key='test_feature', is_enabled=True
        )
        self.assertEqual(flag.key, 'test_feature')
        self.assertTrue(flag.is_enabled)
        self.assertIn('Test Feature', str(flag))

    def test_feature_flag_context_processor(self):
        FeatureFlag.objects.create(
            name='Sitzplan Modul', key='seating_module', is_enabled=False
        )
        NavigationItem.objects.create(
            title='Sitzplan', url_name='seating_plan', order=1, is_active=True
        )
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('features', response.context)
        self.assertFalse(response.context['features'].get('seating_module'))
        # Ensure seating_plan nav item is filtered out when feature flag is disabled
        nav_titles = [item.title for item in response.context['nav_items']]
        self.assertNotIn('Sitzplan', nav_titles)

    def test_health_check_api(self):
        response = self.client.get(reverse('api_health_check'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'healthy')
        self.assertEqual(data['database'], 'ok')
        self.assertEqual(data['cache'], 'ok')
