"""Run isolated per-format regressions for the review and subsequent improvements.

Uses Django's disposable test database, never the application's database.
Run: .venv/Scripts/python.exe scripts/tournament_mode_review.py
The six independent suites and machine-readable results are printed/saved.
"""
import json
import os
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch
from datetime import timedelta
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ.setdefault('SECRET_KEY', 'disposable-tournament-mode-review')
os.environ.setdefault('DEBUG', 'True')
os.environ.setdefault('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver')

import django
django.setup()

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.test.runner import DiscoverRunner
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from media_designer.data import certificate_rows
from tournaments.exceptions import TournamentError, SwissPairingError
from tournaments.testing import confirm_results, release_for_match
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentMatch, TournamentRegistration
from tournaments.services import (
    FFAMatchService, TournamentBracketService, TournamentMatchService,
    TournamentPodiumService, SwissPairingService, SwissStandingService,
    SwissTournamentService, LeagueStandingService, forfeit_team_in_active_tournaments,
)


@override_settings(SECURE_SSL_REDIRECT=False)
class FormatAudit(TestCase):
    mode = None

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.staff = get_user_model().objects.create_user('review-orga', is_staff=True)
        cls.guest = get_user_model().objects.create_user('review-outsider')
        cls.event = Event.objects.create(
            title='Disposable audit LAN', is_active=True, status=Event.Status.REGISTRATION_OPEN,
            start_date=now, end_date=now + timedelta(days=3),
        )
        cls.game = Game.objects.create(name='Audit Game', team_size=1)
        cls.teams = []
        for seed in range(1, 33):
            user = get_user_model().objects.create_user(f'review-player-{seed}')
            team = Team.objects.create(name=f'Team {seed:02}', event=cls.event,
                                       game=cls.game, captain=user, is_solo=True)
            TeamMember.objects.create(team=team, user=user, role=TeamMember.Role.CAPTAIN,
                                      status=TeamMember.Status.ACCEPTED)
            cls.teams.append(team)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.staff)

    def make(self, count=4, *, start=True, rounds=3):
        now = timezone.now()
        tournament = Tournament.objects.create(
            title=f'Review {self.mode} {count}', event=self.event, game=self.game, mode=self.mode,
            status=Tournament.Status.REGISTRATION_OPEN, max_teams=32,
            swiss_rounds=min(rounds, count - (count % 2 == 0)),
            registration_start=now - timedelta(hours=2), registration_end=now + timedelta(hours=2),
        )
        for seed, team in enumerate(self.teams[:count], 1):
            TournamentRegistration.objects.create(tournament=tournament, team=team, seed=seed)
        if start:
            self.start(tournament)
        return tournament

    def start(self, tournament):
        if self.mode == Tournament.Mode.SWISS:
            plan = SwissTournamentService.preview(tournament.pk, actor=self.staff)
            SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'])
        else:
            TournamentBracketService.generate_bracket(tournament.pk, actor=self.staff)
        tournament.refresh_from_db()

    def finish(self, tournament, *, random_seed=19):
        rng = random.Random(random_seed)
        if self.mode == Tournament.Mode.FFA:
            match = tournament.matches.get()
            entries = [{'participant_id': p.pk, 'rank': index, 'score': 100 - index}
                       for index, p in enumerate(match.participants.order_by('pk'), 1)]
            FFAMatchService.update_ffa_scores(match.pk, entries, actor=self.staff)
            confirm_results(tournament, self.staff)
            self.assertEqual(tournament.status, Tournament.Status.FINISHED)
            return
        for step in range(2048):
            confirm_results(tournament, self.staff)
            if tournament.status == Tournament.Status.FINISHED:
                break
            ready = list(tournament.matches.filter(status=TournamentMatch.Status.READY, is_bye=False))
            if not ready and self.mode == Tournament.Mode.SWISS:
                self.start(tournament)
                ready = list(tournament.matches.filter(status=TournamentMatch.Status.READY, is_bye=False))
            self.assertTrue(ready, f'Blocked {self.mode}, after {step} results')
            match = rng.choice(ready)
            self.assertIsNotNone(match.team1_id)
            self.assertIsNotNone(match.team2_id)
            self.assertNotEqual(match.team1_id, match.team2_id)
            second_wins = bool(rng.randrange(2))
            if match.bracket_type == TournamentMatch.BracketType.GRAND_FINAL:
                second_wins = True  # Always exercise reset.
            release_for_match(match, self.staff)
            TournamentMatchService.update_match_score(
                match.pk, 0 if second_wins else 2, 2 if second_wins else 0, actor=self.staff,
            )
        self.assertEqual(tournament.status, Tournament.Status.FINISHED)
        self.assertFalse(tournament.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists())

    def test_complete_tournaments_with_varied_fields_and_match_order(self):
        for count in (2, 3, 4, 5, 6, 7, 8, 9, 16):
            if self.mode == Tournament.Mode.GROUP_STAGE and count < 4:
                continue
            with self.subTest(count=count):
                tournament = self.make(count)
                self.finish(tournament, random_seed=count * 31)
                podium = TournamentPodiumService.calculate(tournament)
                if self.mode not in (Tournament.Mode.SWISS, Tournament.Mode.LEAGUE):
                    self.assertIsNotNone(podium['first'])
                elif self.mode == Tournament.Mode.LEAGUE:
                    self.assertTrue(any(row['rank'] == 1 for row in LeagueStandingService.calculate_league_standings(tournament)))
                matches = tournament.matches.filter(is_bye=False)
                if self.mode == Tournament.Mode.LEAGUE:
                    self.assertEqual(matches.count(), count * (count - 1) // 2)
                    pairs = {frozenset((m.team1_id, m.team2_id)) for m in matches}
                    self.assertEqual(len(pairs), matches.count())
                if self.mode == Tournament.Mode.DOUBLE_ELIMINATION:
                    losses = {team.pk: 0 for team in self.teams[:count]}
                    for match in matches:
                        losses[match.loser_id] += 1
                    self.assertEqual(losses[podium['first'].pk], 1)
                    self.assertTrue(all(n == 2 for team_id, n in losses.items()
                                        if team_id != podium['first'].pk))
                if self.mode == Tournament.Mode.SWISS:
                    self.assertEqual(tournament.swiss_round_records.count(), tournament.swiss_rounds)
                    pairs = [tuple(sorted((m.team1_id, m.team2_id))) for m in matches]
                    self.assertEqual(len(pairs), len(set(pairs)))

    def test_unauthorized_start_and_scoring_are_rejected(self):
        tournament = self.make(start=False)
        with self.assertRaises(TournamentError):
            TournamentBracketService.generate_bracket(tournament.pk, actor=self.guest)
        self.assertFalse(tournament.matches.exists())
        self.start(tournament)
        match = tournament.matches.filter(status=TournamentMatch.Status.READY).first()
        with self.assertRaises(TournamentError):
            if self.mode == Tournament.Mode.FFA:
                FFAMatchService.update_ffa_scores(match.pk, [{}], actor=self.guest)
            else:
                TournamentMatchService.update_match_score(match.pk, 1, 0, actor=self.guest)
        match.refresh_from_db()
        self.assertEqual(match.status, TournamentMatch.Status.READY)

    def test_invalid_results_are_atomic_and_event_end_blocks_results(self):
        tournament = self.make()
        match = tournament.matches.filter(status=TournamentMatch.Status.READY).first()
        before = list(tournament.matches.values())
        with self.assertRaises(TournamentError):
            if self.mode == Tournament.Mode.FFA:
                entries = [{'participant_id': p.pk, 'rank': 1, 'score': 1}
                           for p in match.participants.all()]
                FFAMatchService.update_ffa_scores(match.pk, entries, actor=self.staff)
            else:
                TournamentMatchService.update_match_score(match.pk, -1, 0, actor=self.staff)
        self.assertEqual(before, list(tournament.matches.values()))
        Event.objects.filter(pk=self.event.pk).update(status=Event.Status.FINISHED)
        with self.assertRaises(TournamentError):
            if self.mode == Tournament.Mode.FFA:
                FFAMatchService.update_ffa_scores(match.pk, [{}], actor=self.staff)
            else:
                TournamentMatchService.update_match_score(match.pk, 1, 0, actor=self.staff)

    def test_public_frontend_renders_and_get_does_not_write_matches(self):
        tournament = self.make()
        before = list(tournament.matches.values())
        self.client.logout()
        response = self.client.get(reverse('tournament_detail', args=[tournament.slug]))
        self.assertContains(response, tournament.title)
        self.assertEqual(before, list(tournament.matches.values()))

    def test_admin_status_change_cannot_add_players_outside_generated_schedule(self):
        tournament = self.make()
        tournament.status = Tournament.Status.REGISTRATION_OPEN
        try:
            # Match the admin form's model clean without validating excluded,
            # noneditable fields such as an unset Swiss pairing seed.
            tournament.clean()
            tournament.save()
        except ValidationError:
            return
        # The existing admin change form also leaves status editable.
        response = self.client.post(reverse('tournament_register', args=[tournament.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(tournament.registrations.count(), 4,
                         'Changing status back to OPEN lets the frontend add a participant '
                         'who has no slot in the generated matches')


class SingleEliminationAudit(FormatAudit):
    mode = Tournament.Mode.SINGLE_ELIMINATION

    def test_winner_correction_updates_unplayed_final(self):
        tournament = self.make()
        semi = tournament.matches.filter(status=TournamentMatch.Status.READY).first()
        TournamentMatchService.update_match_score(semi.pk, 1, 0, actor=self.staff)
        TournamentMatchService.update_match_score(semi.pk, 0, 1, actor=self.staff, decision_reason='Testkorrektur')
        final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.FINAL)
        self.assertIn(semi.team2_id, (final.team1_id, final.team2_id))
        self.assertNotIn(semi.team1_id, (final.team1_id, final.team2_id))
        self.finish(tournament)


class DoubleEliminationAudit(FormatAudit):
    mode = Tournament.Mode.DOUBLE_ELIMINATION

    def test_corrected_grand_final_does_not_leave_a_reset_match_open(self):
        tournament = self.make(2)
        wb = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS)
        TournamentMatchService.update_match_score(wb.pk, 1, 0, actor=self.staff)
        final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL)
        TournamentMatchService.update_match_score(final.pk, 0, 1, actor=self.staff)
        self.assertTrue(tournament.matches.filter(bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET).exists())
        TournamentMatchService.update_match_score(final.pk, 1, 0, actor=self.staff, decision_reason='Testkorrektur')
        confirm_results(tournament, self.staff)
        self.assertEqual(tournament.status, Tournament.Status.FINISHED)
        self.assertFalse(tournament.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists(),
                         'Finished tournament still contains an unplayable READY reset final')


class LeagueAudit(FormatAudit):
    mode = Tournament.Mode.LEAGUE

    def test_withdrawn_leader_cannot_be_declared_champion(self):
        tournament = self.make()
        leader = self.teams[0]
        matches = list(tournament.matches.filter(team1=leader)) + list(tournament.matches.filter(team2=leader))
        for match in matches[:2]:
            TournamentMatchService.update_match_score(match.pk,
                100 if match.team1_id == leader.pk else 0,
                100 if match.team2_id == leader.pk else 0, actor=self.staff)
        forfeit_team_in_active_tournaments(leader)
        self.finish(tournament)
        self.assertTrue(tournament.registrations.get(team=leader).is_forfeited)
        self.assertNotEqual(TournamentPodiumService.calculate(tournament)['first'], leader,
                            'A withdrawn team remains champion with its historical points/score difference')

    def test_certificates_include_places_below_third(self):
        tournament = self.make()
        for match in tournament.matches.all():
            TournamentMatchService.update_match_score(match.pk,
                2 if match.team1_id < match.team2_id else 0,
                2 if match.team2_id < match.team1_id else 0, actor=self.staff)
        confirm_results(tournament, self.staff)
        fourth = LeagueStandingService.calculate_league_standings(tournament)[3]['team']
        self.assertEqual(certificate_rows([fourth], tournament, '')[0]['team.placement'], '4. Platz')


class GroupStageAudit(FormatAudit):
    mode = Tournament.Mode.GROUP_STAGE

    def test_top_two_seeds_are_balanced_across_groups(self):
        tournament = self.make(8)
        seeds = {r.seed: r.group_name for r in tournament.registrations.all()}
        self.assertNotEqual(seeds[1], seeds[2])
        self.assertNotEqual(seeds[3], seeds[4])
        self.assertEqual(seeds[1], seeds[4],
                         'Alternating distribution is not snake seeding: A gets 1,3,5,7; B gets 2,4,6,8')


class FFAAudit(FormatAudit):
    mode = Tournament.Mode.FFA

    def test_missing_active_ranks_do_not_finish_the_tournament(self):
        tournament = self.make()
        match = tournament.matches.get()
        entries = [{'participant_id': p.pk, 'rank': 1 if index == 0 else None, 'score': 0}
                   for index, p in enumerate(match.participants.order_by('pk'))]
        try:
            FFAMatchService.update_ffa_scores(match.pk, entries, actor=self.staff)
        except TournamentError:
            return  # Rejecting incomplete classification also satisfies this invariant.
        tournament.refresh_from_db()
        self.assertNotEqual(tournament.status, Tournament.Status.FINISHED,
                            'Only the winner has a rank, yet every active participant is finalized')


class SwissAudit(FormatAudit):
    mode = Tournament.Mode.SWISS

    def test_six_player_four_round_tournament_can_publish_its_final_round(self):
        with patch('tournaments.services.swiss.secrets.randbits', return_value=0):
            tournament = self.make(6, rounds=4)
        rng = random.Random(0)
        for number in range(1, 4):
            for match in tournament.matches.filter(round_number=number).order_by('match_number'):
                first_wins = bool(rng.randrange(2))
                TournamentMatchService.update_match_score(
                    match.pk, 1 if first_wins else 0, 0 if first_wins else 1, actor=self.staff,
                )
            if number < 3:
                self.start(tournament)
        self.assertEqual(tournament.registrations.filter(is_forfeited=True).count(), 0)
        self.assertEqual(tournament.swiss_round_records.count(), 3)
        try:
            self.start(tournament)
        except SwissPairingError:
            plan = SwissTournamentService.preview(tournament.pk, actor=self.staff, allow_repeats=True)
            self.assertEqual(len(plan['repeated_pairs']), 1)
            with self.assertRaises(TournamentError):
                SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'])
            SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'], approve_repeats=True)
        self.assertEqual(tournament.swiss_round_records.count(), 4)
        self.finish(tournament)

    def test_four_round_pairings_for_six_players_complete_with_explicit_exception_fallback(self):
        for seed in range(200):
            rows = [{'team': SimpleNamespace(pk=i), 'seed': i, 'points': 0, 'withdrawn': False}
                    for i in range(1, 7)]
            history = set()
            rng = random.Random(seed)
            for number in range(1, 5):
                rows.sort(key=lambda r: (-r['points'], r['seed']))
                try:
                    pairs = SwissPairingService.pair(rows, history, set(), seed, number)
                except SwissPairingError:
                    pairs = SwissPairingService.pair(rows, history, set(), seed, number, allow_repeats=True)
                    self.assertEqual(len([pair for pair in pairs if tuple(sorted(pair)) in history]), 1)
                by_id = {r['team'].pk: r for r in rows}
                for a, b in pairs:
                    history.add(tuple(sorted((a, b))))
                    winner = a if rng.randrange(2) else b
                    by_id[winner]['points'] += 3


def main():
    runner = DiscoverRunner(verbosity=0, interactive=False)
    runner.setup_test_environment()
    old_config = runner.setup_databases()
    results = {}
    try:
        runner.run_checks(databases={'default'})
        for case in (SingleEliminationAudit, DoubleEliminationAudit, LeagueAudit,
                     GroupStageAudit, FFAAudit, SwissAudit):
            print(f'\n=== {case.mode} ===', flush=True)
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(case)
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            results[str(case.mode)] = {
                'tests': result.testsRun,
                'passed': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
                'failures': [{'test': str(test), 'traceback': trace} for test, trace in result.failures],
                'errors': [{'test': str(test), 'traceback': trace} for test, trace in result.errors],
                'skipped': result.skipped,
            }
    finally:
        runner.teardown_databases(old_config)
        runner.teardown_test_environment()
    output = ROOT / 'docs' / 'tournament-mode-improvements-results-2026-10-01.json'
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\nResults: {output}', flush=True)
    print(json.dumps({mode: {'tests': r['tests'], 'passed': r['passed'],
                             'failures': len(r['failures']), 'errors': len(r['errors'])}
                      for mode, r in results.items()}, indent=2))
    return 1 if any(r['failures'] or r['errors'] for r in results.values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
