import os
from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from events.admin import EventRegistrationAdmin
from events.models import Event, EventRegistration
from seating.admin import SeatingPlanAdmin
from seating.models import SeatingPlan, SeatingCell

User = get_user_model()


class FrontendAssetAndSecurityPositiveTests(TestCase):
    """
    Positiv-Tests: Überprüft, dass alle statischen Assets korrekt auffindbar sind
    und Views/Admin-Widgets die erwarteten Templates rendern.
    """

    def test_static_assets_are_findable(self):
        """Prüft, ob alle modularisierten CSS- und JS-Dateien vom Staticfiles-Finder gefunden werden."""
        expected_assets = [
            'js/vendor/html5-qrcode.min.js',
            'js/checkin-scanner.js',
            'js/dashboard.js',
            'js/admin-seat-picker.js',
            'js/admin-seat-preview.js',
            'css/dashboard.css',
            'css/checkin-scanner.css',
            'css/admin-seating.css',
        ]
        for asset in expected_assets:
            result = finders.find(asset)
            self.assertIsNotNone(
                result, f"Statisches Asset '{asset}' konnte nicht von staticfiles.finders gefunden werden!"
            )
            self.assertTrue(
                os.path.exists(result), f"Gefundene Datei '{result}' existiert nicht auf dem Dateisystem!"
            )

    def test_checkin_scanner_renders_local_vendor_script(self):
        """Prüft, dass die Scanner-Seite das lokale vendor-Skript einbindet."""
        staff_user = User.objects.create_user(
            username='staff_scanner', email='staff@test.com', password='pw', is_staff=True
        )
        event = Event.objects.create(
            title="Scan Event", slug="scan-event", is_active=True,
            start_date=timezone.now(), end_date=timezone.now() + timezone.timedelta(days=1)
        )
        self.client.force_login(staff_user)
        response = self.client.get(reverse('checkin_scanner'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/static/js/vendor/html5-qrcode.min.js')
        self.assertContains(response, '/static/js/checkin-scanner.js')
        self.assertContains(response, '/static/css/checkin-scanner.css')

    def test_assigned_seat_picker_admin_widget_renders_clean_template(self):
        """Prüft, dass assigned_seat_picker das saubere Admin-Template rendert."""
        user = User.objects.create_user(username='guest_seat', email='guest@test.com', password='pw')
        event = Event.objects.create(
            title="Admin Seat LAN", slug="admin-seat-lan", is_active=True,
            start_date=timezone.now(), end_date=timezone.now() + timezone.timedelta(days=1)
        )
        plan = SeatingPlan.objects.create(event=event, name="Halle A", columns=5, rows=5)
        cell = SeatingCell.objects.create(
            plan=plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT, seat_label="A-01"
        )
        reg = EventRegistration.objects.create(event=event, user=user)
        cell.registration = reg
        cell.save()

        admin_instance = EventRegistrationAdmin(EventRegistration, AdminSite())
        html = admin_instance.assigned_seat_picker(reg)
        self.assertIn("A-01", str(html))
        self.assertIn("openSeatModal", str(html))
        self.assertIn("admin-seat-picker.js", str(html))

    def test_seating_plan_live_preview_admin_widget_renders_clean_template(self):
        """Prüft, dass live_occupancy_preview das saubere Admin-Template rendert."""
        event = Event.objects.create(
            title="Preview LAN", slug="preview-lan", is_active=True,
            start_date=timezone.now(), end_date=timezone.now() + timezone.timedelta(days=1)
        )
        plan = SeatingPlan.objects.create(event=event, name="Preview Halle", columns=4, rows=4)
        SeatingCell.objects.create(
            plan=plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT, seat_label="P-01"
        )

        admin_instance = SeatingPlanAdmin(SeatingPlan, AdminSite())
        html = admin_instance.live_occupancy_preview(plan)
        self.assertIn("seat-preview-container", str(html))
        self.assertIn("admin-seating.css", str(html))
        self.assertIn("admin-seat-preview.js", str(html))


class FrontendNegativeSecurityTests(TestCase):
    """
    Negativ-Tests: Stellt sicher, dass unerwünschte Zustände, Sicherheitsrisiken
    und Code-Smells explizit scheitern und verhindert werden.
    """

    def test_no_unpinned_unpkg_or_insecure_cdn_scripts_in_templates(self):
        """
        Negativ-Test: Stellt sicher, dass keine externen unpkg-CDNs oder ungesicherten
        HTTP-Script-Tags in Templates eingebunden sind (Schutz vor Supply-Chain-Attacken).
        """
        template_dirs = [
            settings.BASE_DIR / 'templates',
            settings.BASE_DIR / 'events' / 'templates',
            settings.BASE_DIR / 'seating' / 'templates',
        ]
        
        forbidden_patterns = ['unpkg.com', 'http://']
        found_violations = []

        for t_dir in template_dirs:
            if not os.path.exists(t_dir):
                continue
            for root, _, files in os.walk(t_dir):
                for f in files:
                    if f.endswith('.html'):
                        filepath = os.path.join(root, f)
                        with open(filepath, 'r', encoding='utf-8') as file_obj:
                            content = file_obj.read()
                            for pat in forbidden_patterns:
                                if f'<script src="{pat}' in content or f"<script src='{pat}" in content or f'src="https://{pat}' in content:
                                    found_violations.append(f"{filepath} enthält verbotenes CDN-Pattern '{pat}'")

        self.assertEqual(
            found_violations, [],
            f"Gefundene unsichere CDN-Skripte in Templates: {found_violations}"
        )

    def test_no_inline_script_tags_in_python_admin_files(self):
        """
        Negativ-Test: Stellt sicher, dass in events/admin.py und seating/admin.py
        keine <script>-Tags mehr in Python-Strings deklariert werden.
        """
        admin_files = [
            settings.BASE_DIR / 'events' / 'admin.py',
            settings.BASE_DIR / 'seating' / 'admin.py',
        ]
        for admin_file in admin_files:
            with open(admin_file, 'r', encoding='utf-8') as f:
                content = f.read()
                self.assertNotIn(
                    '<script>', content,
                    f"Python-Datei '{admin_file}' enthält noch Inline-<script>-Tags in Strings!"
                )
                self.assertNotIn(
                    '</script>', content,
                    f"Python-Datei '{admin_file}' enthält noch Inline-</script>-Tags in Strings!"
                )

    def test_no_inline_script_blocks_in_dashboard_and_scanner_templates(self):
        """
        Negativ-Test: Stellt sicher, dass dashboard.html und checkin_scanner.html
        keine Inline-<script>-Logikblöcke mehr enthalten (nur noch externe <script src="...">).
        """
        import re

        target_templates = [
            settings.BASE_DIR / 'templates' / 'dashboard.html',
            settings.BASE_DIR / 'events' / 'templates' / 'events' / 'checkin_scanner.html',
        ]

        # Matcht <script> Tags, die KEIN src-Attribut besitzen
        inline_script_pattern = re.compile(r'<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>', re.IGNORECASE)

        for tmpl in target_templates:
            with open(tmpl, 'r', encoding='utf-8') as f:
                content = f.read()
                matches = inline_script_pattern.findall(content)
                # Nur nicht-leere Inline-Skripte zählen
                non_empty_matches = [m.strip() for m in matches if m.strip()]
                self.assertEqual(
                    non_empty_matches, [],
                    f"Template '{tmpl}' enthält unerlaubte Inline-<script>-Blöcke!"
                )
