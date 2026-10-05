"""Tournament status, roster visibility and organizer registration closure."""
from datetime import timedelta
from html import unescape
import re

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventRegistration
from users.models import User
from tournaments.exceptions import TournamentError, TournamentNotOpenError
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentRegistration
from tournaments.services import TournamentBracketService, TournamentLifecycleService, TournamentRegistrationService


@override_settings(SECURE_SSL_REDIRECT=False)
class TournamentFrontendFeedbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.staff = User.objects.create_user('feedback-orga', is_staff=True)
        cls.guest = User.objects.create_user('feedback-guest')
        cls.event = Event.objects.create(title='Feedback LAN', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=now, end_date=now + timedelta(days=2))
        cls.game = Game.objects.create(name='Feedback game', team_size=2)
        cls.teams = []
        for number, count in enumerate((2, 1)):
            captain = User.objects.create_user(f'feedback-captain-{number}')
            team = Team.objects.create(name=f'Feedback Team {number}', game=cls.game,
                captain=captain, event=cls.event)
            for index in range(count):
                user = captain if index == 0 else User.objects.create_user(f'feedback-member-{number}')
                TeamMember.objects.create(team=team, user=user, status=TeamMember.Status.ACCEPTED)
                EventRegistration.objects.create(user=user, event=cls.event, is_checked_in=True)
            cls.teams.append(team)
        cls.tournament = Tournament.objects.create(title='Feedback Cup', event=cls.event,
            game=cls.game, status=Tournament.Status.REGISTRATION_OPEN,
            roster_rule=Tournament.RosterRule.BY_START,
            registration_start=now - timedelta(hours=1), registration_end=now + timedelta(hours=1))
        for team in cls.teams:
            TournamentRegistration.objects.create(tournament=cls.tournament, team=team)

    def setUp(self):
        cache.clear()
        self.detail_url = reverse('tournament_detail', args=[self.tournament.slug])
        self.close_url = reverse('tournament_close_registration', args=[self.tournament.slug])

    def set_status(self, status, *, generated=False):
        Tournament.objects.filter(pk=self.tournament.pk).update(status=status, is_generated=generated)
        self.tournament.refresh_from_db()

    def header(self, response):
        return response.content.decode().split('<!-- Siegerehrung')[0]

    def test_status_visible_for_guests_members_and_organizers_in_every_state(self):
        for actor in (None, self.guest, self.teams[0].captain, self.staff):
            self.client.force_login(actor) if actor else self.client.logout()
            for status in Tournament.Status.values:
                with self.subTest(actor=actor, status=status):
                    self.set_status(status, generated=status == Tournament.Status.IN_PROGRESS)
                    response = self.client.get(self.detail_url)
                    if status == Tournament.Status.DRAFT and actor != self.staff:
                        self.assertEqual(response.status_code, 404)
                        continue
                    self.assertEqual(response.status_code, 200)
                    badge = re.search(r'<span class="ux-tournament-state".*?</span>', self.header(response), re.S)
                    self.assertIsNotNone(badge)
                    text = unescape(re.sub(r'<[^>]+>', '', badge.group()))
                    self.assertIn('Turnierstatus', text)
                    self.assertIn(self.tournament.get_status_display(), text)

    def test_cancelled_generated_tournament_does_not_offer_registration_or_start(self):
        self.set_status(Tournament.Status.CANCELLED, generated=True)
        for actor in (None, self.teams[0].captain, self.staff):
            self.client.force_login(actor) if actor else self.client.logout()
            response = self.client.get(self.detail_url)
            header = self.header(response)
            self.assertIn('Turnier abgesagt', header)
            self.assertNotIn('Angemeldet mit', header)
            self.assertNotIn('Baum jetzt generieren', header)
            self.assertNotIn('Läuft aktuell', header)
            self.assertNotIn('Jetzt Anmeldung schließen', header)

    def test_certificate_link_visible_only_after_finish_and_only_to_staff(self):
        self.client.force_login(self.staff)
        for status in Tournament.Status.values:
            with self.subTest(status=status):
                self.set_status(status)
                response = self.client.get(self.detail_url)
                if status == Tournament.Status.FINISHED:
                    self.assertContains(response, 'Urkunden gestalten und exportieren')
                else:
                    self.assertNotContains(response, 'Urkunden gestalten und exportieren')
        self.set_status(Tournament.Status.FINISHED)
        self.client.force_login(self.teams[0].captain)
        self.assertNotContains(self.client.get(self.detail_url), 'Urkunden gestalten und exportieren')

    def test_participant_list_labels_full_partial_and_withdrawn_teams(self):
        self.tournament.registrations.filter(team=self.teams[1]).update(is_forfeited=True)
        response = self.client.get(self.detail_url)
        panel = response.content.decode().split('id="tab-teams"')[1].split('<!-- Tab 4:')[0]
        self.assertIn('Anmeldestatus: Angemeldet', panel)
        self.assertIn('Anmeldestatus: Zurückgezogen', panel)
        self.assertIn('Vollzählig', panel)
        self.assertIn('Unvollständig', panel)
        self.assertIn('2/2 bestätigte Spieler', panel)
        self.assertIn('1/2 bestätigte Spieler', panel)

    def test_personal_registration_status_always_includes_current_roster_count(self):
        for team, label, count in ((self.teams[0], 'Vollzählig', '2/2'),
                (self.teams[1], 'Unvollständig', '1/2')):
            self.client.force_login(team.captain)
            response = self.client.get(self.detail_url)
            self.assertIn(label, self.header(response))
            self.assertIn(f'{count} bestätigte Spieler', self.header(response))

    def test_pending_players_do_not_complete_roster_and_membership_changes_refresh_badge(self):
        team = self.teams[1]
        member = User.objects.create_user('feedback-pending')
        membership = TeamMember.objects.create(team=team, user=member, status=TeamMember.Status.PENDING)
        self.client.force_login(team.captain)
        self.assertIn('Unvollständig', self.header(self.client.get(self.detail_url)))
        membership.status = TeamMember.Status.ACCEPTED
        membership.save()
        self.assertIn('Vollzählig', self.header(self.client.get(self.detail_url)))

    def test_empty_and_oversized_rosters_show_invalid_badge(self):
        self.teams[0].memberships.all().delete()
        for index in range(2):
            user = User.objects.create_user(f'feedback-oversized-{index}')
            TeamMember.objects.create(team=self.teams[1], user=user, status=TeamMember.Status.ACCEPTED)
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'Ungültiger Kader', count=2)
        self.assertContains(response, '0/2 bestätigte Spieler')
        self.assertContains(response, '3/2 bestätigte Spieler')

    def test_no_merge_markers_and_complete_metadata_in_tournament_list_and_detail(self):
        for url in (reverse('tournament_list'), self.detail_url):
            response = self.client.get(url)
            for marker in ('<<<<<<<', '>>>>>>>', '9e3d60f'):
                self.assertNotContains(response, marker)
            self.assertNotRegex(response.content.decode(), r'(?m)^=======\s*$')
        response = self.client.get(reverse('tournament_list'))
        self.assertContains(response, timezone.localtime(self.tournament.registration_end).strftime('%d.%m.%Y'))
        self.assertContains(response, 'Anmeldeschluss:', count=1)
        self.assertContains(response, 'Turnierstart:', count=1)
        self.assertContains(response, 'Orga-Team')

    def test_original_link_removed_while_backend_provenance_is_preserved(self):
        edition = Tournament.objects.create(title='Feedback new edition', event=self.event,
            game=self.game, status=Tournament.Status.REGISTRATION_OPEN,
            restarted_from=self.tournament, restart_source_title=self.tournament.title,
            registration_start=self.tournament.registration_start,
            registration_end=self.tournament.registration_end)
        response = self.client.get(reverse('tournament_detail', args=[edition.slug]))
        self.assertNotContains(response, 'Originalturnier:')
        self.assertNotContains(response, f'href="{self.detail_url}"')
        edition.refresh_from_db()
        self.assertEqual(edition.restarted_from_id, self.tournament.pk)
        self.assertEqual(edition.restart_source_title, self.tournament.title)

    def test_close_preserves_teams_and_dates_without_generating_matches(self):
        self.client.force_login(self.staff)
        dates = (self.tournament.registration_start, self.tournament.registration_end)
        ids = list(self.tournament.registrations.values_list('pk', flat=True))
        response = self.client.post(self.close_url, follow=True)
        self.assertRedirects(response, self.detail_url)
        self.assertContains(response, 'Der Turnierstart erfolgt separat.')
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.status, Tournament.Status.REGISTRATION_CLOSED)
        self.assertFalse(self.tournament.is_generated)
        self.assertFalse(self.tournament.matches.exists())
        self.assertEqual(list(self.tournament.registrations.values_list('pk', flat=True)), ids)
        self.assertEqual((self.tournament.registration_start, self.tournament.registration_end), dates)
        self.assertNotContains(response, 'Jetzt Anmeldung schließen')
        self.assertContains(response, 'Baum jetzt generieren')

    def test_close_blocks_new_registrations_and_start_remains_possible_after_filling_roster(self):
        TournamentLifecycleService.close_registration(self.tournament.pk, actor=self.staff)
        new_team = Team.objects.create(name='Feedback late team', game=self.game,
            captain=self.guest, event=self.event)
        TeamMember.objects.create(team=new_team, user=self.guest, status=TeamMember.Status.ACCEPTED)
        with self.assertRaises(TournamentNotOpenError):
            TournamentRegistrationService.register_team(self.tournament.pk, user=self.guest,
                team_id=new_team.pk, actor=self.staff)
        with self.assertRaises(TournamentError):
            TournamentBracketService.generate_bracket(self.tournament.pk, actor=self.staff)
        TeamMember.objects.create(team=self.teams[1], user=self.guest, status=TeamMember.Status.ACCEPTED)
        TournamentBracketService.generate_bracket(self.tournament.pk, actor=self.staff)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.status, Tournament.Status.IN_PROGRESS)

    def test_close_requires_post_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        self.assertEqual(client.get(self.close_url).status_code, 405)
        self.assertEqual(client.post(self.close_url).status_code, 403)
        client.get(self.detail_url)
        response = client.post(self.close_url, {'csrfmiddlewaretoken': client.cookies['csrftoken'].value})
        self.assertEqual(response.status_code, 302)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.status, Tournament.Status.REGISTRATION_CLOSED)

    def test_guest_cannot_close_and_anonymous_post_requires_login(self):
        self.assertEqual(self.client.post(self.close_url).status_code, 302)
        self.client.force_login(self.guest)
        response = self.client.get(self.detail_url)
        self.assertNotContains(response, 'Jetzt Anmeldung schließen')
        self.assertEqual(self.client.post(self.close_url).status_code, 403)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.status, Tournament.Status.REGISTRATION_OPEN)

    def test_assigned_admin_and_support_can_close_without_staff_status(self):
        for field in ('tournament_admin', 'tournament_support'):
            with self.subTest(field=field):
                self.set_status(Tournament.Status.REGISTRATION_OPEN)
                setattr(self.tournament, field, self.guest)
                self.tournament.save()
                self.client.force_login(self.guest)
                self.assertContains(self.client.get(self.detail_url), f'action="{self.close_url}"')
                self.assertEqual(self.client.post(self.close_url).status_code, 302)
                self.tournament.refresh_from_db()
                self.assertEqual(self.tournament.status, Tournament.Status.REGISTRATION_CLOSED)
                setattr(self.tournament, field, None)
                self.tournament.save()

    def test_service_rejects_inactive_deleted_and_unprivileged_accounts(self):
        inactive = User.objects.create_user('feedback-inactive', is_staff=True, is_active=False)
        deleted = User.objects.create_user('feedback-deleted', is_staff=True, deleted_at=timezone.now())
        for actor in (AnonymousUser(), self.guest, inactive, deleted):
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                TournamentLifecycleService.close_registration(self.tournament.pk, actor=actor)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.status, Tournament.Status.REGISTRATION_OPEN)

    def test_close_only_allowed_for_ungenerated_open_tournament(self):
        for status in Tournament.Status.values:
            if status == Tournament.Status.REGISTRATION_OPEN:
                continue
            with self.subTest(status=status):
                self.set_status(status)
                with self.assertRaises(TournamentError):
                    TournamentLifecycleService.close_registration(self.tournament.pk, actor=self.staff)
                self.tournament.refresh_from_db()
                self.assertEqual(self.tournament.status, status)
        self.set_status(Tournament.Status.REGISTRATION_OPEN, generated=True)
        with self.assertRaises(TournamentError):
            TournamentLifecycleService.close_registration(self.tournament.pk, actor=self.staff)

    def test_closure_and_generation_controls_hidden_in_draft_and_terminal_states(self):
        self.client.force_login(self.staff)
        for status in (Tournament.Status.DRAFT, Tournament.Status.CANCELLED, Tournament.Status.FINISHED):
            with self.subTest(status=status):
                self.set_status(status)
                response = self.client.get(self.detail_url)
                self.assertFalse(response.context['can_generate_bracket'])
                self.assertNotContains(response, 'Baum jetzt generieren')
                self.assertNotContains(response, 'Jetzt Anmeldung schließen')
        self.set_status(Tournament.Status.REGISTRATION_OPEN)
        self.assertContains(self.client.get(self.detail_url), 'Jetzt Anmeldung schließen')

    def test_closed_or_expired_event_blocks_closure_and_hides_controls(self):
        self.client.force_login(self.staff)
        for status in (Event.Status.FINISHED, Event.Status.CANCELLED):
            with self.subTest(status=status):
                Event.objects.filter(pk=self.event.pk).update(status=status)
                with self.assertRaises(TournamentError):
                    TournamentLifecycleService.close_registration(self.tournament.pk, actor=self.staff)
                response = self.client.get(self.detail_url)
                self.assertNotContains(response, 'Jetzt Anmeldung schließen')
                self.assertFalse(response.context['can_generate_bracket'])
        Event.objects.filter(pk=self.event.pk).update(status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() - timedelta(days=2),
            end_date=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(TournamentError):
            TournamentLifecycleService.close_registration(self.tournament.pk, actor=self.staff)

    def test_swiss_closure_preserves_roster_and_keeps_round_preview_available(self):
        self.tournament.mode = Tournament.Mode.SWISS
        self.tournament.swiss_rounds = 1
        self.tournament.save()
        self.client.force_login(self.staff)
        response = self.client.post(self.close_url, follow=True)
        self.assertContains(response, 'Runde 1 vorbereiten')
        self.assertFalse(self.tournament.swiss_round_records.exists())
        self.assertFalse(self.tournament.matches.exists())
