"""Regressionen zum QA-Review des Turniermoduls vom 31.10.2026 (B-01 bis B-07)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from configuration.translations import get_translation
from events.models import EventRegistration
from tournaments import test_audit as audit
from tournaments.exceptions import TournamentError
from tournaments.models import Team, TeamMember, Tournament, TournamentMatch, TournamentRegistration
from tournaments.services import (TournamentBracketService, TournamentLifecycleService as Life,
                                  TournamentMatchService as Scores, TournamentRegistrationService as Registration)
from tournaments.services.forfeits import forfeit_team_in_active_tournaments
from tournaments.services.podium import TournamentPodiumService
from tournaments.services.results import result_lock_reason


class QAReviewTests(TestCase):
    setUpTestData = classmethod(audit.TournamentAuditTests.setUpTestData.__func__)
    tournament = audit.TournamentAuditTests.tournament
    start = audit.TournamentAuditTests.start

    def play(self, match, a=2, b=0, **kwargs):
        return Scores.update_match_score(match.pk, a, b, actor=self.staff, **kwargs)

    def play_ready(self, tournament):
        for _ in range(100):
            match = tournament.matches.filter(status=TournamentMatch.Status.READY).order_by('pk').first()
            if not match:
                return
            self.play(match)
        self.fail('Turnier wurde nicht abgeschlossen')

    def withdraw(self, team):
        forfeit_team_in_active_tournaments(team, reason='Rückzug')

    def final(self, tournament):
        return tournament.matches.get(bracket_type=TournamentMatch.BracketType.FINAL)

    # B-01
    def test_organizer_registers_selected_player_in_1v1(self):
        t = self.tournament(count=0)
        player = self.teams[3].captain
        Registration.register_team(t.pk, self.staff, actor=self.staff, player_id=player.pk)
        Registration.register_team(t.pk, self.staff, actor=self.staff, team_id=self.teams[4].pk)
        self.assertEqual(set(t.registrations.values_list('team__captain', flat=True)),
                         {player.pk, self.teams[4].captain_id})
        self.assertFalse(Team.objects.filter(captain=self.staff).exists())

    def test_organizer_registration_via_detail_page_names_selected_team(self):
        t = self.tournament(count=0)
        self.client.force_login(self.staff)
        page = self.client.get(reverse('tournament_detail', args=[t.slug]))
        self.assertIn(self.teams[5].captain, page.context['organizer_players'])
        response = self.client.post(reverse('tournament_register', args=[t.slug]),
                                    {'player_id': self.teams[5].captain_id}, follow=True)
        self.assertContains(response, self.teams[5].name)
        self.assertTrue(t.registrations.filter(team=self.teams[5]).exists())

    def test_players_cannot_register_someone_else(self):
        t = self.tournament(count=0)
        with self.assertRaises(TournamentError):
            Registration.register_team(t.pk, self.teams[0].captain, actor=self.teams[0].captain,
                                       player_id=self.teams[1].captain_id)
        self.assertFalse(t.registrations.exists())
        Registration.register_team(t.pk, self.teams[0].captain, actor=self.teams[0].captain,
                                   team_id=self.teams[0].pk)
        self.assertTrue(t.registrations.filter(team=self.teams[0]).exists())

    # B-02 / B-03
    def test_withdrawn_finalist_keeps_second_place_regardless_of_timing(self):
        for early in (False, True):
            with self.subTest(opponent_known=not early):
                t = self.start()
                semis = list(t.matches.filter(status=TournamentMatch.Status.READY).order_by('match_number'))
                self.play(semis[1])
                if not early:
                    self.play(semis[0])
                finalist = semis[1].__class__.objects.get(pk=semis[1].pk).winner
                self.withdraw(finalist)
                if early:
                    self.play(semis[0])
                final = self.final(t)
                self.assertEqual(final.status, TournamentMatch.Status.COMPLETED)
                self.assertEqual(final.result_type, TournamentMatch.ResultType.WALKOVER)
                self.assertFalse(final.is_bye)
                self.assertEqual(final.loser, finalist)
                Life.confirm_results(t.pk, actor=self.staff)
                t.refresh_from_db()
                podium = TournamentPodiumService.calculate(t)
                self.assertEqual(podium['second'], finalist)
                self.assertNotEqual(podium['first'], finalist)
                self.assertEqual(result_lock_reason(final, t), get_translation('results_final_locked'))

    def test_withdrawn_double_elimination_grand_finalist_keeps_second_place(self):
        t = self.start(Tournament.Mode.DOUBLE_ELIMINATION)
        winners = t.matches.filter(bracket_type=TournamentMatch.BracketType.WINNERS)
        for _ in range(3):
            self.play(winners.filter(status=TournamentMatch.Status.READY).first())
        grand_final = t.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL)
        self.assertIsNone(grand_final.team2_id)
        champion = grand_final.team1
        self.withdraw(champion)
        self.play_ready(t)
        grand_final.refresh_from_db()
        self.assertEqual(grand_final.result_type, TournamentMatch.ResultType.WALKOVER)
        self.assertFalse(t.matches.filter(bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET).exists())
        Life.confirm_results(t.pk, actor=self.staff)
        t.refresh_from_db()
        self.assertEqual(TournamentPodiumService.calculate(t)['second'], champion)

    def test_automatic_byes_are_typed_as_bye(self):
        t = self.start(count=3)
        bye = t.matches.get(is_bye=True)
        self.assertEqual(bye.result_type, TournamentMatch.ResultType.BYE)

    def test_correcting_semifinal_rebuilds_automatic_walkover(self):
        t = self.start()
        semis = list(t.matches.filter(status=TournamentMatch.Status.READY).order_by('match_number'))
        self.play(semis[1])
        self.withdraw(semis[1].__class__.objects.get(pk=semis[1].pk).winner)
        self.play(semis[0])
        self.play(semis[0], 0, 2, decision_reason='Ergebnis vertauscht')
        final = self.final(t)
        semis[0].refresh_from_db()
        self.assertEqual(final.winner, semis[0].winner)
        self.assertEqual(final.result_type, TournamentMatch.ResultType.WALKOVER)

    # B-04
    def test_organizer_can_record_and_correct_walkover(self):
        t = self.start()
        match = t.matches.filter(status=TournamentMatch.Status.READY).first()
        with self.assertRaises(TournamentError):
            self.play(match, 0, 0, winner_id=match.team2_id, walkover=True)
        with self.assertRaises(TournamentError):
            self.play(match, 0, 0, walkover=True, decision_reason='Nichtantreten')
        with self.assertRaises(TournamentError):
            Scores.update_match_score(match.pk, 0, 1, winner_id=match.team2_id, walkover=True,
                                      decision_reason='Nichtantreten', actor=match.team1.captain)
        self.play(match, 0, 0, winner_id=match.team2_id, walkover=True, decision_reason='Nichtantreten')
        match.refresh_from_db()
        self.assertEqual(match.result_type, TournamentMatch.ResultType.WALKOVER)
        self.assertEqual(match.winner_id, match.team2_id)
        self.assertFalse(t.registrations.filter(is_forfeited=True).exists())
        self.assertEqual(result_lock_reason(match, t), '')
        self.play(match, 2, 1, walkover=False, decision_reason='Doch gespielt')
        match.refresh_from_db()
        self.assertEqual(match.result_type, TournamentMatch.ResultType.PLAYED)
        self.assertEqual(match.winner_id, match.team1_id)

    def test_walkover_via_frontend_and_swiss_standings(self):
        from tournaments.services.swiss import SwissStandingService
        t = self.start(Tournament.Mode.SWISS)
        match = t.matches.filter(status=TournamentMatch.Status.READY).first()
        self.client.force_login(self.staff)
        from tournaments.services.results import match_version
        response = self.client.post(reverse('match_update_score', args=[match.pk]), {
            'score_team1': 0, 'score_team2': 0, 'winner_id': match.team1_id, 'walkover': '1',
            'decision_reason': 'Nichtantreten', 'expected_state': match_version(match)})
        self.assertEqual(response.status_code, 200, response.content)
        row = next(r for r in SwissStandingService.calculate(t) if r['team'].pk == match.team1_id)
        self.assertEqual((row['walkovers'], row['played'], row['points']), (1, 0, 3))

    # B-05
    def test_league_with_shared_first_place_shows_placements(self):
        t = self.start(Tournament.Mode.LEAGUE)
        for match in t.matches.all():
            self.play(match, 1, 1)
        Life.confirm_results(t.pk, actor=self.staff)
        self.client.force_login(self.staff)
        page = self.client.get(reverse('tournament_detail', args=[t.slug]))
        self.assertEqual([p['rank'] for p in page.context['shared_placements']], [1, 1, 1, 1])
        self.assertContains(page, get_translation('results_shared_placements'))

    # B-06
    def test_player_in_two_registered_teams_is_rejected_by_name(self):
        players = [get_user_model().objects.create_user(f'dup-player-{n}') for n in range(3)]
        teams = []
        for name, members in (('Dup A', players[:2]), ('Dup B', players[1:])):
            team = Team.objects.create(name=name, game=self.team_game, captain=members[0], event=self.event)
            for user in members:
                TeamMember.objects.create(team=team, user=user,
                    role=TeamMember.Role.CAPTAIN if user == members[0] else TeamMember.Role.MEMBER)
            teams.append(team)
        for user in players:
            EventRegistration.objects.create(user=user, event=self.event, is_checked_in=True)
        t = self.tournament(count=0)
        Tournament.objects.filter(pk=t.pk).update(game=self.team_game)
        Registration.register_team(t.pk, self.staff, team_id=teams[0].pk, actor=self.staff)
        with self.assertRaisesMessage(TournamentError, 'dup-player-1'):
            Registration.register_team(t.pk, self.staff, team_id=teams[1].pk, actor=self.staff)
        TournamentRegistration.objects.create(tournament=t, team=teams[1])
        with self.assertRaisesMessage(TournamentError, 'dup-player-1'):
            TournamentBracketService.generate_bracket(t.pk, actor=self.staff)

    # B-07
    def test_double_elimination_hides_empty_bye_matches(self):
        t = self.start(Tournament.Mode.DOUBLE_ELIMINATION, count=9)
        self.assertTrue(t.matches.filter(is_bye=True, team1__isnull=True, team2__isnull=True).exists())
        self.client.force_login(self.staff)
        page = self.client.get(reverse('tournament_detail', args=[t.slug]))
        for key in ('wb_matches', 'lb_matches', 'match_list_cards'):
            self.assertFalse([m for m in page.context[key] if m.is_bye and not m.team1_id and not m.team2_id], key)
