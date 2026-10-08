"""Real PostgreSQL races at the boundary between read-only drafts and publication."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import Event as ThreadEvent

from django.db import close_old_connections, connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from events.models import Event
from tournaments.exceptions import TournamentError
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentRegistration
from tournaments.services.draws import TournamentDrawService
from tournaments.services.locking import lock_tournament
from tournaments.services.registration import TournamentRegistrationService
from users.models import User


@skipUnlessDBFeature('has_select_for_update')
class DrawConcurrencyTests(TransactionTestCase):
    def setUp(self):
        now = timezone.now()
        self.staff = User.objects.create_superuser('draw-lock-orga')
        self.event = Event.objects.create(title='Draw locks', is_active=True, status=Event.Status.REGISTRATION_OPEN,
            start_date=now, end_date=now + timedelta(days=2))
        self.game = Game.objects.create(name='Draw lock game', team_size=1)
        self.tournament = Tournament.objects.create(title='Draw lock cup', event=self.event, game=self.game,
            status=Tournament.Status.REGISTRATION_OPEN, registration_start=now, registration_end=now + timedelta(hours=1))
        self.teams = []
        for index in range(5):
            captain = User.objects.create_user(f'draw-lock-captain-{index}')
            team = Team.objects.create(name=f'Draw lock team {index}', captain=captain, game=self.game, event=self.event)
            TeamMember.objects.create(team=team, user=captain, status=TeamMember.Status.ACCEPTED, role=TeamMember.Role.CAPTAIN)
            self.teams.append(team)
            if index < 4:
                TournamentRegistration.objects.create(tournament=self.tournament, team=team)
        self.plan = TournamentDrawService.preview(self.tournament.pk, actor=self.staff)

    @staticmethod
    def separate(action):
        close_old_connections()
        try:
            return action()
        finally:
            connections.close_all()

    def compete(self, first_action, second_action):
        paused, proceed, entered = ThreadEvent(), ThreadEvent(), ThreadEvent()
        def first():
            with transaction.atomic():
                result = first_action()
                paused.set()
                if not proceed.wait(10):
                    raise RuntimeError('Draw concurrency test timed out')
                return result
        def second():
            entered.set()
            return second_action()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(self.separate, first)
            self.assertTrue(paused.wait(10))
            second_future = pool.submit(self.separate, second)
            self.assertTrue(entered.wait(10))
            try:
                with self.assertRaises(TimeoutError):
                    second_future.result(timeout=0.2)
            finally:
                proceed.set()
            first_result = first_future.result(timeout=10)
            return first_result, second_future.result(timeout=10)

    def publish(self, token=None):
        return TournamentDrawService.publish(self.tournament.pk, actor=self.staff, token=token or self.plan['token'])

    def test_simultaneous_same_publication_creates_one_draw(self):
        first, second = self.compete(self.publish, self.publish)
        self.assertTrue(first[1])
        self.assertFalse(second[1])
        self.assertEqual(first[0].pk, second[0].pk)
        self.assertEqual(self.tournament.draw_logs.count(), 1)
        self.assertEqual(self.tournament.matches.count(), 3)

    def test_different_drafts_cannot_both_start_the_tournament(self):
        other = TournamentDrawService.preview(self.tournament.pk, actor=self.staff)
        with self.assertRaises(TournamentError):
            self.compete(self.publish, lambda: self.publish(other['token']))
        self.assertEqual(self.tournament.draw_logs.count(), 1)
        self.assertEqual(self.tournament.matches.count(), 3)

    def test_registration_before_publication_invalidates_draft(self):
        team = self.teams[4]
        with self.assertRaisesMessage(TournamentError, 'seit der Vorschau'):
            self.compete(lambda: TournamentRegistrationService.register_team(self.tournament.pk,
                user=team.captain, team_id=team.pk, actor=self.staff), self.publish)
        self.assertEqual(self.tournament.registrations.count(), 5)
        self.assertFalse(self.tournament.matches.exists())
        self.assertFalse(self.tournament.draw_logs.exists())

    def test_publication_blocks_waiting_registration(self):
        team = self.teams[4]
        with self.assertRaises(TournamentError):
            self.compete(self.publish, lambda: TournamentRegistrationService.register_team(self.tournament.pk,
                user=team.captain, team_id=team.pk, actor=self.staff))
        self.assertEqual(self.tournament.registrations.count(), 4)
        self.assertEqual(self.tournament.draw_logs.count(), 1)

    def test_roster_change_before_publication_invalidates_draft(self):
        def change_roster():
            lock_tournament(self.tournament.pk)
            Team.objects.select_for_update().get(pk=self.teams[0].pk)
            TeamMember.objects.filter(team=self.teams[0]).update(status=TeamMember.Status.PENDING)
        with self.assertRaisesMessage(TournamentError, 'seit der Vorschau'):
            self.compete(change_roster, self.publish)
        self.assertFalse(self.tournament.matches.exists())

    def test_event_end_before_publication_blocks_start(self):
        def close_event():
            Event.objects.select_for_update().get(pk=self.event.pk)
            Event.objects.filter(pk=self.event.pk).update(status=Event.Status.FINISHED)
        with self.assertRaises(TournamentError):
            self.compete(close_event, self.publish)
        self.assertFalse(self.tournament.matches.exists())
