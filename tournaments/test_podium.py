"""Verhalten des gemeinsamen Podium-Services und seiner Detailansicht."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from tournaments.models import (
    Game, Team, Tournament, TournamentMatch, TournamentMatchParticipant,
    TournamentRegistration,
)
from tournaments.services import TournamentPodiumService
from users.models import User


class TournamentPodiumServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.event = Event.objects.create(
            title='Podium LAN', slug='podium-lan',
            start_date=now, end_date=now + timedelta(days=2),
        )
        cls.game = Game.objects.create(name='Podium Game', team_size=1)
        captain = User.objects.create_user(username='podium-captain')
        cls.teams = [
            Team.objects.create(name=f'Podium Team {number}', captain=captain,
                                game=cls.game, event=cls.event)
            for number in range(1, 5)
        ]

    def make_tournament(self, mode):
        now = timezone.now()
        return Tournament.objects.create(
            title=f'Podium {mode}', event=self.event, game=self.game, mode=mode,
            status=Tournament.Status.FINISHED, is_generated=True,
            registration_start=now - timedelta(days=2),
            registration_end=now - timedelta(days=1),
        )

    def assert_podium(self, tournament, expected):
        podium = TournamentPodiumService.calculate(tournament)
        self.assertEqual(tuple(podium.values()), expected)
        return podium

    def test_only_generated_finished_tournaments_have_a_podium(self):
        tournament = self.make_tournament(Tournament.Mode.SINGLE_ELIMINATION)
        TournamentMatch.objects.create(
            tournament=tournament, bracket_type=TournamentMatch.BracketType.FINAL,
            status=TournamentMatch.Status.COMPLETED,
            team1=self.teams[0], team2=self.teams[1],
            winner=self.teams[0], loser=self.teams[1],
        )
        tournament.status = Tournament.Status.IN_PROGRESS
        self.assert_podium(tournament, (None, None, None))
        tournament.status = Tournament.Status.FINISHED
        tournament.is_generated = False
        self.assert_podium(tournament, (None, None, None))

    def test_single_elimination_and_group_stage_preserve_unknown_third_place(self):
        for mode in (Tournament.Mode.SINGLE_ELIMINATION, Tournament.Mode.GROUP_STAGE):
            with self.subTest(mode=mode):
                tournament = self.make_tournament(mode)
                TournamentMatch.objects.create(
                    tournament=tournament, bracket_type=TournamentMatch.BracketType.FINAL,
                    status=TournamentMatch.Status.COMPLETED,
                    team1=self.teams[0], team2=self.teams[1],
                    winner=self.teams[0], loser=self.teams[1],
                )
                self.assert_podium(tournament, (self.teams[0], self.teams[1], None))

    def test_double_elimination_uses_reset_final_and_loser_final(self):
        tournament = self.make_tournament(Tournament.Mode.DOUBLE_ELIMINATION)
        TournamentMatch.objects.create(
            tournament=tournament,
            bracket_type=TournamentMatch.BracketType.GRAND_FINAL,
            status=TournamentMatch.Status.COMPLETED,
            team1=self.teams[0], team2=self.teams[1],
            winner=self.teams[1], loser=self.teams[0],
        )
        TournamentMatch.objects.create(
            tournament=tournament,
            bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET,
            status=TournamentMatch.Status.COMPLETED, round_number=2,
            team1=self.teams[0], team2=self.teams[1],
            winner=self.teams[0], loser=self.teams[1],
        )
        TournamentMatch.objects.create(
            tournament=tournament,
            bracket_type=TournamentMatch.BracketType.LOSERS,
            status=TournamentMatch.Status.COMPLETED, round_number=2,
            team1=self.teams[1], team2=self.teams[2],
            winner=self.teams[1], loser=self.teams[2],
        )
        self.assert_podium(tournament, tuple(self.teams[:3]))

    def test_league_uses_final_standings(self):
        tournament = self.make_tournament(Tournament.Mode.LEAGUE)
        for team in self.teams[:3]:
            TournamentRegistration.objects.create(tournament=tournament, team=team)
        for winner, loser in ((0, 1), (0, 2), (1, 2)):
            TournamentMatch.objects.create(
                tournament=tournament, bracket_type=TournamentMatch.BracketType.GROUP,
                status=TournamentMatch.Status.COMPLETED,
                team1=self.teams[winner], team2=self.teams[loser],
                score_team1=2, score_team2=0, winner=self.teams[winner],
                loser=self.teams[loser],
            )
        self.assert_podium(tournament, tuple(self.teams[:3]))

    def test_ffa_uses_ranked_teams_and_detail_view_uses_service(self):
        tournament = self.make_tournament(Tournament.Mode.FFA)
        match = TournamentMatch.objects.create(
            tournament=tournament, bracket_type=TournamentMatch.BracketType.FFA,
            status=TournamentMatch.Status.COMPLETED,
        )
        for rank, team in enumerate(self.teams[:3], 1):
            TournamentMatchParticipant.objects.create(match=match, team=team, rank=rank)

        expected = tuple(self.teams[:3])
        self.assert_podium(tournament, expected)
        response = self.client.get(reverse('tournament_detail', args=[tournament.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(tuple(response.context['podium'].values()), expected)
