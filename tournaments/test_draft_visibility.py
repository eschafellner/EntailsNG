"""Internal draft visibility and staff publication through the frontend."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from tournaments.exceptions import TournamentError
from tournaments.models import Game, Tournament
from tournaments.services import TournamentLifecycleService


@override_settings(SECURE_SSL_REDIRECT=False)
class TournamentDraftTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        users = get_user_model()
        cls.guest = users.objects.create_user('draft-guest')
        cls.staff = users.objects.create_user('draft-staff', is_staff=True)
        cls.admin = users.objects.create_superuser('draft-admin', password='test-secret')
        cls.event = Event.objects.create(
            title='Draft LAN', is_active=True, status=Event.Status.REGISTRATION_OPEN,
            start_date=now, end_date=now + timedelta(days=2),
        )
        cls.game = Game.objects.create(name='Draft game', team_size=1)
        cls.draft = Tournament.objects.create(
            title='Internal draft tournament', game=cls.game, event=cls.event,
            registration_start=now - timedelta(hours=1),
            registration_end=now + timedelta(days=1),
        )
        cls.published = Tournament.objects.create(
            title='Public tournament', game=cls.game, event=cls.event,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=now - timedelta(hours=1),
            registration_end=now + timedelta(days=1),
        )

    def setUp(self):
        cache.clear()
        self.list_url = reverse('tournament_list')
        self.detail_url = reverse('tournament_detail', args=[self.draft.slug])
        self.open_url = reverse('tournament_open_registration', args=[self.draft.slug])

    def test_anonymous_visitors_cannot_see_or_open_drafts(self):
        response = self.client.get(self.list_url)
        self.assertContains(response, self.published.title)
        self.assertNotContains(response, self.draft.title)
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)
        self.assertEqual(self.client.post(self.open_url).status_code, 302)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Tournament.Status.DRAFT)

    def test_logged_in_guests_cannot_see_or_open_drafts(self):
        self.client.force_login(self.guest)
        response = self.client.get(self.list_url)
        self.assertContains(response, self.published.title)
        self.assertNotContains(response, self.draft.title)
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)
        self.assertEqual(self.client.post(self.open_url).status_code, 403)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Tournament.Status.DRAFT)

    def test_assigned_guest_directors_and_support_do_not_gain_draft_access(self):
        for field in ('tournament_admin', 'tournament_support'):
            with self.subTest(field=field):
                setattr(self.draft, field, self.guest)
                self.draft.save()
                self.assertTrue(self.draft.is_managed_by(self.guest))
                self.client.force_login(self.guest)
                self.assertNotContains(self.client.get(self.list_url), self.draft.title)
                self.assertEqual(self.client.get(self.detail_url).status_code, 404)
                self.assertEqual(self.client.post(self.open_url).status_code, 403)

    def test_staff_and_superadmins_see_publication_buttons_on_both_pages(self):
        for actor in (self.staff, self.admin):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)
                for url in (self.list_url, self.detail_url):
                    response = self.client.get(url)
                    self.assertContains(response, self.draft.title)
                    self.assertContains(response, f'action="{self.open_url}"')
                    self.assertContains(response, 'Anmeldung für dieses Turnier öffnen')

    def test_guest_and_staff_requests_do_not_share_visibility(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(self.list_url), self.draft.title)
        self.client.logout()
        self.assertNotContains(self.client.get(self.list_url), self.draft.title)
        self.client.force_login(self.guest)
        self.assertNotContains(self.client.get(self.list_url), self.draft.title)
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(self.list_url), self.draft.title)

    def test_all_published_statuses_remain_visible_to_guests(self):
        for status in Tournament.Status:
            if status == Tournament.Status.DRAFT:
                continue
            with self.subTest(status=status):
                self.published.status = status
                self.published.save()
                self.assertContains(self.client.get(self.list_url), self.published.title)
                self.assertEqual(self.client.get(reverse(
                    'tournament_detail', args=[self.published.slug],
                )).status_code, 200)

    def test_staff_can_open_from_list_and_tournament_becomes_public(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.open_url, {'return_to': 'list'}, follow=True)
        self.assertRedirects(response, self.list_url)
        self.assertContains(response, 'Die Anmeldung für &quot;Internal draft tournament&quot; wurde geöffnet.')
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Tournament.Status.REGISTRATION_OPEN)
        self.client.logout()
        self.assertContains(self.client.get(self.list_url), self.draft.title)
        self.assertContains(self.client.get(self.detail_url), self.draft.title)

    def test_superadmin_can_open_from_detail(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.post(self.open_url), self.detail_url)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Tournament.Status.REGISTRATION_OPEN)

    def test_get_does_not_publish(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.open_url).status_code, 405)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Tournament.Status.DRAFT)

    def test_publication_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        self.assertEqual(client.post(self.open_url).status_code, 403)
        client.get(self.list_url)
        response = client.post(self.open_url, {
            'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
        })
        self.assertEqual(response.status_code, 302)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Tournament.Status.REGISTRATION_OPEN)

    def test_service_rejects_guests_and_inactive_or_deleted_staff(self):
        inactive = get_user_model().objects.create_user('draft-inactive', is_staff=True, is_active=False)
        deleted = get_user_model().objects.create_user('draft-deleted', is_staff=True)
        deleted.deleted_at = timezone.now()
        for actor in (AnonymousUser(), self.guest, inactive, deleted):
            with self.subTest(actor=str(actor)):
                with self.assertRaises(PermissionDenied):
                    TournamentLifecycleService.open_registration(self.draft.pk, actor=actor)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Tournament.Status.DRAFT)

    def test_only_drafts_can_be_opened_and_repeated_clicks_are_rejected(self):
        self.client.force_login(self.staff)
        self.client.post(self.open_url)
        response = self.client.post(self.open_url, follow=True)
        self.assertContains(response, 'Nur ein Turnier im Status Entwurf')
        for status in Tournament.Status:
            if status == Tournament.Status.DRAFT:
                continue
            with self.subTest(status=status):
                Tournament.objects.filter(pk=self.draft.pk).update(status=status)
                with self.assertRaises(TournamentError):
                    TournamentLifecycleService.open_registration(self.draft.pk, actor=self.staff)
                self.draft.refresh_from_db()
                self.assertEqual(self.draft.status, status)

    def test_generated_draft_cannot_reopen_registration(self):
        self.draft.is_generated = True
        self.draft.save()
        with self.assertRaises(TournamentError):
            TournamentLifecycleService.open_registration(self.draft.pk, actor=self.staff)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Tournament.Status.DRAFT)

    def test_closed_or_expired_events_block_publication(self):
        for status in (Event.Status.FINISHED, Event.Status.CANCELLED):
            with self.subTest(status=status):
                Event.objects.filter(pk=self.event.pk).update(status=status)
                self.client.force_login(self.staff)
                response = self.client.post(self.open_url, follow=True)
                self.assertContains(response, 'Die Veranstaltung ist beendet oder abgesagt.')
                self.draft.refresh_from_db()
                self.assertEqual(self.draft.status, Tournament.Status.DRAFT)
        Event.objects.filter(pk=self.event.pk).update(
            status=Event.Status.REGISTRATION_OPEN, start_date=timezone.now() - timedelta(days=2),
            end_date=timezone.now() - timedelta(hours=1),
        )
        with self.assertRaises(TournamentError):
            TournamentLifecycleService.open_registration(self.draft.pk, actor=self.staff)

    def test_publication_preserves_registration_dates_and_tournament_settings(self):
        for start, end in (
            (timezone.now() + timedelta(days=2), timezone.now() + timedelta(days=3)),
            (timezone.now() - timedelta(days=2), timezone.now() - timedelta(days=1)),
        ):
            with self.subTest(start=start):
                self.draft.status = Tournament.Status.DRAFT
                self.draft.registration_start, self.draft.registration_end = start, end
                self.draft.save()
                # Draft control must also appear outside the registration window.
                self.client.force_login(self.staff)
                self.assertContains(self.client.get(self.detail_url), f'action="{self.open_url}"')
                TournamentLifecycleService.open_registration(self.draft.pk, actor=self.staff)
                self.draft.refresh_from_db()
                self.assertEqual(self.draft.status, Tournament.Status.REGISTRATION_OPEN)
                self.assertEqual(self.draft.registration_start, start)
                self.assertEqual(self.draft.registration_end, end)
                self.assertFalse(self.draft.is_registration_open)
                self.assertFalse(self.draft.is_generated)

    def test_draft_action_urls_do_not_expose_drafts_to_assigned_guests(self):
        self.draft.mode = Tournament.Mode.SWISS
        self.draft.tournament_admin = self.guest
        self.draft.save()
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(reverse(
            'tournament_swiss_preview', args=[self.draft.slug],
        )).status_code, 404)
        for name in ('tournament_register', 'tournament_unregister', 'tournament_generate_bracket',
                     'tournament_swiss_publish'):
            with self.subTest(name=name):
                self.assertEqual(self.client.post(reverse(name, args=[self.draft.slug])).status_code, 404)

    def test_list_still_uses_only_the_active_event(self):
        other = Event.objects.create(
            title='Other LAN', start_date=timezone.now(), end_date=timezone.now() + timedelta(days=3),
        )
        self.draft.event = other
        self.draft.save()
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(self.list_url), self.draft.title)
        self.assertContains(self.client.get(self.detail_url), self.draft.title)

    def test_no_active_event_returns_empty_list(self):
        self.event.is_active = False
        self.event.save()
        for actor in (self.guest, self.staff):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)
                response = self.client.get(self.list_url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, self.draft.title)
                self.assertNotContains(response, self.published.title)
