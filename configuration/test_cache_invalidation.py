from django.test import TestCase

from .models import GeneralConfiguration, NavigationItem, SiteCustomization, SystemTranslation


class SingleInvalidationTests(TestCase):
    """F-014: Jede Änderung invalidiert ihren Cache genau einmal (über die Signal-Receiver)."""

    def callbacks(self, action):
        with self.captureOnCommitCallbacks() as callbacks:
            action()
        return len(callbacks)

    def test_navigation_and_translations(self):
        item = NavigationItem(title='Cache', url_name='dashboard')
        self.assertEqual(self.callbacks(item.save), 1)
        self.assertEqual(self.callbacks(item.delete), 1)
        text = SystemTranslation(key='cache_test_key', text='x')
        self.assertEqual(self.callbacks(text.save), 1)
        self.assertEqual(self.callbacks(text.delete), 1)

    def test_singletons(self):
        self.assertEqual(self.callbacks(GeneralConfiguration.load().save), 1)
        # Eigener Cache plus Texte und Navigation (Theme-/Textabhängigkeiten).
        self.assertEqual(self.callbacks(SiteCustomization.load().save), 3)
