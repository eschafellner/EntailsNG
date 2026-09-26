from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.exceptions import ValidationError
from configuration.models import (
    NavigationItem,
    SiteCustomization,
    SystemTranslation,
)


User = get_user_model()


class ConfigurationModelTests(TestCase):

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()
        super().tearDown()

    def test_navigation_item_url(self):
        item = NavigationItem.objects.create(
            title='Sitzplan', url_name='seating_plan', order=1
        )
        self.assertEqual(item.get_url(), '/seating/')

    def test_navigation_item_alias_urls(self):
        """Testet alle Aliasse in ALIAS_MAP."""
        aliases = [
            ('teams', '/tournaments/teams/all/'),
            ('tournaments', '/tournaments/'),
            ('turniere', '/tournaments/'),
            ('clans', '/clans/'),
            ('seating', '/seating/'),
            ('info', '/info/'),
            ('infos', '/info/'),
            ('news', '/news/'),
            ('sponsors', '/sponsoren/'),
            ('sponsoren', '/sponsoren/'),
        ]
        for alias, expected_path in aliases:
            item = NavigationItem(title='Test', url_name=alias, order=1)
            item.clean()  # darf keinen ValidationError werfen
            self.assertEqual(item.get_url(), expected_path, f"Fehler bei Alias: {alias}")

    def test_navigation_item_clean_invalid_url_name(self):
        """Ungültige URL-Namen werden von clean() abgelehnt."""
        item = NavigationItem(title='Ungültig', url_name='invalid_unknown_route')
        with self.assertRaises(ValidationError) as ctx:
            item.clean()
        self.assertIn('url_name', ctx.exception.message_dict)

    def test_navigation_item_clean_and_get_url_with_absolute_path(self):
        """Absolute Pfade und URLs werden von clean() akzeptiert und von get_url() unverändert geliefert."""
        item = NavigationItem(title='Catering', url_name='/info/catering/', order=10)
        item.clean()
        self.assertEqual(item.get_url(), '/info/catering/')

    def test_system_translation_cache(self):
        translation = SystemTranslation.objects.create(
            key='test_key', text='Test Text'
        )
        self.assertEqual(translation.key, 'test_key')
        self.assertIn('test_key', str(translation))

    def test_get_translation_helper(self):
        from configuration.translations import get_translation as gt_module, DEFAULT_TEXTS as dt_module
        from configuration.context_processors import get_translation, DEFAULT_TEXTS

        # Test backward-compatibility re-exports
        self.assertIs(get_translation, gt_module)
        self.assertIs(DEFAULT_TEXTS, dt_module)

        # Test fallback default text
        self.assertEqual(get_translation('unknown_key', 'Fallback {name}', name='Entails'), 'Fallback Entails')
        # Test predefined DEFAULT_TEXTS key with kwargs formatting
        msg = get_translation('msg_team_created', team_name='Alpha', invite_code='1234')
        self.assertEqual(msg, 'Team "Alpha" erfolgreich gegründet! Einladungscode: 1234')
        # Test database override
        with self.captureOnCommitCallbacks(execute=True):
            SystemTranslation.objects.update_or_create(
                key='msg_team_created',
                defaults={'text': 'Team {team_name} gegründet! Code: {invite_code}'}
            )
        msg_custom = get_translation('msg_team_created', team_name='Alpha', invite_code='1234')
        self.assertEqual(msg_custom, 'Team Alpha gegründet! Code: 1234')


    def test_navigation_item_active_toggle_in_context_processor(self):
        """Inaktive Menüpunkte (is_active=False) werden nicht im Frontend gerendert."""
        NavigationItem.objects.create(
            title='Sitzplan Aktiv', url_name='seating_plan', order=1, is_active=True
        )
        NavigationItem.objects.create(
            title='Teams Inaktiv', url_name='team_list', order=2, is_active=False
        )
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        nav_titles = [item.title for item in response.context['nav_items']]
        self.assertIn('Sitzplan Aktiv', nav_titles)
        self.assertNotIn('Teams Inaktiv', nav_titles)

    def test_navigation_visibility_for_guests_users_and_staff_with_shared_cache(self):
        NavigationItem.objects.create(
            title='Öffentlicher Testpunkt', url_name='dashboard', order=1
        )
        NavigationItem.objects.create(
            title='Interner Testpunkt', url_name='profile', order=2,
            visibility=NavigationItem.Visibility.AUTHENTICATED,
        )
        NavigationItem.objects.create(
            title='Medien-Designer intern', url_name='media_template_list', order=3,
            visibility=NavigationItem.Visibility.STAFF,
        )
        regular_user = User.objects.create_user(username='nav_user', password='test-password')
        staff_user = User.objects.create_user(
            username='nav_staff', password='test-password', is_staff=True
        )

        def visible_titles():
            response = self.client.get(reverse('dashboard'))
            self.assertEqual(response.status_code, 200)
            return {item.title for item in response.context['nav_items']}, response

        guest_titles, guest_response = visible_titles()
        self.assertEqual(guest_titles, {'Öffentlicher Testpunkt'})
        self.assertNotContains(guest_response, 'Medien-Designer intern')

        self.client.force_login(regular_user)
        user_titles, user_response = visible_titles()
        self.assertEqual(user_titles, {'Öffentlicher Testpunkt', 'Interner Testpunkt'})
        self.assertNotContains(user_response, 'Medien-Designer intern')

        self.client.force_login(staff_user)
        staff_titles, staff_response = visible_titles()
        self.assertEqual(staff_titles, {
            'Öffentlicher Testpunkt', 'Interner Testpunkt', 'Medien-Designer intern'
        })
        self.assertContains(staff_response, 'Medien-Designer intern')

        self.client.logout()
        guest_titles_again, _ = visible_titles()
        self.assertEqual(guest_titles_again, guest_titles)

    def test_media_designer_navigation_migration_restricts_existing_entries(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection

        media_items = [
            NavigationItem.objects.create(title='Medien', url_name=url_name)
            for url_name in ('media_template_list', '/media-designer/')
        ]
        other_item = NavigationItem.objects.create(title='Öffentlich', url_name='dashboard')

        migration = import_module('configuration.migrations.0020_navigationitem_visibility')
        migration.restrict_media_designer_navigation(
            apps, SimpleNamespace(connection=connection)
        )

        for item in media_items:
            item.refresh_from_db()
            self.assertEqual(item.visibility, NavigationItem.Visibility.STAFF)
        other_item.refresh_from_db()
        self.assertEqual(other_item.visibility, NavigationItem.Visibility.PUBLIC)

    def test_legal_links_rendered_in_desktop_and_mobile_menu(self):
        """Impressum und Datenschutz sind in der Desktop-Sidebar und im mobilen Mehr-Menü vorhanden."""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        # Desktop-Sidebar
        self.assertContains(response, 'class="sidebar-legal"')
        self.assertContains(response, reverse('impressum'))
        self.assertContains(response, reverse('datenschutz'))
        # Mobiles Mehr-Menü
        self.assertContains(response, 'class="mobile-item mobile-more-btn')
        self.assertContains(response, 'id="mobile-menu-overlay"')
        self.assertContains(response, 'class="mobile-modal-item')

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
        config.ticket_requires_login = False
        config.ticket_requires_payment = False
        with self.captureOnCommitCallbacks(execute=True):
            config.save()

        self.assertFalse(should_show_onboarding_ticket(upcoming_event=event))

        config.ticket_enabled = True
        with self.captureOnCommitCallbacks(execute=True):
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
        with self.captureOnCommitCallbacks(execute=True):
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

    def test_general_configuration_ticket_requires_login(self):
        from datetime import timedelta
        from django.utils import timezone
        from configuration.models import GeneralConfiguration
        from configuration.services import should_show_onboarding_ticket
        from events.models import Event

        event = Event.objects.create(
            title="Login-Test LAN",
            slug="login-test-lan",
            is_active=True,
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=3),
        )

        user = User.objects.create_user(username="ticket_tester", password="password")

        config = GeneralConfiguration.load()
        config.ticket_enabled = True
        config.ticket_days_before_event = 0
        config.ticket_requires_login = True
        config.ticket_requires_payment = False
        with self.captureOnCommitCallbacks(execute=True):
            config.save()

        # 1. Anonymer User darf das Ticket nicht sehen
        self.assertFalse(should_show_onboarding_ticket(user=None, upcoming_event=event))

        # 2. Eingeloggter User darf das Ticket sehen
        self.assertTrue(should_show_onboarding_ticket(user=user, upcoming_event=event))

        # 3. HTTP GET: Dashboard als anonymer Benutzer
        resp_anon = self.client.get(reverse('dashboard'))
        self.assertFalse(resp_anon.context['show_onboarding_ticket'])
        self.assertNotContains(resp_anon, 'onboarding-ticket')

        # 4. HTTP GET: Dashboard als angemeldeter Benutzer
        self.client.login(username='ticket_tester', password='password')
        resp_user = self.client.get(reverse('dashboard'))
        self.assertTrue(resp_user.context['show_onboarding_ticket'])
        self.assertContains(resp_user, 'onboarding-ticket')

    def test_general_configuration_ticket_requires_payment(self):
        from datetime import timedelta
        from django.utils import timezone
        from configuration.models import GeneralConfiguration
        from configuration.services import should_show_onboarding_ticket
        from events.models import Event, EventRegistration, TicketType

        event = Event.objects.create(
            title="Payment-Test LAN",
            slug="payment-test-lan",
            is_active=True,
            start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=3),
        )
        ticket = TicketType.objects.create(event=event, name="Normal", price=25.0)
        user = User.objects.create_user(username="pay_tester", password="password")

        config = GeneralConfiguration.load()
        config.ticket_enabled = True
        config.ticket_days_before_event = 0
        config.ticket_requires_login = False
        config.ticket_requires_payment = True
        with self.captureOnCommitCallbacks(execute=True):
            config.save()

        # 1. Anonym -> False
        self.assertFalse(should_show_onboarding_ticket(user=None, upcoming_event=event))

        # 2. Eingeloggt, aber keine Registrierung -> False
        self.assertFalse(should_show_onboarding_ticket(user=user, upcoming_event=event, user_registration=None))

        # 3. Eingeloggt, Registrierung unbezahlt -> False
        reg = EventRegistration.objects.create(
            user=user,
            event=event,
            ticket_type=ticket,
            payment_status=EventRegistration.PaymentStatus.UNPAID,
        )
        self.assertFalse(should_show_onboarding_ticket(user=user, upcoming_event=event, user_registration=reg))

        # 4. Eingeloggt, Registrierung bezahlt -> True
        reg.payment_status = EventRegistration.PaymentStatus.PAID
        reg.save()
        self.assertTrue(should_show_onboarding_ticket(user=user, upcoming_event=event, user_registration=reg))


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

        # Test alle neuen Themes
        for preset in [
            SiteCustomization.ThemePreset.QUAKE_99,
            SiteCustomization.ThemePreset.ARENA_PRO,
            SiteCustomization.ThemePreset.CYBERDECK,
            SiteCustomization.ThemePreset.MAINFRAME,
            SiteCustomization.ThemePreset.DAYLIGHT,
        ]:
            custom.theme_preset = preset
            custom.primary_color = ''
            custom.save()
            vars_dict = custom.get_css_variables()
            self.assertIn('--paper', vars_dict)
            self.assertIn('--panel', vars_dict)
            self.assertIn('--signal', vars_dict)
            self.assertIn('--amber', vars_dict)
            self.assertIn('--ink', vars_dict)
            self.assertIn('--muted', vars_dict)
            self.assertIn('--line', vars_dict)
            self.assertIn('--sidebar-text', vars_dict)
            self.assertIn('--sidebar-nav-text', vars_dict)
            self.assertIn('--sidebar-nav-active-bg', vars_dict)

        # Mainframe (Terminal Green) specific check
        custom.theme_preset = SiteCustomization.ThemePreset.MAINFRAME
        mainframe_vars = custom.get_css_variables()
        self.assertEqual(mainframe_vars['--sidebar-nav-text'], '#4ADE80')
        self.assertEqual(mainframe_vars['--sidebar-nav-active-bg'], '#22C55E')

        # Quake 99 specific check
        custom.theme_preset = SiteCustomization.ThemePreset.QUAKE_99
        self.assertEqual(custom.get_css_variables()['--signal'], '#EA580C')

        # Daylight specific check
        custom.theme_preset = SiteCustomization.ThemePreset.DAYLIGHT
        self.assertEqual(custom.get_css_variables()['--paper'], '#F8FAFC')




    def test_legal_views(self):
        from configuration.models import SiteCustomization

        custom = SiteCustomization.load()
        custom.impressum_content = '<p>Test Impressum Content</p>'
        custom.datenschutz_content = '<p>Test Datenschutz Content</p>'
        with self.captureOnCommitCallbacks(execute=True):
            custom.save()

        resp_imp = self.client.get(reverse('impressum'))
        self.assertEqual(resp_imp.status_code, 200)
        self.assertContains(resp_imp, 'Test Impressum Content')

        resp_dat = self.client.get(reverse('datenschutz'))
        self.assertEqual(resp_dat.status_code, 200)
        self.assertContains(resp_dat, 'Test Datenschutz Content')

    def test_default_datenschutz_content_and_cookie_disclosure(self):
        """Standard-Datenschutzerklärung enthält alle Pflichtangaben inkl. technisch notwendiger Cookies."""
        from configuration.models import SiteCustomization, DEFAULT_DATENSCHUTZ_CONTENT

        custom = SiteCustomization.load()
        custom.datenschutz_content = DEFAULT_DATENSCHUTZ_CONTENT
        with self.captureOnCommitCallbacks(execute=True):
            custom.save()

        resp = self.client.get(reverse('datenschutz'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Prüfe wesentliche rechtliche Inhalte
        self.assertIn('Datenschutzerklärung', content)
        self.assertIn('sessionid', content)
        self.assertIn('csrftoken', content)
        self.assertIn('sessionStorage', content)
        self.assertIn('Verantwortlicher', content)
        self.assertIn('TDDDG', content)
        self.assertIn('Rechte als betroffene Person', content)

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
        with self.captureOnCommitCallbacks(execute=True):
            config.save()
        self.assertTrue(should_show_onboarding_ticket(upcoming_event=past_event))

        # Test MODE HIDE: Ticket soll verborgen werden
        config.expired_ticket_mode = GeneralConfiguration.ExpiredTicketMode.HIDE
        with self.captureOnCommitCallbacks(execute=True):
            config.save()
        self.assertFalse(should_show_onboarding_ticket(upcoming_event=past_event))

    def test_event_capacity_stats_smart_caching_and_invalidation(self):
        from datetime import timedelta
        from django.utils import timezone
        from events.models import Event
        from seating.models import SeatingPlan, SeatingCell
        from seating.services import get_event_capacity_stats, CAPACITY_CACHE_KEY_PREFIX
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

        # Ändere den Sitzplatz-Status -> `save()` invalidiert den Cache automatisch nach Commit
        with self.captureOnCommitCallbacks(execute=True):
            cell.reservation_status = SeatingCell.ReservationStatus.RESERVED
            cell.save()

        # Cache muss gelöscht und neu berechnet werden
        stats2 = get_event_capacity_stats(event)
        self.assertEqual(stats2['reserved_seats'], 1)
        self.assertEqual(stats2['capacity_percent'], 100)

        # 3. Kachel löschen -> Cache muss invalidiert werden
        with self.captureOnCommitCallbacks(execute=True):
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
        with self.captureOnCommitCallbacks(execute=True):
            plan.clone_for_event(new_event=event_new)
        self.assertIsNone(cache.get(f"{CAPACITY_CACHE_KEY_PREFIX}{event_new.id}"))


    def test_dynamic_debug_mode_toggle(self):
        from django.test import RequestFactory, override_settings
        from django.contrib.auth.models import AnonymousUser
        from configuration.middleware import DynamicDebugMiddleware
        from configuration.models import GeneralConfiguration

        conf = GeneralConfiguration.load()
        conf.debug_mode = False
        with self.captureOnCommitCallbacks(execute=True):
            conf.save()

        rf = RequestFactory()
        request = rf.get('/some-error-endpoint/')
        staff_user = User.objects.create_user(username="debug_admin", password="password", is_staff=True)
        regular_user = User.objects.create_user(username="regular_guest", password="password")

        def raising_view(req):
            raise ValueError("Test-Fehler für Debug-Middleware")

        middleware = DynamicDebugMiddleware(raising_view)

        # 1. Bei debug_mode=False liefert process_exception immer None
        request.user = staff_user
        try:
            raising_view(request)
        except Exception as e:
            res_off = middleware.process_exception(request, e)
            self.assertIsNone(res_off)

        # 2. In Produktion (settings.DEBUG=False): selbst bei debug_mode=True und Staff-User -> KEIN Leak (liefert None)
        conf.debug_mode = True
        with self.captureOnCommitCallbacks(execute=True):
            conf.save()
        with override_settings(DEBUG=False):
            request.user = staff_user
            try:
                raising_view(request)
            except Exception as e:
                res_prod = middleware.process_exception(request, e)
                self.assertIsNone(res_prod)

        # 3. Unter DEBUG=True, aber ANONYMEM User: Schutz vor Information Leakage (liefert neutrale 500-Response)
        with override_settings(DEBUG=True):
            request.user = AnonymousUser()
            try:
                raising_view(request)
            except Exception as e:
                res_anon = middleware.process_exception(request, e)
                self.assertIsNotNone(res_anon)
                self.assertEqual(res_anon.status_code, 500)

            # 4. Unter DEBUG=True, aber NORMALEM User: Schutz vor Information Leakage (liefert neutrale 500-Response)
            request.user = regular_user
            try:
                raising_view(request)
            except Exception as e:
                res_user = middleware.process_exception(request, e)
                self.assertIsNotNone(res_user)
                self.assertEqual(res_user.status_code, 500)

            # 5. Unter DEBUG=True UND debug_mode=True UND STAFF-User: liefert technische Debug-Response
            request.user = staff_user
            try:
                raising_view(request)
            except Exception as e:
                res_staff = middleware.process_exception(request, e)
                self.assertIsNotNone(res_staff)
                self.assertEqual(res_staff.status_code, 500)
                self.assertIn(b"Test-Fehler", res_staff.content)

    def test_dynamic_debug_middleware_ignores_404_and_403(self):
        from django.http import Http404
        from django.core.exceptions import PermissionDenied
        from django.test import RequestFactory
        from configuration.middleware import DynamicDebugMiddleware
        rf = RequestFactory()
        request = rf.get('/')
        middleware = DynamicDebugMiddleware(lambda req: None)
        self.assertIsNone(middleware.process_exception(request, Http404("Not found")))
        self.assertIsNone(middleware.process_exception(request, PermissionDenied("Forbidden")))

    @override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver', '127.0.0.1', 'localhost'])
    def test_custom_404_template_rendering_when_debug_false(self):
        response = self.client.get('/tesm')
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, '404.html')
        self.assertContains(response, 'Seite nicht gefunden', status_code=404)
        self.assertContains(response, '404', status_code=404)

    def test_navigation_item_svg_sanitization_positive(self):
        """Positiver Test: Gültiges Vektor-SVG wird anstandslos validiert und gespeichert."""
        valid_svg = '<svg width="20" height="20" viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/></svg>'
        item = NavigationItem(title="Valid Nav", url_name="dashboard", icon_name=NavigationItem.IconChoices.CUSTOM, order=10, icon_svg=valid_svg)
        item.clean()
        item.save()
        self.assertEqual(item.icon_svg, valid_svg)

    def test_navigation_item_uses_system_icons(self):
        """Testet, dass NavigationItem Standard-Icons aus der sicheren System-Icon-Registry rendert."""
        item = NavigationItem(title="Turniere Nav", url_name="dashboard", icon_name=NavigationItem.IconChoices.TOURNAMENTS, order=5)
        item.clean()
        item.save()
        self.assertIn('<svg', item.get_icon_svg())
        self.assertIn('viewBox="0 0 24 24"', item.get_icon_svg())

    def test_navigation_item_svg_sanitization_rejects_script_tag(self):
        """Sicherheitstest: <script> Tags in benutzerdefinierten SVG-Icons werden mit ValidationError blockiert."""
        from django.core.exceptions import ValidationError
        evil_svg = '<svg width="20" height="20"><script>alert("XSS")</script></svg>'
        item = NavigationItem(title="Evil Nav", url_name="dashboard", icon_name=NavigationItem.IconChoices.CUSTOM, order=10, icon_svg=evil_svg)
        with self.assertRaises(ValidationError) as ctx:
            item.clean()
        self.assertIn("Nicht erlaubtes SVG-Tag '<script>'", str(ctx.exception))

    def test_navigation_item_svg_sanitization_rejects_onload_attribute(self):
        """Sicherheitstest: Event-Handler wie onload werden mit ValidationError blockiert."""
        from django.core.exceptions import ValidationError
        evil_svg = '<svg width="20" height="20" onload="alert(1)"><circle cx="10" cy="10" r="5"/></svg>'
        item = NavigationItem(title="Evil Nav 2", url_name="dashboard", icon_name=NavigationItem.IconChoices.CUSTOM, order=10, icon_svg=evil_svg)
        with self.assertRaises(ValidationError) as ctx:
            item.clean()
        self.assertIn("Nicht erlaubtes Attribut 'onload'", str(ctx.exception))

    def test_navigation_item_svg_sanitization_rejects_javascript_uri(self):
        """Sicherheitstest: Gefährliche javascript: URIs werden blockiert."""
        from django.core.exceptions import ValidationError
        evil_svg = '<svg width="20" height="20"><use href="javascript:alert(1)"/></svg>'
        item = NavigationItem(title="Evil Nav 3", url_name="dashboard", icon_name=NavigationItem.IconChoices.CUSTOM, order=10, icon_svg=evil_svg)
        with self.assertRaises(ValidationError) as ctx:
            item.clean()
        self.assertIn("Gefährliche URI", str(ctx.exception))

    def test_navigation_item_svg_sanitization_rejects_doctype_xxe(self):
        """Sicherheitstest: DOCTYPE / XXE Injektionen werden sofort abgewiesen."""
        from django.core.exceptions import ValidationError
        xxe_svg = '<!DOCTYPE svg SYSTEM "http://attacker.com/xxe"><svg width="20" height="20"></svg>'
        item = NavigationItem(title="XXE Nav", url_name="dashboard", icon_name=NavigationItem.IconChoices.CUSTOM, order=10, icon_svg=xxe_svg)
        with self.assertRaises(ValidationError) as ctx:
            item.clean()
        self.assertIn("DOCTYPE", str(ctx.exception))

    def test_html_sanitizer_removes_dangerous_tags_and_events(self):
        """Sicherheitstest: Rechtstexte filtern <script>, <iframe>, onclick und javascript: URIs sicher heraus."""
        from configuration.models import sanitize_html
        dirty = (
            '<h3>Impressum</h3><script>steal()</script>'
            '<p onclick="pwn()">Text <a href="javascript:hack()">Link</a>'
            '<iframe src="http://evil.com"></iframe></p>'
        )
        clean = sanitize_html(dirty)
        self.assertNotIn('<script>', clean)
        self.assertNotIn('<iframe>', clean)
        self.assertNotIn('onclick', clean)
        self.assertNotIn('javascript:hack()', clean)
        self.assertIn('<h3>Impressum</h3>', clean)
        self.assertIn('Text', clean)

    def test_sitecustomization_clean_sanitizes_legal_texts(self):
        """Sicherheitstest: SiteCustomization.clean() bereinigt Impressum und Datenschutz."""
        custom = SiteCustomization.load()
        custom.impressum_content = '<h3>Title</h3><script>alert(1)</script><p>Info</p>'
        custom.datenschutz_content = '<p onmouseover="bad()">Datenschutz <a href="javascript:bad()">Link</a></p>'
        custom.save()
        custom.refresh_from_db()
        self.assertNotIn('<script>', custom.impressum_content)
        self.assertNotIn('onmouseover', custom.datenschutz_content)
        self.assertNotIn('javascript:', custom.datenschutz_content)

    def test_custom_css_validation_rejects_malicious_code(self):
        """Sicherheitstest: Bösartiges CSS (@import, javascript:, expression) wird abgewiesen."""
        from django.core.exceptions import ValidationError
        custom = SiteCustomization.load()
        custom.custom_css = 'body { background: url(javascript:alert(1)); }'
        with self.assertRaises(ValidationError):
            custom.clean()

        custom.custom_css = '@import url("http://evil.com/style.css");'
        with self.assertRaises(ValidationError):
            custom.clean()

    def test_admin_readonly_fields_for_non_superusers(self):
        """
        Sicherheitstest / Privilege Escalation Prevention:
        Staff-Redakteure (is_staff=True, is_superuser=False) haben keinen Schreibzugriff
        auf custom_css, Rechtstexte oder rohes SVG im Django-Admin.
        """
        from django.contrib.admin.sites import AdminSite
        from configuration.admin import SiteCustomizationAdmin, NavigationItemAdmin
        from django.contrib.auth import get_user_model
        from unittest.mock import Mock

        User = get_user_model()
        staff_request = Mock()
        staff_request.user = Mock()
        staff_request.user.is_superuser = False

        admin_site = AdminSite()
        site_admin = SiteCustomizationAdmin(SiteCustomization, admin_site)
        readonly_site = site_admin.get_readonly_fields(staff_request)
        self.assertIn('custom_css', readonly_site)
        self.assertIn('impressum_content', readonly_site)
        self.assertIn('datenschutz_content', readonly_site)

        nav_admin = NavigationItemAdmin(NavigationItem, admin_site)
        readonly_nav = nav_admin.get_readonly_fields(staff_request)
        self.assertIn('icon_svg', readonly_nav)

        # Superuser hat vollen Schreibzugriff auf sensible Felder
        super_request = Mock()
        super_request.user = Mock()
        super_request.user.is_superuser = True
        super_site_readonly = site_admin.get_readonly_fields(super_request)
        self.assertNotIn('custom_css', super_site_readonly)
        self.assertNotIn('impressum_content', super_site_readonly)
        self.assertNotIn('datenschutz_content', super_site_readonly)

        super_nav_readonly = nav_admin.get_readonly_fields(super_request)
        self.assertNotIn('icon_svg', super_nav_readonly)

    def test_translation_template_tag_default_and_override(self):
        """Test für {% t %} Template-Tag mit Default-Werten, DB-Overrides und Fallbacks."""
        from django.template import Context, Template

        # 1. Unbekannter Key mit explizitem Fallback
        t_fallback = Template('{% t "unknown_custom_key" "Mein Fallback" %}')
        self.assertEqual(t_fallback.render(Context({})), 'Mein Fallback')

        # 2. DB-Override über SystemTranslation
        with self.captureOnCommitCallbacks(execute=True):
            SystemTranslation.objects.update_or_create(key='test_override_key', defaults={'text': 'INDIVIDUELLE RESERVIERUNG'})
        t_override = Template('{% t "test_override_key" %}')
        self.assertEqual(t_override.render(Context({})), 'INDIVIDUELLE RESERVIERUNG')

        # 3. Default-Text aus DEFAULT_TEXTS (wenn kein DB Eintrag vorhanden)
        with self.captureOnCommitCallbacks(execute=True):
            SystemTranslation.objects.filter(key='seat_card_title').delete()
        t_default = Template('{% t "seat_card_title" %}')
        self.assertEqual(t_default.render(Context({})), 'SITZPLATZBUCHUNG')

    def test_context_processor_is_lean_without_txt_bloat(self):
        """Testet, dass der Context Processor keine 400 txt_* Keys mehr injiziert."""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        # Sicherstellen, dass keine txt_* Variablen im Context rumliegen
        context_keys = list(response.context.keys())
        txt_keys = [k for k in context_keys if k.startswith('txt_')]
        self.assertEqual(txt_keys, [])
        self.assertNotIn('tr', response.context)
        self.assertNotIn('translations', response.context)
        # Schlanke Kern-Keys sind vorhanden
        self.assertIn('features', response.context)
        self.assertIn('nav_items', response.context)
        self.assertIn('site_customization', response.context)

    def test_iban_validation_valid(self):
        """Gültige IBANs (DE, AT, CH etc.) werden erfolgreich validiert."""
        from configuration.validators import validate_iban
        valid_ibans = [
            'DE89370400440532013000',
            'DE89 3704 0044 0532 0130 00',  # Mit Leerzeichen
            'de89-3704-0044-0532-0130-00',  # Klein & mit Bindestrichen
            'AT611904300234573201',         # Österreich
            'CH9300762011623852957',        # Schweiz
        ]
        for iban in valid_ibans:
            try:
                validate_iban(iban)
            except ValidationError as e:
                self.fail(f"Valide IBAN '{iban}' wurde fälschlicherweise als ungültig abgewiesen: {e}")

    def test_iban_validation_invalid(self):
        """Ungültige IBANs (falsche Prüfziffer, zu kurz, zu lang, unzulässige Zeichen) werfen ValidationError."""
        from configuration.validators import validate_iban
        invalid_ibans = [
            'DE89370400440532013001',  # Falsche Prüfziffer
            'DE12345',                 # Zu kurz
            'DE8937040044053201300012345678901234567',  # Zu lang (>34)
            '12345678901234567890',    # Kein Ländercode
            'DE8937040044053201300!',  # Sonderzeichen
        ]
        for iban in invalid_ibans:
            with self.assertRaises(ValidationError, msg=f"Ungültige IBAN '{iban}' hätte abgelehnt werden müssen"):
                validate_iban(iban)

    def test_bic_validation(self):
        """BIC-Validierung akzeptiert 8 und 11 Zeichen und weist fehlerhafte ab."""
        from configuration.validators import validate_bic
        # Gültig
        validate_bic('GENODEF1S01')
        validate_bic('GENODEF1')
        validate_bic('genodef1s01')
        validate_bic('')  # leer erlaubt

        # Ungültig
        with self.assertRaises(ValidationError):
            validate_bic('SHORT')
        with self.assertRaises(ValidationError):
            validate_bic('TOOLONGBICCODE123')
        with self.assertRaises(ValidationError):
            validate_bic('GENO!EF1')

    def test_general_configuration_payment_fields(self):
        """GeneralConfiguration speichert Zahlungsdaten sauber bereinigt und formatiert die IBAN."""
        from configuration.models import GeneralConfiguration
        config = GeneralConfiguration.load()
        config.kontoinhaber = '  LAN Party e.V.  '
        config.iban = 'DE89 3704 0044 0532 0130 00'
        config.bic = ' genodef1s01 '
        config.clean()
        config.save()

        self.assertTrue(config.has_payment_details)
        self.assertEqual(config.kontoinhaber, 'LAN Party e.V.')
        self.assertEqual(config.iban, 'DE89370400440532013000')
        self.assertEqual(config.bic, 'GENODEF1S01')
        self.assertEqual(config.formatted_iban, 'DE89 3704 0044 0532 0130 00')


class SystemErrorLogTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='err_admin', email='err_admin@example.com', password='password'
        )

    def test_middleware_captures_unhandled_exception(self):
        from configuration.middleware import DynamicDebugMiddleware
        from configuration.models import SystemErrorLog
        from config.urls import custom_500_handler
        from django.test import RequestFactory, override_settings

        rf = RequestFactory()
        request = rf.get('/test-error-endpoint/')
        request.user = self.admin

        middleware = DynamicDebugMiddleware(lambda req: None)
        with override_settings(DEBUG=False):
            response = middleware.process_exception(request, RuntimeError("Test-Systemfehler"))

        self.assertIsNone(response)
        self.assertTrue(hasattr(request, 'system_error_id'))

        log = SystemErrorLog.objects.latest('id')
        self.assertEqual(log.path, '/test-error-endpoint/')
        self.assertEqual(log.exception_type, 'RuntimeError')
        self.assertEqual(log.error_message, 'Test-Systemfehler')
        self.assertEqual(log.user, 'err_admin')
        self.assertFalse(log.resolved)

        # Teste 500-Handler mit Fehler-Referenz
        handler_resp = custom_500_handler(request)
        self.assertEqual(handler_resp.status_code, 500)
        self.assertIn("Fehler-Referenz:", handler_resp.content.decode())
        self.assertIn(f"#{log.id}", handler_resp.content.decode())

    def test_system_error_log_admin_views(self):
        from configuration.models import SystemErrorLog
        log = SystemErrorLog.objects.create(
            path='/admin-error/',
            method='POST',
            exception_type='ValueError',
            error_message='Ungültiger Wert',
            traceback='Traceback (most recent call last):\n  File "foo.py", line 1, in bar',
            user='err_admin',
        )

        self.client.force_login(self.admin)
        resp_list = self.client.get('/admin/configuration/systemerrorlog/')
        self.assertEqual(resp_list.status_code, 200)
        self.assertContains(resp_list, f"#{log.pk}")
        self.assertContains(resp_list, "/admin-error/")

        resp_detail = self.client.get(f'/admin/configuration/systemerrorlog/{log.pk}/change/')
        self.assertEqual(resp_detail.status_code, 200)
        self.assertContains(resp_detail, "Ungültiger Wert")
        self.assertContains(resp_detail, "foo.py")


