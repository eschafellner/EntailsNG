"""Regression coverage for the six-format review and optional tournament rules."""
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from media_designer.data import certificate_rows
from tournaments.exceptions import TournamentError, SwissPairingError
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentMatch, TournamentRegistration
from tournaments.services import (
    FFAMatchService, TournamentBracketService, TournamentMatchService, TournamentPodiumService,
    LeagueStandingService, GroupStageStandingService, SwissPairingService, SwissTournamentService, forfeit_team_in_active_tournaments,
)


@override_settings(SECURE_SSL_REDIRECT=False)
class FormatImprovementsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.staff = get_user_model().objects.create_user('format-staff', is_staff=True)
        cls.guest = get_user_model().objects.create_user('format-guest')
        cls.event = Event.objects.create(title='Format LAN', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=now, end_date=now + timedelta(days=3))
        cls.game = Game.objects.create(name='Format Game', team_size=1)
        cls.teams = []
        for seed in range(1, 17):
            user = get_user_model().objects.create_user(f'format-player-{seed}')
            team = Team.objects.create(name=f'Team {seed:02}', captain=user, event=cls.event, game=cls.game, is_solo=True)
            TeamMember.objects.create(team=team, user=user, role=TeamMember.Role.CAPTAIN)
            cls.teams.append(team)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.staff)

    def make(self, mode=Tournament.Mode.SINGLE_ELIMINATION, count=4, **settings):
        tournament = Tournament.objects.create(title='Format review', game=self.game, event=self.event,
            mode=mode, status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now()-timedelta(hours=1), registration_end=timezone.now()+timedelta(days=1), **settings)
        for seed, team in enumerate(self.teams[:count], 1):
            TournamentRegistration.objects.create(tournament=tournament, team=team, seed=seed)
        if mode != Tournament.Mode.SWISS:
            TournamentBracketService.generate_bracket(tournament.pk, actor=self.staff)
        tournament.refresh_from_db()
        return tournament

    def play(self, match, first=True):
        return TournamentMatchService.update_match_score(match.pk, 2 if first else 0, 0 if first else 2, actor=self.staff)

    def finish(self, tournament):
        for _ in range(512):
            tournament.refresh_from_db()
            if tournament.status == Tournament.Status.FINISHED:
                return
            match = tournament.matches.filter(status=TournamentMatch.Status.READY, is_bye=False).first()
            self.assertIsNotNone(match)
            self.play(match)
        self.fail('Tournament did not finish')

    def test_correcting_grand_final_removes_unused_reset(self):
        tournament = self.make(Tournament.Mode.DOUBLE_ELIMINATION, 2)
        self.play(tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS))
        final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL)
        self.play(final, False)
        self.assertTrue(tournament.matches.filter(bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET).exists())
        self.play(final)
        tournament.refresh_from_db()
        self.assertEqual(tournament.status, Tournament.Status.FINISHED)
        self.assertFalse(tournament.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists())

    def test_played_reset_still_blocks_correction(self):
        tournament = self.make(Tournament.Mode.DOUBLE_ELIMINATION, 2)
        self.play(tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS))
        final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL)
        self.play(final, False)
        reset = tournament.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET)
        reset.status = TournamentMatch.Status.IN_PROGRESS
        reset.save()
        with self.assertRaises(TournamentError):
            self.play(final)
        self.assertTrue(tournament.matches.filter(pk=reset.pk).exists())

    def test_bronze_and_final_can_finish_in_either_order(self):
        for mode in (Tournament.Mode.SINGLE_ELIMINATION, Tournament.Mode.GROUP_STAGE):
            for bronze_first in (False, True):
                with self.subTest(mode=mode, bronze_first=bronze_first):
                    tournament = self.make(mode, 8, play_third_place=True)
                    while tournament.matches.exclude(bracket_type__in=(TournamentMatch.BracketType.THIRD_PLACE,
                        TournamentMatch.BracketType.FINAL)).exclude(status=TournamentMatch.Status.COMPLETED).exists() or (
                        mode == Tournament.Mode.GROUP_STAGE and tournament.matches.filter(
                            bracket_type=TournamentMatch.BracketType.FINAL, next_match_winner__isnull=False).exclude(status=TournamentMatch.Status.COMPLETED).exists()):
                        match = tournament.matches.filter(status=TournamentMatch.Status.READY).exclude(
                            bracket_type=TournamentMatch.BracketType.THIRD_PLACE).first()
                        self.assertIsNotNone(match)
                        self.play(match)
                    final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.FINAL, next_match_winner__isnull=True)
                    bronze = tournament.matches.get(bracket_type=TournamentMatch.BracketType.THIRD_PLACE)
                    first, last = (bronze, final) if bronze_first else (final, bronze)
                    self.play(first)
                    tournament.refresh_from_db()
                    self.assertEqual(tournament.status, Tournament.Status.IN_PROGRESS)
                    self.play(last)
                    tournament.refresh_from_db()
                    bronze.refresh_from_db()
                    self.assertEqual(tournament.status, Tournament.Status.FINISHED)
                    self.assertEqual(TournamentPodiumService.calculate(tournament)['third'], bronze.winner)
                    self.assertEqual(certificate_rows([bronze.winner], tournament, '')[0]['team.placement'], '3. Platz')
                    self.assertContains(self.client.get(reverse('tournament_detail', args=[tournament.slug])), 'Spiel um Platz 3')

    def test_bronze_with_byes_and_withdrawals_finishes(self):
        for count in (3, 5, 9):
            with self.subTest(count=count):
                tournament = self.make(count=count, play_third_place=True)
                forfeit_team_in_active_tournaments(self.teams[0])
                self.finish(tournament)
                self.assertFalse(tournament.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists())

    def test_preview_includes_bronze_and_clear_round_names(self):
        tournament = self.make(count=8, play_third_place=True)
        quarter = tournament.matches.filter(round_number=1, bracket_type=TournamentMatch.BracketType.WINNERS).first()
        semi = tournament.matches.filter(round_number=2, bracket_type=TournamentMatch.BracketType.WINNERS).first()
        self.assertEqual(quarter.round_name, 'Viertelfinale')
        self.assertEqual(semi.round_name, 'Halbfinale')
        TournamentBracketService.reset_bracket(tournament.pk, actor=self.staff)
        preview = TournamentBracketService.get_bracket_preview(tournament.pk)
        self.assertIn('Spiel um Platz 3', [r['name'] for r in preview['rounds']])

    def test_double_elimination_crosses_wb_second_round_feeds(self):
        tournament = self.make(Tournament.Mode.DOUBLE_ELIMINATION, 8)
        feeders = list(tournament.matches.filter(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=2).order_by('match_number'))
        self.assertEqual([m.next_match_loser.match_number for m in feeders], [2, 1])
        self.finish(tournament)

    def test_snake_seeding_and_configurable_qualifiers(self):
        tournament = self.make(Tournament.Mode.GROUP_STAGE, 8)
        self.assertEqual(list(tournament.registrations.filter(group_name='Gruppe A').order_by('seed').values_list('seed', flat=True)), [1, 4, 5, 8])
        for count, qualifiers in ((4, 2), (6, 2), (8, 1)):
            with self.subTest(count=count, qualifiers=qualifiers):
                tournament = self.make(Tournament.Mode.GROUP_STAGE, count, group_qualifiers_per_group=qualifiers, play_third_place=True)
                self.assertEqual(tournament.matches.filter(bracket_type=TournamentMatch.BracketType.FINAL).count(), 3 if qualifiers == 2 else 1)
                self.finish(tournament)

    def test_started_rules_are_frozen_and_reset_restores_editability(self):
        tournament = self.make()
        for field, value in (('play_third_place', True), ('group_qualifiers_per_group', 2), ('standings_tiebreak', Tournament.Tiebreak.HEAD_TO_HEAD)):
            with self.subTest(field=field):
                tournament.refresh_from_db()
                setattr(tournament, field, value)
                with self.assertRaises(ValidationError):
                    tournament.save()
        TournamentBracketService.reset_bracket(tournament.pk, actor=self.staff)
        tournament.refresh_from_db()
        tournament.play_third_place = True
        tournament.save()

    def test_group_round_titles_separate_group_matches_from_knockouts(self):
        tournament = self.make(Tournament.Mode.GROUP_STAGE, 8, play_third_place=True)
        response = self.client.get(reverse('tournament_detail', args=[tournament.slug]))
        rounds = response.context['bracket_rounds']
        self.assertEqual([r['name'] for r in rounds], [
            'Gruppenphase · Spieltag 1', 'Gruppenphase · Spieltag 2', 'Gruppenphase · Spieltag 3',
            'Halbfinale', 'Finale', 'Spiel um Platz 3',
        ])
        for round in rounds[:3]:
            self.assertTrue(all(m.bracket_type == TournamentMatch.BracketType.GROUP for m in round['matches']))
        self.assertContains(response, 'Gruppenphase · Spieltag 3')

    def test_withdrawn_league_leader_has_no_rank_or_certificate_place(self):
        tournament = self.make(Tournament.Mode.LEAGUE)
        leader = self.teams[0]
        matches = [m for m in tournament.matches.all() if leader.pk in (m.team1_id, m.team2_id)]
        for match in matches[:2]:
            TournamentMatchService.update_match_score(match.pk, 100 if match.team1_id == leader.pk else 0,
                100 if match.team2_id == leader.pk else 0, actor=self.staff)
        forfeit_team_in_active_tournaments(leader)
        self.finish(tournament)
        rows = LeagueStandingService.calculate_league_standings(tournament)
        row = next(r for r in rows if r['team'].pk == leader.pk)
        self.assertEqual(row['points'], 6)
        self.assertTrue(row['withdrawn'])
        self.assertIsNone(row['rank'])
        self.assertNotEqual(TournamentPodiumService.calculate(tournament)['first'], leader)
        self.assertEqual(certificate_rows([leader], tournament, '')[0]['team.placement'], '')
        self.assertContains(self.client.get(reverse('tournament_detail', args=[tournament.slug])), 'Zurückgezogen')

    def test_all_league_places_are_exported(self):
        tournament = self.make(Tournament.Mode.LEAGUE, 6)
        for match in tournament.matches.all():
            self.play(match, match.team1_id < match.team2_id)
        tournament.refresh_from_db()
        placements = TournamentPodiumService.placements(tournament)
        self.assertEqual([p['rank'] for p in placements], list(range(1, 7)))
        self.assertEqual(certificate_rows([placements[-1]['team']], tournament, '')[0]['team.placement'], '6. Platz')

    def test_shared_league_ranks_do_not_invent_a_champion(self):
        tournament = self.make(Tournament.Mode.LEAGUE)
        for match in tournament.matches.all():
            TournamentMatchService.update_match_score(match.pk, 0, 0, actor=self.staff)
        tournament.refresh_from_db()
        self.assertEqual([r['rank'] for r in LeagueStandingService.calculate_league_standings(tournament)], [1, 1, 1, 1])
        self.assertIsNone(TournamentPodiumService.calculate(tournament)['first'])
        self.assertEqual(len(TournamentPodiumService.placements(tournament)), 4)

    def test_migration_retains_historical_ranking_and_new_tournaments_use_shared_ranks(self):
        existing = self.make(Tournament.Mode.LEAGUE)
        self.assertEqual([row['rank'] for row in LeagueStandingService.calculate_league_standings(existing)], [1, 1, 1, 1])
        match_ids = list(existing.matches.values_list('pk', flat=True))
        migration = import_module('tournaments.migrations.0010_format_improvements')
        migration.preserve_existing_tiebreaks(apps, connection.schema_editor())
        existing.refresh_from_db()
        self.assertEqual(existing.standings_tiebreak, Tournament.Tiebreak.LEGACY)
        self.assertEqual([row['rank'] for row in LeagueStandingService.calculate_league_standings(existing)], [1, 2, 3, 4])
        self.assertEqual(list(existing.matches.values_list('pk', flat=True)), match_ids)
        new = self.make(Tournament.Mode.LEAGUE)
        self.assertEqual(new.standings_tiebreak, Tournament.Tiebreak.SHARED)
        self.assertEqual([row['rank'] for row in LeagueStandingService.calculate_league_standings(new)], [1, 1, 1, 1])

    def test_head_to_head_uses_complete_mini_table(self):
        tournament = self.make(Tournament.Mode.LEAGUE, 4, standings_tiebreak=Tournament.Tiebreak.HEAD_TO_HEAD)
        # A beats B, C beats A, B beats C; A and B both beat D, C loses to D.
        wins = {(0, 1): 0, (0, 2): 2, (0, 3): 0, (1, 2): 1, (1, 3): 1, (2, 3): 3}
        ids = {team.pk: i for i, team in enumerate(self.teams[:4])}
        for match in tournament.matches.all():
            pair = tuple(sorted((ids[match.team1_id], ids[match.team2_id])))
            self.play(match, ids[match.team1_id] == wins[pair])
        rows = LeagueStandingService.calculate_league_standings(tournament)
        self.assertEqual(rows[0]['team'], self.teams[0])
        self.assertEqual(rows[1]['team'], self.teams[1])

    def test_ffa_rejects_missing_active_ranks_atomically_but_allows_dq(self):
        tournament = self.make(Tournament.Mode.FFA)
        match = tournament.matches.get()
        entries = [{'participant_id': p.pk, 'rank': 1 if index == 0 else None, 'score': 0}
            for index, p in enumerate(match.participants.order_by('pk'))]
        with self.assertRaises(TournamentError):
            FFAMatchService.update_ffa_scores(match.pk, entries, actor=self.staff)
        self.assertTrue(all(p.rank is None for p in match.participants.all()))
        for entry in entries[1:]:
            entry['is_disqualified'] = True
        FFAMatchService.update_ffa_scores(match.pk, entries, actor=self.staff)
        tournament.refresh_from_db()
        self.assertEqual(tournament.status, Tournament.Status.FINISHED)

    def blocked_swiss(self):
        import random
        tournament = self.make(Tournament.Mode.SWISS, 6, swiss_rounds=4)
        rng = random.Random(0)
        with patch('tournaments.services.swiss.secrets.randbits', return_value=0):
            for number in range(1, 4):
                plan = SwissTournamentService.preview(tournament.pk, actor=self.staff)
                SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'])
                for match in tournament.matches.filter(round_number=number).order_by('match_number'):
                    self.play(match, bool(rng.randrange(2)))
        return tournament

    def test_swiss_exception_requires_separate_approval_and_finishes(self):
        tournament = self.blocked_swiss()
        with self.assertRaises(SwissPairingError):
            SwissTournamentService.preview(tournament.pk, actor=self.staff)
        plan = SwissTournamentService.preview(tournament.pk, actor=self.staff, allow_repeats=True)
        self.assertTrue(plan['has_repeats'])
        self.assertEqual(len(plan['repeated_pairs']), 1)
        with self.assertRaises(TournamentError):
            SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'])
        self.assertEqual(tournament.swiss_round_records.count(), 3)
        record = SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'], approve_repeats=True)
        self.assertTrue(record.repeat_pairings_approved)
        self.assertEqual(record.published_by, self.staff)
        self.finish(tournament)
        self.assertContains(self.client.get(reverse('tournament_detail', args=[tournament.slug])), 'ausdrücklich genehmigte Wiederholungen')

    def test_swiss_exception_is_visible_and_protected_in_frontend(self):
        tournament = self.blocked_swiss()
        preview_url = reverse('tournament_swiss_preview', args=[tournament.slug])
        publish_url = reverse('tournament_swiss_publish', args=[tournament.slug])
        response = self.client.get(preview_url)
        self.assertContains(response, 'Ausnahmevorschau mit Wiederholungen prüfen')
        response = self.client.get(preview_url, {'allow_repeats': '1'})
        self.assertContains(response, 'name="approve_repeats"')
        token = response.context['plan']['token']
        self.client.post(publish_url, {'preview_token': token})
        self.assertEqual(tournament.swiss_round_records.count(), 3)
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(preview_url, {'allow_repeats': '1'}).status_code, 403)
        self.assertEqual(self.client.post(publish_url, {'preview_token': token, 'approve_repeats': 'yes'}).status_code, 403)
        self.client.force_login(self.staff)
        self.client.post(publish_url, {'preview_token': token, 'approve_repeats': 'yes'})
        self.assertEqual(tournament.swiss_round_records.count(), 4)

    def test_swiss_exception_does_not_allow_replay_or_hide_changes(self):
        tournament = self.blocked_swiss()
        plan = SwissTournamentService.preview(tournament.pk, actor=self.staff, allow_repeats=True)
        match = tournament.matches.filter(round_number=3).first()
        self.play(match, not bool(match.winner_id == match.team1_id))
        with self.assertRaises(TournamentError):
            SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'], approve_repeats=True)
        plan = SwissTournamentService.preview(tournament.pk, actor=self.staff, allow_repeats=True)
        SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'], approve_repeats=True)
        with self.assertRaises(TournamentError):
            SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'], approve_repeats=True)

    def test_swiss_normal_preview_keeps_strict_pairs_even_in_exception_mode(self):
        tournament = self.make(Tournament.Mode.SWISS, 6, swiss_rounds=4)
        plan = SwissTournamentService.preview(tournament.pk, actor=self.staff, allow_repeats=True)
        self.assertFalse(plan['has_repeats'])
        record = SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'])
        self.assertFalse(record.repeat_pairings_approved)

    def test_swiss_exception_can_rescue_exhausted_byes_without_relaxing_active_count(self):
        rows = [{'team': SimpleNamespace(pk=i), 'seed': i, 'points': 0, 'withdrawn': False}
                for i in range(1, 4)]
        with self.assertRaises(SwissPairingError):
            SwissPairingService.pair(rows, {(1, 2)}, {1, 2, 3}, 0, 4)
        pairs = SwissPairingService.pair(rows, {(1, 2)}, {1, 2, 3}, 0, 4, allow_repeats=True)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(sorted(a for pair in pairs for a in pair if a is not None), [1, 2, 3])
        self.assertEqual(sum(b is None for a, b in pairs), 1)
        self.assertTrue(all(tuple(sorted((a, b))) != (1, 2) for a, b in pairs if b is not None))
        with self.assertRaises(TournamentError):
            SwissPairingService.pair(rows[:1], set(), set(), 0, 4, allow_repeats=True)
