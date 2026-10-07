"""Exercise round publication races with real PostgreSQL row locks."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import Event as ThreadEvent

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from events.models import Event
from tournaments.exceptions import TournamentError
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentRegistration, TournamentMatch
from tournaments.services import SwissTournamentService, TournamentMatchService


@skipUnlessDBFeature('has_select_for_update')
class SwissConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('swiss-lock-orga', is_staff=True)
        now = timezone.now()
        self.event = Event.objects.create(title='Swiss locks', status=Event.Status.REGISTRATION_OPEN,
            start_date=now + timedelta(days=1), end_date=now + timedelta(days=2))
        game = Game.objects.create(name='Swiss lock game', team_size=1)
        self.tournament = Tournament.objects.create(title='Swiss locks', event=self.event, game=game,
            mode=Tournament.Mode.SWISS, swiss_rounds=2, status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=now - timedelta(hours=2), registration_end=now - timedelta(hours=1))
        for seed in range(1, 5):
            captain = get_user_model().objects.create_user(f'swiss-lock-player-{seed}')
            team = Team.objects.create(name=f'Lock team {seed}', captain=captain, game=game)
            TeamMember.objects.create(team=team, user=captain, role=TeamMember.Role.CAPTAIN)
            TournamentRegistration.objects.create(tournament=self.tournament, team=team, seed=seed)
        SwissTournamentService.publish(self.tournament.pk, actor=self.staff)
        for match in self.tournament.matches.all():
            TournamentMatchService.update_match_score(match.pk, 1, 0, actor=self.staff)
        self.old_match = self.tournament.matches.order_by('match_number').first()
        self.token = SwissTournamentService.preview(self.tournament.pk, actor=self.staff)['token']

    @staticmethod
    def separate_connection(action):
        close_old_connections()
        try:
            return action()
        finally:
            connections.close_all()

    def compete(self, first_action, second_action, expected_exception=None):
        paused, proceed, entered = ThreadEvent(), ThreadEvent(), ThreadEvent()

        def first():
            with transaction.atomic():
                result = first_action()
                paused.set()
                if not proceed.wait(10):
                    raise RuntimeError('Swiss concurrency test timed out')
                return result

        def second():
            entered.set()
            return second_action()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(self.separate_connection, first)
            self.assertTrue(paused.wait(10))
            second_future = pool.submit(self.separate_connection, second)
            self.assertTrue(entered.wait(10))
            try:
                with self.assertRaises(TimeoutError):
                    second_future.result(timeout=0.2)
            finally:
                proceed.set()
            first_future.result(timeout=10)
            if expected_exception:
                with self.assertRaises(expected_exception):
                    second_future.result(timeout=10)
            else:
                second_future.result(timeout=10)

    def publish_next(self):
        return SwissTournamentService.publish(self.tournament.pk, actor=self.staff, token=self.token)

    def correct_previous(self):
        return TournamentMatchService.update_match_score(self.old_match.pk, 0, 1, actor=self.staff, decision_reason='Testkorrektur')

    def test_two_publications_create_exactly_one_round(self):
        self.compete(self.publish_next, self.publish_next, TournamentError)
        self.assertEqual(self.tournament.swiss_round_records.count(), 2)
        self.assertEqual(self.tournament.matches.filter(round_number=2).count(), 2)
        self.assertEqual(self.tournament.swiss_round_records.get(number=2).entries.count(), 4)

    def test_committed_correction_invalidates_waiting_publication(self):
        self.compete(self.correct_previous, self.publish_next, TournamentError)
        self.assertEqual(self.tournament.swiss_round_records.count(), 1)
        self.old_match.refresh_from_db()
        self.assertEqual(self.old_match.winner_id, self.old_match.team2_id)

    def test_committed_publication_blocks_waiting_correction(self):
        self.compete(self.publish_next, self.correct_previous, TournamentError)
        self.old_match.refresh_from_db()
        self.assertEqual(self.old_match.winner_id, self.old_match.team1_id)

    def test_withdrawal_invalidates_waiting_publication(self):
        self.compete(lambda: SwissTournamentService.withdraw(self.tournament.pk, self.old_match.team1_id,
            actor=self.staff), self.publish_next, TournamentError)
        self.assertEqual(self.tournament.swiss_round_records.count(), 1)
        self.assertTrue(self.tournament.registrations.get(team_id=self.old_match.team1_id).is_forfeited)

    def test_parallel_last_results_finish_once_without_losing_results(self):
        self.publish_next()
        a, b = self.tournament.matches.filter(round_number=2).order_by('match_number')
        self.compete(lambda: TournamentMatchService.update_match_score(a.pk, 1, 0, actor=self.staff),
            lambda: TournamentMatchService.update_match_score(b.pk, 1, 0, actor=self.staff))
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.status, Tournament.Status.RESULTS_REVIEW)
        self.assertFalse(self.tournament.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists())