class CacheResilienceAndFallbackTests(TestCase):
    """
    Tests zur Verifikation der Resilienz bei Redis- und Cache-Ausfällen.
    Stellt sicher, dass bei Cache-Exceptions kontrollierte Fallbacks auf PostgreSQL greifen
    und Seiten nicht mit HTTP 500 abstürzen.
    """

    def test_safe_cache_get_or_set_fallback_on_cache_error(self):
        from unittest.mock import patch
        from configuration.cache import safe_cache_get_or_set

        called = {'count': 0}
        def db_callback():
            called['count'] += 1
            return {'data': 'from_database'}

        with patch('django.core.cache.cache.get', side_effect=Exception("Redis connection refused")), \
             patch('django.core.cache.cache.set', side_effect=Exception("Redis connection refused")):
            res = safe_cache_get_or_set('resilient_key', db_callback, 300)

        self.assertEqual(res, {'data': 'from_database'})
        self.assertEqual(called['count'], 1)

    def test_safe_cache_delete_and_delete_many_survives_cache_error(self):
        from unittest.mock import patch
        from configuration.cache import safe_cache_delete, safe_cache_delete_many

        with patch('django.core.cache.cache.delete', side_effect=Exception("Redis connection refused")), \
             patch('django.core.cache.cache.delete_many', side_effect=Exception("Redis connection refused")):
            # Dürfen keine Exceptions werfen
            safe_cache_delete('any_key')
            safe_cache_delete_many(['key1', 'key2'])

    def test_context_processor_feature_flags_resilient_to_redis_down(self):
        from unittest.mock import patch
        from django.test import RequestFactory
        from configuration.context_processors import feature_flags
        from configuration.models import NavigationItem

        NavigationItem.objects.create(title="Turniere", url_name="/tournaments/", order=1, is_active=True)
        rf = RequestFactory()
        req = rf.get('/')

        with patch('django.core.cache.cache.get', side_effect=Exception("Redis connection refused")), \
             patch('django.core.cache.cache.set', side_effect=Exception("Redis connection refused")):
            ctx = feature_flags(req)

        self.assertIn('nav_items', ctx)
        self.assertTrue(any(item.title == "Turniere" for item in ctx['nav_items']))
        self.assertIsNotNone(ctx['site_customization'])

    def test_general_configuration_and_site_customization_load_fallback(self):
        from unittest.mock import patch
        from configuration.models import GeneralConfiguration, SiteCustomization

        with patch('django.core.cache.cache.get', side_effect=Exception("Redis connection refused")), \
             patch('django.core.cache.cache.set', side_effect=Exception("Redis connection refused")):
            conf = GeneralConfiguration.load()
            custom = SiteCustomization.load()

        self.assertEqual(conf.pk, 1)
        self.assertEqual(custom.pk, 1)

    def test_translations_load_fallback_with_redis_down(self):
        from unittest.mock import patch
        from configuration.translations import get_translation, SystemTranslation

        SystemTranslation.objects.create(key='test_resilient_trans', text='Ausfallsicherer Text')

        with patch('django.core.cache.cache.get', side_effect=Exception("Redis connection refused")), \
             patch('django.core.cache.cache.set', side_effect=Exception("Redis connection refused")):
            trans = get_translation('test_resilient_trans')

        self.assertEqual(trans, 'Ausfallsicherer Text')

    def test_seating_capacity_stats_fallback_with_redis_down(self):
        from unittest.mock import patch
        from datetime import timedelta
        from django.utils import timezone
        from events.models import Event
        from seating.models import SeatingPlan, SeatingCell
        from seating.services import get_event_capacity_stats

        event = Event.objects.create(
            title="Resilience LAN",
            slug="resilience-lan",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        plan = SeatingPlan.objects.create(event=event, name="Haupthalle", columns=10, rows=10)
        SeatingCell.objects.create(
            plan=plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT,
            reservation_status=SeatingCell.ReservationStatus.RESERVED
        )

        with patch('django.core.cache.cache.get', side_effect=Exception("Redis connection refused")), \
             patch('django.core.cache.cache.set', side_effect=Exception("Redis connection refused")):
            stats = get_event_capacity_stats(event)

        self.assertEqual(stats['total_seats'], 1)
        self.assertEqual(stats['reserved_seats'], 1)
        self.assertEqual(stats['capacity_percent'], 100)

    def test_auth_backend_ip_rate_limiting_fails_open(self):
        from unittest.mock import patch
        from users.auth_backends import _is_ip_rate_limited, _record_ip_failed_attempt

        with patch('django.core.cache.cache.get', side_effect=Exception("Redis connection refused")):
            # Bei Ausfall Fail-Open -> False
            self.assertFalse(_is_ip_rate_limited('192.168.1.1'))

        with patch('django.core.cache.cache.add', side_effect=Exception("Redis connection refused")), \
             patch('django.core.cache.cache.incr', side_effect=Exception("Redis connection refused")), \
             patch('django.core.cache.cache.set', side_effect=Exception("Redis connection refused")):
            # Bei Ausfall Fail-Open -> kein Crash, Rückgabe 1
            attempts = _record_ip_failed_attempt('192.168.1.1')
            self.assertEqual(attempts, 1)


class RequestLevelTranslationCacheTests(TestCase):
    """
    Tests für das Request-Level Caching von Übersetzungen (Punkt 1 der Performance-Optimierung).
    Stellt sicher, dass viele {% t %}-Aufrufe innerhalb desselben Requests nur EINEN einzigen
    Cache-Zugriff (Redis) auslösen und Folgeaufrufe aus dem lokalen Request-Speicher bedient werden.
    """

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        SystemTranslation.objects.create(key='test_key_1', text='Text 1')
        SystemTranslation.objects.create(key='test_key_2', text='Text 2')

    def test_20_template_translation_tags_only_read_cache_once_per_request(self):
        from django.template import Template, Context
        from django.test import RequestFactory
        from unittest.mock import patch
        from django.core.cache import cache

        factory = RequestFactory()
        request = factory.get('/')

        # Erstelle ein Template mit 20 {% t %}-Aufrufen
        template_str = "".join([f'{{% t "test_key_{i % 2 + 1}" %}} ' for i in range(20)])
        template = Template(template_str)

        # Zähle Aufrufe von cache.get für den Schlüssel 'system_translations'
        original_get = cache.get
        cache_get_count = 0

        def counting_get(key, *args, **kwargs):
            nonlocal cache_get_count
            if key == 'system_translations':
                cache_get_count += 1
            return original_get(key, *args, **kwargs)

        with patch('django.core.cache.cache.get', side_effect=counting_get):
            context = Context({'request': request})
            rendered = template.render(context)

        # Alle 20 Aufrufe müssen korrekt gerendert worden sein
        self.assertIn('Text 1', rendered)
        self.assertIn('Text 2', rendered)
        # Exakt 1 Cache-Get (für das Wörterbuch), die restlichen 19 Aufrufe kamen aus dem Request-Cache
        self.assertEqual(cache_get_count, 1)

    def test_middleware_request_cache_cleans_up_after_request(self):
        from django.test import RequestFactory
        from configuration.middleware import RequestCacheMiddleware
        from configuration.translations import get_request_cache, get_translation
        from django.http import HttpResponse

        factory = RequestFactory()
        request = factory.get('/')

        middleware = RequestCacheMiddleware(get_response=lambda req: HttpResponse(get_translation('test_key_1')))

        self.assertIsNone(get_request_cache())
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        # Nach Abschluss des Requests muss der Thread-Local Cache bereinigt sein
        self.assertIsNone(get_request_cache())

    def test_python_calls_in_same_request_share_cache(self):
        from configuration.translations import init_request_cache, clear_request_cache, get_translation
        from unittest.mock import patch
        from django.core.cache import cache

        init_request_cache()
        try:
            original_get = cache.get
            cache_get_count = 0

            def counting_get(key, *args, **kwargs):
                nonlocal cache_get_count
                if key == 'system_translations':
                    cache_get_count += 1
                return original_get(key, *args, **kwargs)

            with patch('django.core.cache.cache.get', side_effect=counting_get):
                # 5 Aufrufe hintereinander
                res1 = get_translation('test_key_1')
                res2 = get_translation('test_key_2')
                res3 = get_translation('test_key_1')
                res4 = get_translation('test_key_2')
                res5 = get_translation('test_key_1')

            self.assertEqual(res1, 'Text 1')
            self.assertEqual(res2, 'Text 2')
            self.assertEqual(cache_get_count, 1)
        finally:
            clear_request_cache()


class ConfigurationFeedbackHardeningTests(TestCase):
    """
    Tests zur Verifikation aller 7 Audit-Punkte und strukturellen Verbesserungen:
    - P1: Demo-Reset Berechtigung nur für Superuser
    - P2: Sichere HTML-Bereinigung gegen Entity-Decoding-Bypasses und Idempotenz
    - P3: DynamicDebugMiddleware schützt anonyme & normale Besucher bei DEBUG=True vor Traceback-Leaks
    - P4: Cache-Konsistenz bei Rollback und Bulk-Löschung via Signals & on_commit
    - P5: reset_demo_data Transaktionssicherheit & Fehlerbehandlung
    - P6: seed_features überschreibt keine angepassten Menüpunkte und verhindert Duplikate
    - P7: delete_resolved_logs im Admin löscht nur die übergebene Queryset-Auswahl
    - S2: SiteCustomization.load() ist read-only (keine DB-Writes bei Aufruf)
    - S3: Hex-Farbvalidierung lehnt fehlerhafte Werte ab
    """

    def tearDown(self):
        from django.core.cache import cache
        from configuration.translations import clear_request_cache
        cache.clear()
        clear_request_cache()
        super().tearDown()

    def test_p1_demo_reset_forbidden_for_non_superuser_staff(self):
        """P1: Ein aktiver Mitarbeiter ohne Superuser-Status erhält beim Demo-Reset HTTP 403."""
        from django.contrib.auth import get_user_model
        from unittest.mock import patch

        User = get_user_model()
        staff_user = User.objects.create_user(
            username="staff_only",
            email="staff@example.com",
            password="password",
            is_staff=True,
            is_superuser=False,
        )
        superuser = User.objects.create_superuser(
            username="admin_super",
            email="super@example.com",
            password="password",
        )

        reset_url = reverse('admin:reset_demo_data_admin')

        # 1. Mitarbeiter ohne Superuser-Status: HTTP 403 Forbidden
        self.client.login(username="staff_only", password="password")
        resp_staff = self.client.post(reset_url)
        self.assertEqual(resp_staff.status_code, 403)

        # 2. Superuser darf den Reset ausführen
        self.client.login(username="admin_super", password="password")
        with patch('configuration.admin.call_command') as mock_cmd:
            resp_super = self.client.post(reset_url)
            self.assertEqual(resp_super.status_code, 302)
            mock_cmd.assert_called_once_with('reset_demo_data')

    def test_p2_html_sanitizer_entity_decoding_and_idempotence(self):
        """P2: HTMLSanitizer verhindert Entity-Decoding-Bypasses und arbeitet idempotent."""
        from configuration.sanitizer import sanitize_html

        # 1. Entity-Decoding-Bypass Test: &lt;img ...&gt; darf NICHT in echtes <img> gewandelt werden
        xss_payload = '&lt;img src=x onerror=alert(1)&gt;'
        sanitized = sanitize_html(xss_payload)
        self.assertNotIn('<img', sanitized)
        self.assertIn('&lt;img', sanitized)

        # 2. Idempotenz: Mehrfaches Bereinigen verändert den String nicht erneut
        complex_html = (
            '<h3>Überschrift</h3>\n'
            '<p>Ein Absatz mit <strong>fettem Text</strong>, <em>kursivem Text</em> '
            'und einem <a href="https://example.com" target="_blank" rel="noopener">sicheren Link</a>.</p>'
        )
        first_pass = sanitize_html(complex_html)
        second_pass = sanitize_html(first_pass)
        self.assertEqual(first_pass, second_pass)

        # 3. Gefährliche URL-Schemata werden auf '#' neutralisiert
        bad_links = (
            '<a href="javascript:alert(document.cookie)">JS</a>'
            '<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">Data</a>'
            '<a href="vbscript:msgbox(1)">VBS</a>'
        )
        sanitized_links = sanitize_html(bad_links)
        self.assertNotIn('javascript:', sanitized_links)
        self.assertNotIn('data:', sanitized_links)
        self.assertNotIn('vbscript:', sanitized_links)
        self.assertIn('href="#"', sanitized_links)

    def test_p3_dynamic_debug_middleware_prevents_leaks_on_debug_true(self):
        """P3: Bei DEBUG=True rendert die Middleware für Nicht-Staff neutrale 500-Seiten ohne Traceback-Leaks."""
        from django.test import RequestFactory, override_settings
        from django.contrib.auth.models import AnonymousUser
        from django.contrib.auth import get_user_model
        from configuration.middleware import DynamicDebugMiddleware
        from configuration.models import GeneralConfiguration

        User = get_user_model()
        staff_user = User.objects.create_user(username="dbg_staff", password="password", is_staff=True)
        regular_user = User.objects.create_user(username="dbg_regular", password="password")

        secret_marker = "SUPER_SECRET_INTERNAL_KEY_98765"

        def leaking_view(request):
            raise RuntimeError(f"Database crash with secret {secret_marker}")

        middleware = DynamicDebugMiddleware(leaking_view)
        rf = RequestFactory()
        request = rf.get('/critical-operation/')

        conf = GeneralConfiguration.load()
        conf.debug_mode = True
        with self.captureOnCommitCallbacks(execute=True):
            conf.save()

        with override_settings(DEBUG=True):
            # Anonymer Besucher: Neutrale 500-Seite ohne Secrets
            request.user = AnonymousUser()
            try:
                leaking_view(request)
            except Exception as e:
                resp_anon = middleware.process_exception(request, e)
                self.assertIsNotNone(resp_anon)
                self.assertEqual(resp_anon.status_code, 500)
                self.assertNotIn(secret_marker.encode(), resp_anon.content)

            # Normaler Benutzer: Neutrale 500-Seite ohne Secrets
            request.user = regular_user
            try:
                leaking_view(request)
            except Exception as e:
                resp_reg = middleware.process_exception(request, e)
                self.assertIsNotNone(resp_reg)
                self.assertEqual(resp_reg.status_code, 500)
                self.assertNotIn(secret_marker.encode(), resp_reg.content)

            # Staff-Benutzer mit aktiviertem debug_mode: Technische Debug-Ausgabe mit Traceback
            request.user = staff_user
            try:
                leaking_view(request)
            except Exception as e:
                resp_staff = middleware.process_exception(request, e)
                self.assertIsNotNone(resp_staff)
                self.assertEqual(resp_staff.status_code, 500)
                self.assertIn(secret_marker.encode(), resp_staff.content)

    def test_p4_cache_rollback_and_bulk_delete_invalidation(self):
        """P4: Cache-Invalidierung feuert erst nach Commit und Bulk-Löschungen invalidieren zuverlässig."""
        from django.db import transaction
        from configuration.models import SystemTranslation, NavigationItem
        from configuration.translations import get_translation

        # 1. Rollback-Test: Transaktionsabbruch darf keine unbestätigten Daten im Cache hinterlassen
        try:
            with transaction.atomic():
                SystemTranslation.objects.create(key='test_rollback_key', text='Uncommitted Text')
                # Vor Commit wird ein Rollback provoziert
                raise ValueError("Simulation eines DB-Fehlers")
        except ValueError:
            pass

        # Der unbestätigte Text darf weder in der DB noch im Translation-Cache existieren
        self.assertFalse(SystemTranslation.objects.filter(key='test_rollback_key').exists())
        self.assertEqual(get_translation('test_rollback_key', default='Default Value'), 'Default Value')

        # 2. Bulk-Delete Test: Queryset.delete() invalidiert den Cache über Signals
        with self.captureOnCommitCallbacks(execute=True):
            SystemTranslation.objects.create(key='bulk_target_key', text='Vorheriger Wert')

        # Cache befüllen
        self.assertEqual(get_translation('bulk_target_key'), 'Vorheriger Wert')

        # Massenlöschung durchführen
        with self.captureOnCommitCallbacks(execute=True):
            SystemTranslation.objects.filter(key='bulk_target_key').delete()

        # Cache muss geleert sein -> Liefert Default-Wert
        self.assertEqual(get_translation('bulk_target_key', default='Bereinigt'), 'Bereinigt')

    def test_p5_demo_reset_command_failure_handling(self):
        """P5: Fehler beim Demo-Reset werfen CommandError und Admin meldet Fehler statt Scheinerfolg."""
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from unittest.mock import patch
        from django.contrib.auth import get_user_model

        User = get_user_model()
        superuser = User.objects.create_superuser(
            username="admin_p5",
            email="p5@example.com",
            password="password",
        )

        # 1. Command wirft CommandError bei Fixture-Fehlern
        with patch('configuration.management.commands.reset_demo_data.call_command', side_effect=Exception("Fixture fehlt")):
            with self.assertRaises(CommandError) as ctx:
                call_command('reset_demo_data', stdout=StringIO())
            self.assertIn("Demo-Reset fehlgeschlagen", str(ctx.exception))

        # 2. Admin-Endpunkt fängt den Fehler ab und sendet messages.error
        self.client.login(username="admin_p5", password="password")
        with patch('configuration.admin.call_command', side_effect=Exception("DB-Verbindung unterbrochen")):
            resp = self.client.post(reverse('admin:reset_demo_data_admin'), follow=True)
            self.assertEqual(resp.status_code, 200)
            messages_list = [str(m) for m in resp.context['messages']]
            self.assertTrue(any("Fehler beim Zurücksetzen der Demo-Daten" in m for m in messages_list))

    def test_p6_seed_features_preserves_customizations_without_reset(self):
        """P6: seed_features behält benutzerdefinierte Titel, Reihenfolgen und Status bei, wenn kein --reset übergeben wird."""
        from io import StringIO
        from django.core.management import call_command
        from configuration.models import NavigationItem

        # Initiales Seeding
        call_command('seed_features', stdout=StringIO())

        # Administrator passt Menüpunkt an (z. B. Turniere)
        item = NavigationItem.objects.get(url_name='tournament_list')
        item.title = 'LAN Meisterschaften 2026'
        item.order = 99
        item.is_active = False
        item.visibility = NavigationItem.Visibility.STAFF
        with self.captureOnCommitCallbacks(execute=True):
            item.save()

        # Erneuter Lauf von seed_features ohne --reset
        call_command('seed_features', stdout=StringIO())

        # Anpassungen dürfen nicht überschrieben worden sein
        item.refresh_from_db()
        self.assertEqual(item.title, 'LAN Meisterschaften 2026')
        self.assertEqual(item.order, 99)
        self.assertFalse(item.is_active)
        self.assertEqual(item.visibility, NavigationItem.Visibility.STAFF)
        # Es darf kein Duplikat mit dem alten Namen angelegt worden sein
        self.assertEqual(NavigationItem.objects.filter(url_name='tournament_list').count(), 1)

        # Lauf mit --reset setzt auf Standardwerte zurück
        call_command('seed_features', reset=True, stdout=StringIO())
        item.refresh_from_db()
        self.assertEqual(item.title, 'Turniere')
        self.assertEqual(item.order, 2)
        self.assertTrue(item.is_active)
        self.assertEqual(item.visibility, NavigationItem.Visibility.STAFF)

    def test_p7_delete_resolved_logs_admin_action_scope(self):
        """P7: delete_resolved_logs löscht nur die im Admin ausgewählten gelösten Logs."""
        from configuration.models import SystemErrorLog
        from configuration.admin import SystemErrorLogAdmin
        from django.contrib.admin.sites import AdminSite
        from unittest.mock import Mock

        log1 = SystemErrorLog.objects.create(path="/test1", exception_type="Error", error_message="msg1", resolved=True)
        log2 = SystemErrorLog.objects.create(path="/test2", exception_type="Error", error_message="msg2", resolved=True)
        log3 = SystemErrorLog.objects.create(path="/test3", exception_type="Error", error_message="msg3", resolved=False)

        admin = SystemErrorLogAdmin(SystemErrorLog, AdminSite())
        request = Mock()

        # Nur log1 zur Löschung übergeben
        queryset = SystemErrorLog.objects.filter(id=log1.id)
        admin.delete_resolved_logs(request, queryset)

        # log1 ist gelöscht
        self.assertFalse(SystemErrorLog.objects.filter(id=log1.id).exists())
        # log2 (obwohl resolved) darf NICHT gelöscht worden sein!
        self.assertTrue(SystemErrorLog.objects.filter(id=log2.id).exists())
        # log3 (unresolved) darf NICHT gelöscht worden sein
        self.assertTrue(SystemErrorLog.objects.filter(id=log3.id).exists())

    def test_s2_site_customization_load_is_read_only(self):
        """S2: SiteCustomization.load() führt keine schreibenden DB-Operationen aus."""
        from configuration.models import SiteCustomization

        SiteCustomization.objects.all().delete()
        self.assertEqual(SiteCustomization.objects.count(), 0)

        # Erster Aufruf ohne DB-Datensatz: Liefert In-Memory-Default ohne DB-Speicherung
        custom = SiteCustomization.load()
        self.assertIsNotNone(custom)
        self.assertEqual(SiteCustomization.objects.count(), 0)

        # Nach regulärem Speichern: load() lädt das Objekt unverändert
        with self.captureOnCommitCallbacks(execute=True):
            SiteCustomization.objects.create(primary_color="#123456")
        self.assertEqual(SiteCustomization.objects.count(), 1)
        loaded = SiteCustomization.load()
        self.assertEqual(loaded.primary_color, "#123456")
        self.assertEqual(SiteCustomization.objects.count(), 1)

    def test_s3_validate_hex_color(self):
        """S3: validate_hex_color akzeptiert valide Hex-Codes und weist ungültige Strings ab."""
        from configuration.validators import validate_hex_color
        from django.core.exceptions import ValidationError

        valid_colors = ['#fff', '#FFF', '#123456', '#a1b2c3', '#00000000', '#ffffffff']
        for color in valid_colors:
            try:
                validate_hex_color(color)
            except ValidationError:
                self.fail(f"Gültige Farbe '{color}' wurde fälschlicherweise abgelehnt.")

        invalid_colors = ['red', '123456', '#12', '#1234', '#12345', '#1234567', '#gggggg', 'rgba(0,0,0,1)']
        for color in invalid_colors:
            with self.assertRaises(ValidationError, msg=f"Ungültige Farbe '{color}' wurde nicht abgewiesen"):
                validate_hex_color(color)










