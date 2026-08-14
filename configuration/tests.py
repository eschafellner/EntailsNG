from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
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

    def test_general_configuration_ticket_toggle(self):
        from datetime import timedelta
        from django.utils import timezone
        from configuration.models import GeneralConfiguration
        from configuration.services import should_show_onboarding_ticket
        from events.models import Event

        event = Event.objects.create(
            title="Test LAN",
            slug="test-lan",
            is_active=True,
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=3),
        )

        config = GeneralConfiguration.load()
        config.ticket_enabled = False
        config.ticket_days_before_event = 0
        config.save()

        self.assertFalse(should_show_onboarding_ticket(upcoming_event=event))

        config.ticket_enabled = True
        config.save()
        self.assertTrue(should_show_onboarding_ticket(upcoming_event=event))

    def test_general_configuration_days_before_event(self):
        from datetime import timedelta
        from django.utils import timezone
        from configuration.models import GeneralConfiguration
        from configuration.services import should_show_onboarding_ticket
        from events.models import Event

        config = GeneralConfiguration.load()
        config.ticket_days_before_event = 1  # Nur 1 Tag vor Event
        config.save()

        # Event startet in 2 Tagen und 17 Stunden (65 Stunden)
        future_event = Event(
            title="Zukunfts-LAN",
            slug="zukunfts-lan",
            is_active=True,
            start_date=timezone.now() + timedelta(days=2, hours=17),
            end_date=timezone.now() + timedelta(days=4),
        )

        # Ticket darf bei x=1 Tag NICHT angezeigt werden
        self.assertFalse(should_show_onboarding_ticket(upcoming_event=future_event))

    def test_site_customization_themes_and_css_variables(self):
        from configuration.models import SiteCustomization

        custom = SiteCustomization.load()
        self.assertEqual(custom.site_name, 'Entails')
        self.assertEqual(custom.theme_preset, SiteCustomization.ThemePreset.WARM_AMBER)

        amber_vars = custom.get_css_variables()
        self.assertEqual(amber_vars['--signal'], '#f8ab2d')

        # Test switching to Cyberpunk
        custom.theme_preset = SiteCustomization.ThemePreset.CYBERPUNK
        custom.save()
        cyber_vars = custom.get_css_variables()
        self.assertEqual(cyber_vars['--signal'], '#00f0ff')

        # Test custom color override
        custom.primary_color = '#ff00ff'
        custom.save()
        custom_vars = custom.get_css_variables()
        self.assertEqual(custom_vars['--signal'], '#ff00ff')

        # Test UIScale choices
        self.assertEqual(custom.ui_scale, SiteCustomization.UIScale.MEDIUM)
        self.assertEqual(custom_vars['--nav-item-height'], '42px')
        self.assertEqual(custom_vars['--font-base'], '15px')
        self.assertEqual(custom_vars['--card-padding'], '24px')

        custom.ui_scale = SiteCustomization.UIScale.VERY_SMALL
        custom.save()
        xs_vars = custom.get_css_variables()
        self.assertEqual(xs_vars['--nav-item-height'], '36px')
        self.assertEqual(xs_vars['--font-base'], '13px')
        self.assertEqual(xs_vars['--card-padding'], '16px')

        custom.ui_scale = SiteCustomization.UIScale.VERY_LARGE
        custom.save()
        xl_vars = custom.get_css_variables()
        self.assertEqual(xl_vars['--nav-item-height'], '50px')
        self.assertEqual(xl_vars['--font-base'], '17px')
        self.assertEqual(xl_vars['--card-padding'], '32px')



    def test_legal_views(self):
        from configuration.models import SiteCustomization

        custom = SiteCustomization.load()
        custom.impressum_content = '<p>Test Impressum Content</p>'
        custom.datenschutz_content = '<p>Test Datenschutz Content</p>'
        custom.save()

        resp_imp = self.client.get(reverse('impressum'))
        self.assertEqual(resp_imp.status_code, 200)
        self.assertContains(resp_imp, 'Test Impressum Content')

        resp_dat = self.client.get(reverse('datenschutz'))
        self.assertEqual(resp_dat.status_code, 200)
        self.assertContains(resp_dat, 'Test Datenschutz Content')

    def test_expired_ticket_modes(self):
        from datetime import timedelta
        from django.utils import timezone
        from events.models import Event
        from configuration.models import GeneralConfiguration
        from configuration.services import should_show_onboarding_ticket

        # Erstelle abgelaufenes Event
        now = timezone.now()
        past_event = Event.objects.create(
            title="Vergangene LAN",
            start_date=now - timedelta(days=5),
            end_date=now - timedelta(days=2),
            is_active=True
        )

        config = GeneralConfiguration.load()
        
        # Test MODE WORN: Ticket soll angezeigt werden
        config.expired_ticket_mode = GeneralConfiguration.ExpiredTicketMode.WORN
        config.save()
        self.assertTrue(should_show_onboarding_ticket(upcoming_event=past_event))

        # Test MODE HIDE: Ticket soll verborgen werden
        config.expired_ticket_mode = GeneralConfiguration.ExpiredTicketMode.HIDE
        config.save()
        self.assertFalse(should_show_onboarding_ticket(upcoming_event=past_event))

    def test_event_capacity_stats_smart_caching_and_invalidation(self):
        from datetime import timedelta
        from django.utils import timezone
        from events.models import Event
        from seating.models import SeatingPlan, SeatingCell
        from configuration.context_processors import get_event_capacity_stats, CAPACITY_CACHE_KEY_PREFIX
        from django.core.cache import cache

        cache.clear()

        event = Event.objects.create(
            title="Caching LAN",
            slug="caching-lan",
            is_active=True,
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=3),
        )
        plan = SeatingPlan.objects.create(event=event, name="Halle 1", columns=5, rows=5)
        cell = SeatingCell.objects.create(
            plan=plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT, reservation_status=SeatingCell.ReservationStatus.FREE
        )

        stats1 = get_event_capacity_stats(event)
        self.assertEqual(stats1['total_seats'], 1)
        self.assertEqual(stats1['reserved_seats'], 0)
        self.assertIsNotNone(cache.get(f"{CAPACITY_CACHE_KEY_PREFIX}{event.id}"))

        # Ändere den Sitzplatz-Status -> `save()` invalidiert den Cache automatisch
        cell.reservation_status = SeatingCell.ReservationStatus.RESERVED
        cell.save()

        # Cache muss gelöscht und neu berechnet werden
        stats2 = get_event_capacity_stats(event)
        self.assertEqual(stats2['reserved_seats'], 1)
        self.assertEqual(stats2['capacity_percent'], 100)

        # 3. Kachel löschen -> Cache muss invalidiert werden
        cell.delete()
        self.assertIsNone(cache.get(f"{CAPACITY_CACHE_KEY_PREFIX}{event.id}"))
        stats3 = get_event_capacity_stats(event)
        self.assertEqual(stats3['total_seats'], 0)

        # 4. Plan für neues Event klonen -> Cache für neues Event wird initialisiert & invalidiert
        event_new = Event.objects.create(
            title="Cloned LAN",
            slug="cloned-lan",
            is_active=False,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=12),
        )
        plan.clone_for_event(new_event=event_new)
        self.assertIsNone(cache.get(f"{CAPACITY_CACHE_KEY_PREFIX}{event_new.id}"))

    def test_dynamic_debug_mode_toggle(self):
        from django.test import RequestFactory
        from configuration.middleware import DynamicDebugMiddleware
        from configuration.models import GeneralConfiguration

        conf = GeneralConfiguration.load()
        conf.debug_mode = False
        conf.save()

        rf = RequestFactory()
        request = rf.get('/some-error-endpoint/')

        def raising_view(req):
            raise ValueError("Test-Fehler für Debug-Middleware")

        middleware = DynamicDebugMiddleware(raising_view)

        # 1. Bei debug_mode=False liefert process_exception None (Standard 500 Handler greift)
        try:
            raising_view(request)
        except Exception as e:
            res_off = middleware.process_exception(request, e)
            self.assertIsNone(res_off)

        # 2. Bei debug_mode=True liefert process_exception die technische Debug-Response
        conf.debug_mode = True
        conf.save()

        try:
            raising_view(request)
        except Exception as e:
            res_on = middleware.process_exception(request, e)
            self.assertIsNotNone(res_on)
            self.assertEqual(res_on.status_code, 500)
            self.assertIn(b"Test-Fehler", res_on.content)

    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'])
    def test_custom_404_template_rendering_when_debug_false(self):
        response = self.client.get('/tesm')
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')
        self.assertContains(response, 'Seite nicht gefunden', status_code=404)
        self.assertContains(response, '404', status_code=404)






