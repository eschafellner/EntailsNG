from concurrent.futures import ThreadPoolExecutor
import tempfile
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from configuration.demo import DemoDataError, seed_demo_data
from configuration.models import DemoDataset, NavigationItem, SystemTranslation
from emails.models import EmailTemplate, GeneralEmailSettings, OutgoingEmail
from events.models import Event
from seating.models import SeatingCell


class DemoEnvironment:
    def setUp(self):
        super().setUp()
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        setting = override_settings(DEMO_MODE=True, BACKUP_ROOT=root.name)
        setting.enable()
        self.addCleanup(setting.disable)


class DemoDataTests(DemoEnvironment, TestCase):
    def test_disabled_before_any_database_access(self):
        with override_settings(DEMO_MODE=False), self.assertNumQueries(0), self.assertRaises(DemoDataError):
            seed_demo_data()

    def test_create_preserve_seeds_and_repeat_without_writes(self):
        admin = get_user_model().objects.create_superuser('own_admin', 'own@example.invalid', 'individual')
        translation = SystemTranslation.objects.create(key='custom_demo_test', text='Mein Text')
        template = EmailTemplate.objects.get(key='payment_confirmation')
        template.subject = 'Eigener Betreff'
        template.save()
        nav = NavigationItem.objects.create(title='Eigenes Menü', url_name='dashboard', icon_svg='<svg></svg>')
        self.assertTrue(seed_demo_data())
        marker = DemoDataset.objects.get()
        event = Event.objects.get()
        self.assertGreater(event.start_date, marker.created_at)
        self.assertFalse(event.is_active)
        self.assertEqual(event.status, Event.Status.DRAFT)
        self.assertEqual(event.ticket_types.get().price, 0)
        self.assertEqual(event.registrations.count(), 4)
        self.assertEqual(SeatingCell.objects.count(), 8)
        guests = get_user_model().objects.exclude(pk=admin.pk)
        self.assertEqual(guests.count(), 4)
        self.assertTrue(all(not u.has_usable_password() and not u.is_staff and not u.is_superuser
                            and u.email.endswith('@example.invalid') for u in guests))
        self.assertFalse(OutgoingEmail.objects.exists())
        self.assertEqual(GeneralEmailSettings.load().transport_mode, 'unconfigured')
        from events.services import EventLifecycleService
        self.assertFalse(EventLifecycleService.registration_readiness(event).can_open)
        with CaptureQueriesContext(connection) as queries:
            self.assertFalse(seed_demo_data())
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for q in queries))
        translation.refresh_from_db(); template.refresh_from_db(); nav.refresh_from_db()
        self.assertEqual(translation.text, 'Mein Text')
        self.assertEqual(template.subject, 'Eigener Betreff')
        self.assertEqual(nav.title, 'Eigenes Menü')
        self.client.force_login(admin)
        for path in ('/admin/', '/media-designer/', '/knowledge/'):
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_existing_guest_refuses_without_touching_customizations(self):
        get_user_model().objects.create_user('real_guest', 'real@example.invalid', None)
        with patch('configuration.demo.call_command') as command, self.assertRaises(DemoDataError):
            seed_demo_data()
        command.assert_not_called()
        self.assertFalse(Event.objects.exists())
        self.assertFalse(DemoDataset.objects.exists())

    def test_existing_domain_data_refuses_even_with_only_superuser(self):
        from tournaments.models import Game
        Game.objects.create(name='Existing')
        with self.assertRaises(DemoDataError):
            seed_demo_data()
        self.assertFalse(DemoDataset.objects.exists())

    def test_failure_rolls_back_data_marker_and_seeds(self):
        def fail():
            get_user_model().objects.create_user('partial', 'partial@example.invalid', None)
            raise RuntimeError('simulated')
        before = NavigationItem.objects.count()
        with patch('configuration.demo._create_objects', side_effect=fail), self.assertRaises(RuntimeError):
            seed_demo_data()
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(DemoDataset.objects.exists())
        self.assertEqual(NavigationItem.objects.count(), before)

    def test_missing_object_and_version_mismatch_fail_without_repair(self):
        seed_demo_data()
        DemoDataset.objects.update(version=99)
        with self.assertRaises(DemoDataError):
            seed_demo_data()
        DemoDataset.objects.update(version=1)
        SeatingCell.objects.first().delete()
        with self.assertRaises(DemoDataError):
            seed_demo_data()
        self.assertEqual(SeatingCell.objects.count(), 7)

    def test_changed_relationship_is_not_silently_adopted(self):
        from tournaments.models import Game, Team
        seed_demo_data()
        different = Game.objects.create(name='Changed')
        Team.objects.update(game=different)
        with self.assertRaises(DemoDataError):
            seed_demo_data()


class DemoConcurrencyTests(DemoEnvironment, TransactionTestCase):
    def test_parallel_initializations_create_one_complete_dataset(self):
        barrier = Barrier(2)

        def initialize():
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return seed_demo_data()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: initialize(), range(2))), [False, True])
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(DemoDataset.objects.count(), 1)
        self.assertFalse(seed_demo_data())
