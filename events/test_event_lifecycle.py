"""Regression tests for organizer closure and post-event access rules."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.forms.models import model_to_dict
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.admin import EventAdminForm
from events.models import Event, EventRegistration, TicketType
from events.services import CheckInService, EventLifecycleService
from emails.models import GeneralEmailSettings
from configuration.models import GeneralConfiguration
from tournaments.exceptions import TournamentNotOpenError
from tournaments.models import Game, Team, Tournament, TournamentRegistration
from tournaments.services import TournamentRegistrationService


class RegistrationReadinessTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.event = Event.objects.create(
            title='Bereitschaft LAN', status=Event.Status.DRAFT, location='Stadthalle',
            start_date=now + timedelta(days=7), end_date=now + timedelta(days=8),
            max_guests=24,
        )
        self.ticket = TicketType.objects.create(
            event=self.event, name='Standard', price=0, is_active=True,
        )
        self.organizer = get_user_model().objects.create_superuser(
            username='readiness_orga', email='readiness@example.test', password='TestPass123!',
        )
        email = GeneralEmailSettings.load()
        email.transport_mode = GeneralEmailSettings.TransportMode.ENV
        email.sender_email = 'tickets@example.test'
        email.is_enabled = True
        email.save()

    def action(self, **extra):
        return {
            'action': 'action_open_registration',
            '_selected_action': [self.event.pk],
            **extra,
        }

    def test_admin_preview_shows_warnings_and_opens_registration(self):
        staff = Client()
        staff.force_login(self.organizer)
        url = reverse('admin:events_event_changelist')
        response = staff.post(url, self.action())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bereitschaftsprüfung')
        self.assertContains(response, 'Sitzplan')
        self.assertContains(response, 'Anmeldung jetzt öffnen')
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.DRAFT)

        response = staff.post(url, self.action(confirm_open='1'))
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.REGISTRATION_OPEN)
        self.assertTrue(self.event.is_active)

    def test_blockers_are_enforced_even_after_preview(self):
        from events.exceptions import EventLifecycleError

        staff = Client()
        staff.force_login(self.organizer)
        url = reverse('admin:events_event_changelist')
        self.assertContains(staff.post(url, self.action()), 'Anmeldung jetzt öffnen')

        self.ticket.price = 10
        self.ticket.save(update_fields=['price'])
        report = EventLifecycleService.registration_readiness(self.event)
        self.assertFalse(report.can_open)
        self.assertTrue(any(c.label == 'Zahlungsdaten' and c.level == 'blocker' for c in report.checks))
        with self.assertRaises(EventLifecycleError):
            EventLifecycleService.open_registration(self.event.pk)
        response = staff.post(url, self.action(confirm_open='1'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Anmeldung jetzt öffnen')
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.DRAFT)

        config = GeneralConfiguration.load()
        config.iban = 'AT611904300234573201'
        config.kontoinhaber = 'LAN Verein'
        config.save()
        self.assertTrue(EventLifecycleService.registration_readiness(self.event).can_open)

    def test_missing_email_and_existing_active_event_block_opening(self):
        email = GeneralEmailSettings.load()
        email.is_enabled = False
        email.save()
        other = Event.objects.create(
            title='Andere LAN', status=Event.Status.RUNNING, is_active=True,
            start_date=timezone.now() - timedelta(hours=1),
            end_date=timezone.now() + timedelta(days=1),
        )
        report = EventLifecycleService.registration_readiness(self.event)
        self.assertEqual(
            {c.label for c in report.checks if c.level == 'blocker'},
            {'Aktive Veranstaltung', 'E-Mail-Versand'},
        )
        self.assertTrue(other.is_active)

    def test_admin_form_cannot_skip_readiness(self):
        form = EventAdminForm(instance=self.event)
        form.cleaned_data = {'status': Event.Status.REGISTRATION_OPEN}
        with self.assertRaises(ValidationError):
            form.clean_status()

    def test_admin_does_not_add_default_ticket_beside_inline_ticket(self):
        staff = Client()
        staff.force_login(self.organizer)
        response = staff.post(reverse('admin:events_event_add'), {
            'title': 'Neue Browser LAN',
            'slug': 'neue-browser-lan',
            'location': 'Turnhalle',
            'start_date_0': '2026-11-01',
            'start_date_1': '18:00:00',
            'end_date_0': '2026-11-03',
            'end_date_1': '10:00:00',
            'max_guests': '20',
            'status': Event.Status.DRAFT,
            'allow_unpaid_seat_overwrite': 'True',
            'ticket_types-TOTAL_FORMS': '1',
            'ticket_types-INITIAL_FORMS': '0',
            'ticket_types-MIN_NUM_FORMS': '0',
            'ticket_types-MAX_NUM_FORMS': '1000',
            'ticket_types-0-name': 'Wochenende',
            'ticket_types-0-price': '0',
            'ticket_types-0-is_active': 'on',
            '_save': 'Sichern',
        })
        self.assertEqual(response.status_code, 302, response.content.decode()[:500])
        new_event = Event.objects.get(slug='neue-browser-lan')
        self.assertEqual(list(new_event.ticket_types.values_list('name', flat=True)), ['Wochenende'])


class EventLifecycleTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.event = Event.objects.create(
            title="Abschluss LAN", status=Event.Status.RUNNING, is_active=True,
            start_date=now - timedelta(hours=2),
            end_date=now + timedelta(days=1),
        )
        self.organizer = get_user_model().objects.create_superuser(
            username="abschluss_orga", email="orga@example.test", password="TestPass123!",
        )
        self.guest = get_user_model().objects.create_user(
            username="abschluss_gast", email="gast@example.test", password="TestPass123!",
        )
        self.registration = EventRegistration.objects.create(
            event=self.event, user=self.guest,
            payment_status=EventRegistration.PaymentStatus.PAID,
            is_checked_in=True,
        )
        self.game = Game.objects.create(name="Abschluss-Duell", team_size=1)
        self.tournament = Tournament.objects.create(
            title="Offener Cup", event=self.event, game=self.game,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=now - timedelta(hours=1),
            registration_end=now + timedelta(hours=1),
        )
        self.team = Team.objects.create(
            name="Abschluss-Team", event=self.event, game=self.game, captain=self.guest,
        )

    def test_admin_requires_finished_tournaments_and_confirmation(self):
        staff = Client()
        staff.force_login(self.organizer)
        url = reverse("admin:events_event_changelist")
        action = {"action": "action_finish_event", "_selected_action": [self.event.pk]}

        preview = staff.post(url, action)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "Offener Cup")
        self.assertNotContains(preview, "Veranstaltung jetzt abschließen")
        rejected = staff.post(url, {**action, "confirm_finish": "1"})
        self.assertEqual(rejected.status_code, 302)
        self.event.refresh_from_db()
        self.team.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.RUNNING)
        self.assertTrue(self.event.is_active)
        self.assertFalse(self.team.is_archived)

        self.tournament.status = Tournament.Status.CANCELLED
        self.tournament.save(update_fields=["status"])
        preview = staff.post(url, action)
        self.assertContains(preview, "Veranstaltung jetzt abschließen")
        self.assertEqual(staff.post(url, {**action, "confirm_finish": "1"}).status_code, 302)
        self.event.refresh_from_db()
        self.team.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.FINISHED)
        self.assertFalse(self.event.is_active)
        self.assertTrue(self.team.is_archived)
        self.assertIsNone(Event.objects.get_active())

        _, archived_again = EventLifecycleService.finish_event(self.event.pk)
        self.assertEqual(archived_again, 0)

    def test_finish_is_atomic_and_admin_form_cannot_bypass_it(self):
        form = EventAdminForm(instance=self.event)
        form.cleaned_data = {"status": Event.Status.FINISHED}
        with self.assertRaises(ValidationError):
            form.clean_status()

        self.tournament.status = Tournament.Status.FINISHED
        self.tournament.save(update_fields=["status"])
        with patch(
            "tournaments.services.registration.archive_teams_for_event",
            side_effect=RuntimeError("archive failed"),
        ):
            with self.assertRaises(RuntimeError):
                EventLifecycleService.finish_event(self.event.pk)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.RUNNING)
        self.assertTrue(self.event.is_active)

    def test_finished_event_cannot_be_reopened_in_admin_form(self):
        self.tournament.status = Tournament.Status.CANCELLED
        self.tournament.save(update_fields=["status"])
        EventLifecycleService.finish_event(self.event.pk)
        self.event.refresh_from_db()

        form = EventAdminForm(instance=self.event)
        form.cleaned_data = {"status": Event.Status.REGISTRATION_OPEN}
        with self.assertRaises(ValidationError):
            form.clean_status()

        data = model_to_dict(self.event)
        data['start_date'] = self.event.start_date.isoformat()
        data['end_date'] = self.event.end_date.isoformat()
        data['is_active'] = True
        form = EventAdminForm(data=data, instance=self.event)
        self.assertFalse(form.is_valid())
        self.assertIn("is_active", form.errors)

    def test_draft_and_cancelled_events_cannot_be_finished(self):
        from events.exceptions import EventLifecycleError

        staff = Client()
        staff.force_login(self.organizer)
        url = reverse("admin:events_event_changelist")
        for status in (Event.Status.DRAFT, Event.Status.CANCELLED):
            self.event.status = status
            self.event.save(update_fields=["status"])
            with self.assertRaises(EventLifecycleError):
                EventLifecycleService.finish_event(self.event.pk)
            response = staff.post(url, {
                "action": "action_finish_event", "_selected_action": [self.event.pk],
            })
            self.assertEqual(response.status_code, 302)
            self.event.refresh_from_db()
            self.assertEqual(self.event.status, status)

    def test_finished_event_rejects_checkin_and_tournament_registration(self):
        self.tournament.status = Tournament.Status.FINISHED
        self.tournament.save(update_fields=["status"])
        EventLifecycleService.finish_event(self.event.pk)

        self.registration.is_checked_in = False
        self.registration.checked_in_at = None
        self.registration.save(update_fields=["is_checked_in", "checked_in_at"])
        result = self.registration.can_check_in()
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "event_finished")
        with self.assertRaises(ValidationError):
            self.registration.check_in()
        with self.assertRaises(ValidationError):
            CheckInService.check_in(self.registration.pk)

        # A mistakenly reopened tournament still cannot accept guests or staff.
        self.tournament.status = Tournament.Status.REGISTRATION_OPEN
        self.tournament.save(update_fields=["status"])
        self.assertFalse(self.tournament.is_registration_open)
        self.assertFalse(self.tournament.can_register()[0])
        for actor in (self.guest, self.organizer):
            with self.assertRaises(TournamentNotOpenError):
                TournamentRegistrationService.register_team(
                    self.tournament.pk, actor, actor=actor,
                )
        self.assertFalse(TournamentRegistration.objects.filter(tournament=self.tournament).exists())
        self.assertFalse(Team.objects.filter(captain=self.organizer).exists())
        guest_browser = Client()
        guest_browser.force_login(self.guest)
        response = guest_browser.post(reverse(
            'tournament_register', kwargs={'slug': self.tournament.slug},
        ))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(TournamentRegistration.objects.filter(tournament=self.tournament).exists())

    def test_expired_active_event_rejects_scanner_and_tournament_registration(self):
        self.event.end_date = timezone.now() - timedelta(minutes=1)
        self.event.save(update_fields=["end_date"])
        self.registration.is_checked_in = False
        self.registration.save(update_fields=["is_checked_in"])

        staff = Client()
        staff.force_login(self.organizer)
        response = staff.post(
            reverse("api_scan_qr"),
            json.dumps({"code": str(self.registration.checkin_token)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "event_finished")
        with self.assertRaises(TournamentNotOpenError):
            TournamentRegistrationService.register_team(self.tournament.pk, self.guest)
