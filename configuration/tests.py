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

    def test_system_translation_cache(self):
        translation = SystemTranslation.objects.create(
            key='test_key', text='Test Text'
        )
        self.assertEqual(translation.key, 'test_key')
        self.assertIn('test_key', str(translation))

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
        conf.save()
        with override_settings(DEBUG=False):
            request.user = staff_user
            try:
                raising_view(request)
            except Exception as e:
                res_prod = middleware.process_exception(request, e)
                self.assertIsNone(res_prod)

        # 3. Unter DEBUG=True, aber ANONYMEM User: Schutz vor Information Leakage (liefert None)
        with override_settings(DEBUG=True):
            request.user = AnonymousUser()
            try:
                raising_view(request)
            except Exception as e:
                res_anon = middleware.process_exception(request, e)
                self.assertIsNone(res_anon)

            # 4. Unter DEBUG=True, aber NORMALEM User: Schutz vor Information Leakage (liefert None)
            request.user = regular_user
            try:
                raising_view(request)
            except Exception as e:
                res_user = middleware.process_exception(request, e)
                self.assertIsNone(res_user)

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
        SystemTranslation.objects.update_or_create(key='test_override_key', defaults={'text': 'INDIVIDUELLE RESERVIERUNG'})
        t_override = Template('{% t "test_override_key" %}')
        self.assertEqual(t_override.render(Context({})), 'INDIVIDUELLE RESERVIERUNG')

        # 3. Default-Text aus DEFAULT_TEXTS (wenn kein DB Eintrag vorhanden)
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









