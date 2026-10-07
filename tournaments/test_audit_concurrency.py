"""PostgreSQL-only regression tests for legacy results and roster mutations."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import Event as ThreadEvent

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connections, transaction
from django.test import Client, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from tournaments.exceptions import TournamentError
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentRegistration, TournamentMatch
from tournaments.services import TournamentBracketService, TournamentMatchService, TournamentRegistrationService, TournamentLifecycleService


@skipUnlessDBFeature('has_select_for_update')
class TournamentAuditConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('audit-lock-orga', is_staff=True)
        now = timezone.now()
        self.event = Event.objects.create(title='Audit locks', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=now, end_date=now+timedelta(days=2))
        self.game = Game.objects.create(name='Audit lock game', team_size=2)
        self.teams = []
        for index in range(3):
            captain = get_user_model().objects.create_user(f'audit-lock-captain-{index}')
            team = Team.objects.create(name=f'Audit lock team {index}', captain=captain, game=self.game, event=self.event)
            TeamMember.objects.create(team=team, user=captain, role=TeamMember.Role.CAPTAIN)
            self.teams.append(team)

    @staticmethod
    def separate_connection(action):
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
                    raise RuntimeError('Audit concurrency test timed out')
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
            return second_future.result(timeout=10)

    def client_for(self, user):
        client = Client()
        client.force_login(user)
        return client

    def roster_rule_tournament(self):
        now = timezone.now()
        tournament = Tournament.objects.create(title='Roster rule race', event=self.event,
            game=self.game, roster_rule=Tournament.RosterRule.ALLOW_INCOMPLETE,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=now, registration_end=now + timedelta(hours=1))
        for team in self.teams:
            TournamentRegistration.objects.create(tournament=tournament, team=team)
        return tournament

    def test_rule_change_blocks_waiting_start_with_partial_rosters(self):
        tournament = self.roster_rule_tournament()
        def tighten():
            tournament.roster_rule = Tournament.RosterRule.STRICT
            tournament.save(update_fields=['roster_rule'])
        with self.assertRaises(TournamentError):
            self.compete(tighten, lambda: TournamentBracketService.generate_bracket(
                tournament.pk, actor=self.staff))
        tournament.refresh_from_db()
        self.assertEqual(tournament.roster_rule, Tournament.RosterRule.STRICT)
        self.assertFalse(tournament.is_generated)
        self.assertFalse(tournament.matches.exists())

    def test_start_freezes_waiting_rule_change_from_stale_instance(self):
        from django.core.exceptions import ValidationError
        tournament = self.roster_rule_tournament()
        def tighten():
            # This instance was loaded before bracket generation began.
            tournament.roster_rule = Tournament.RosterRule.STRICT
            tournament.save(update_fields=['roster_rule'])
        with self.assertRaises(ValidationError):
            self.compete(lambda: TournamentBracketService.generate_bracket(
                tournament.pk, actor=self.staff), tighten)
        tournament.refresh_from_db()
        self.assertEqual(tournament.roster_rule, Tournament.RosterRule.ALLOW_INCOMPLETE)
        self.assertTrue(tournament.is_generated)
        self.assertTrue(tournament.matches.exists())

    def late_registration(self, tournament):
        captain = get_user_model().objects.create_user('closing-lock-captain')
        team = Team.objects.create(name='Closing late team', captain=captain, game=self.game, event=self.event)
        TeamMember.objects.create(team=team, user=captain)
        return lambda: TournamentRegistrationService.register_team(tournament.pk,
            user=captain, team_id=team.pk, actor=self.staff)

    def test_closure_blocks_waiting_registration(self):
        tournament = self.roster_rule_tournament()
        register = self.late_registration(tournament)
        with self.assertRaises(TournamentError):
            self.compete(lambda: TournamentLifecycleService.close_registration(
                tournament.pk, actor=self.staff), register)
        tournament.refresh_from_db()
        self.assertEqual(tournament.status, Tournament.Status.REGISTRATION_CLOSED)
        self.assertEqual(tournament.registrations.count(), 3)
        self.assertFalse(tournament.matches.exists())

    def test_registration_before_closure_is_preserved(self):
        tournament = self.roster_rule_tournament()
        self.compete(self.late_registration(tournament),
            lambda: TournamentLifecycleService.close_registration(tournament.pk, actor=self.staff))
        tournament.refresh_from_db()
        self.assertEqual(tournament.status, Tournament.Status.REGISTRATION_CLOSED)
        self.assertEqual(tournament.registrations.count(), 4)
        self.assertFalse(tournament.is_generated)
        self.assertFalse(tournament.matches.exists())

    def test_parallel_last_league_results_finish_the_tournament(self):
        tournament = Tournament.objects.create(title='Audit parallel league', event=self.event,
            game=self.game, mode=Tournament.Mode.LEAGUE, status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now(), registration_end=timezone.now()+timedelta(hours=1))
        for team in self.teams:
            member = get_user_model().objects.create_user(f'audit-league-member-{team.pk}')
            TeamMember.objects.create(team=team, user=member)
            TournamentRegistration.objects.create(tournament=tournament, team=team)
        TournamentBracketService.generate_bracket(tournament.pk, actor=self.staff)
        first, second, third = tournament.matches.order_by('pk')
        TournamentMatchService.update_match_score(first.pk, 1, 0, actor=self.staff)
        self.compete(lambda: TournamentMatchService.update_match_score(second.pk, 1, 0, actor=self.staff),
            lambda: TournamentMatchService.update_match_score(third.pk, 1, 0, actor=self.staff))
        tournament.refresh_from_db()
        self.assertEqual(tournament.status, Tournament.Status.RESULTS_REVIEW)
        self.assertFalse(tournament.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists())

    def test_parallel_joins_keep_one_team_per_game(self):
        user = get_user_model().objects.create_user('audit-lock-joining')
        first, second = self.client_for(user), self.client_for(user)
        url = reverse('team_join_by_code')
        response = self.compete(lambda: first.post(url, {'invite_code': self.teams[0].invite_code}),
            lambda: second.post(url, {'invite_code': self.teams[1].invite_code}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TeamMember.objects.filter(user=user, status=TeamMember.Status.ACCEPTED).count(), 1)

    def test_parallel_joins_do_not_exceed_team_capacity(self):
        a = get_user_model().objects.create_user('audit-lock-joining-a')
        b = get_user_model().objects.create_user('audit-lock-joining-b')
        first, second = self.client_for(a), self.client_for(b)
        data = {'invite_code': self.teams[0].invite_code}
        url = reverse('team_join_by_code')
        self.compete(lambda: first.post(url, data), lambda: second.post(url, data))
        self.assertEqual(self.teams[0].get_accepted_members().count(), 2)
        self.assertFalse(TeamMember.objects.filter(team=self.teams[0], user=b).exists())

    def test_event_closure_blocks_a_waiting_join(self):
        user = get_user_model().objects.create_user('audit-lock-closed')
        client = self.client_for(user)
        def close_event():
            event = Event.objects.select_for_update().get(pk=self.event.pk)
            event.status = Event.Status.CANCELLED
            event.save(update_fields=['status'])
        self.compete(close_event, lambda: client.post(reverse('team_join_by_code'), {'invite_code': self.teams[0].invite_code}))
        self.assertFalse(TeamMember.objects.filter(user=user).exists())

    def test_roster_change_blocks_a_waiting_organizer_start(self):
        now = timezone.now()
        tournament = Tournament.objects.create(title='Audit roster race', event=self.event, game=self.game,
            mode=Tournament.Mode.SINGLE_ELIMINATION, status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=now-timedelta(hours=1), registration_end=now+timedelta(hours=1))
        members = []
        for team in self.teams[:2]:
            member = get_user_model().objects.create_user(f'audit-race-member-{team.pk}')
            TeamMember.objects.create(team=team, user=member)
            members.append(member)
            TournamentRegistration.objects.create(tournament=tournament, team=team)
        captain_client = self.client_for(self.teams[0].captain)
        with self.assertRaises(TournamentError):
            self.compete(lambda: captain_client.post(reverse('team_kick_member',
                args=[self.teams[0].slug, members[0].pk])),
                lambda: TournamentBracketService.generate_bracket(tournament.pk, actor=self.staff))
        tournament.refresh_from_db()
        self.assertFalse(tournament.is_generated)
        self.assertFalse(tournament.matches.exists())

    def test_parallel_solo_registrations_reactivate_one_team(self):
        user = self.teams[0].captain
        game = Game.objects.create(name='Parallel solo game', team_size=1)
        now = timezone.now()
        old_event = Event.objects.create(title='Previous parallel solo LAN', status=Event.Status.FINISHED,
            start_date=now-timedelta(days=5), end_date=now-timedelta(days=3))
        team = Team.objects.create(name='Parallel solo archive', captain=user, game=game,
            event=old_event, is_solo=True, is_archived=True)
        first, second = [Tournament.objects.create(title=f'Parallel solo {number}', game=game, event=self.event,
            status=Tournament.Status.REGISTRATION_OPEN, registration_start=now-timedelta(hours=1),
            registration_end=now+timedelta(hours=1)) for number in range(2)]
        self.compete(lambda: TournamentRegistrationService.register_team(first.pk, user, actor=self.staff),
            lambda: TournamentRegistrationService.register_team(second.pk, user, actor=self.staff))
        team.refresh_from_db()
        self.assertFalse(team.is_archived)
        self.assertEqual(team.event_id, self.event.pk)
        self.assertEqual(Team.objects.filter(captain=user, game=game).count(), 1)
        self.assertEqual(team.memberships.count(), 1)
        self.assertEqual(team.tournament_registrations.count(), 2)

    def test_solo_reactivation_waits_for_old_tournament_status_change(self):
        user = self.teams[0].captain
        game = Game.objects.create(name='Old solo start game', team_size=1)
        now = timezone.now()
        old_event = Event.objects.create(title='Old solo tournament event', status=Event.Status.REGISTRATION_OPEN,
            start_date=now, end_date=now+timedelta(days=1))
        team = Team.objects.create(name='Old solo start archive', captain=user, game=game,
            event=old_event, is_solo=True, is_archived=True)
        old = Tournament.objects.create(title='Old solo tournament', game=game, event=old_event,
            status=Tournament.Status.FINISHED, registration_start=now-timedelta(hours=1),
            registration_end=now+timedelta(hours=1))
        TournamentRegistration.objects.create(tournament=old, team=team)
        target = Tournament.objects.create(title='New solo tournament', game=game, event=self.event,
            status=Tournament.Status.REGISTRATION_OPEN, registration_start=now-timedelta(hours=1),
            registration_end=now+timedelta(hours=1))
        def start_old():
            Event.objects.select_for_update().get(pk=old_event.pk)
            Tournament.objects.filter(pk=old.pk).update(status=Tournament.Status.IN_PROGRESS, is_generated=True)
        with self.assertRaises(TournamentError):
            self.compete(start_old, lambda: TournamentRegistrationService.register_team(target.pk, user, actor=self.staff))
        team.refresh_from_db()
        self.assertTrue(team.is_archived)
        self.assertEqual(team.event_id, old_event.pk)
        self.assertFalse(target.registrations.exists())
