"""Swiss tournament lifecycle, fairness, publication and shared placements."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import RestrictedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from media_designer.data import certificate_rows
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentRegistration, TournamentMatch, SwissRoundEntry
from tournaments.exceptions import TournamentError
from tournaments.services import TournamentBracketService, TournamentMatchService, TournamentPodiumService
from tournaments.services.swiss import SwissTournamentService, SwissStandingService, SwissPairingService

User = get_user_model()


class SwissTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.staff = User.objects.create_user(username='swiss-orga', is_staff=True)
        cls.event = Event.objects.create(title='Swiss LAN', slug='swiss-lan', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=now + timedelta(days=1), end_date=now + timedelta(days=3))
        cls.game = Game.objects.create(name='Swiss Game', team_size=1)
        cls.teams = []
        for number in range(1, 9):
            user = User.objects.create_user(username=f'swiss-player-{number}')
            team = Team.objects.create(name=f'Swiss Team {number}', captain=user, game=cls.game,
                                       event=cls.event, is_solo=True)
            TeamMember.objects.create(team=team, user=user, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
            cls.teams.append(team)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.staff)
        self.tournament = self.make_tournament()

    def make_tournament(self, count=8, rounds=3, draws=False, seeded=True):
        now = timezone.now()
        tournament = Tournament.objects.create(title='Schweizer Test', event=self.event, game=self.game,
            mode=Tournament.Mode.SWISS, swiss_rounds=rounds, swiss_allow_draws=draws,
            status=Tournament.Status.REGISTRATION_OPEN, registration_start=now - timedelta(hours=2),
            registration_end=now - timedelta(hours=1))
        for number, team in enumerate(self.teams[:count], 1):
            TournamentRegistration.objects.create(tournament=tournament, team=team, seed=number if seeded else None)
        return tournament

    def publish(self, tournament=None):
        tournament = tournament or self.tournament
        plan = SwissTournamentService.preview(tournament.pk, actor=self.staff)
        record = SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'])
        tournament.refresh_from_db()
        return record, plan

    def score_round(self, tournament=None, draw=False):
        tournament = tournament or self.tournament
        record = tournament.swiss_round_records.order_by('-number').first()
        for match in record.matches.filter(is_bye=False).exclude(status=TournamentMatch.Status.COMPLETED).order_by('match_number'):
            TournamentMatchService.update_match_score(match.pk, 0 if draw else 1, 0, actor=self.staff)
        tournament.refresh_from_db()

    def test_complete_even_tournament_waits_for_orga_between_rounds(self):
        previous = set()
        for number in range(1, 4):
            record, _ = self.publish()
            self.assertEqual(record.number, number)
            self.assertEqual(record.entries.count(), 8)
            self.assertEqual(record.matches.count(), 4)
            for match in record.matches.all():
                pair = tuple(sorted((match.team1_id, match.team2_id)))
                self.assertNotIn(pair, previous)
                previous.add(pair)
                self.assertIsNone(match.next_match_winner_id)
            self.score_round()
            self.assertEqual(self.tournament.swiss_round_records.count(), number)
            self.assertEqual(self.tournament.status, Tournament.Status.FINISHED if number == 3 else Tournament.Status.IN_PROGRESS)
        self.assertEqual(sum(r['points'] for r in SwissStandingService.calculate(self.tournament)), 36)
        with self.assertRaises(TournamentError):
            SwissTournamentService.preview(self.tournament.pk, actor=self.staff)

    def test_odd_participants_receive_distinct_byes_and_three_points(self):
        tournament = self.make_tournament(count=7, rounds=3)
        bye_teams = set()
        for _ in range(3):
            record, _ = self.publish(tournament)
            bye = record.matches.get(is_bye=True)
            self.assertNotIn(bye.team1_id, bye_teams)
            bye_teams.add(bye.team1_id)
            self.assertIsNone(bye.team2_id)
            self.assertEqual(bye.result_type, TournamentMatch.ResultType.BYE)
            self.assertEqual(bye.status, TournamentMatch.Status.COMPLETED)
            self.assertIsNone(bye.score_team1)
            self.assertEqual(record.entries.count(), 7)
            self.score_round(tournament)
        self.assertEqual(sum(r['points'] for r in SwissStandingService.calculate(tournament)), 36)

    def test_three_players_can_play_three_rounds_without_repeat(self):
        tournament = self.make_tournament(count=3, rounds=3)
        for _ in range(3):
            self.publish(tournament)
            self.score_round(tournament)
        self.assertEqual(tournament.matches.filter(is_bye=False).count(), 3)
        self.assertEqual(tournament.status, Tournament.Status.FINISHED)

    def test_preview_is_read_only_and_publishes_exact_pairings_and_seeds(self):
        tournament = self.make_tournament(seeded=False)
        plan = SwissTournamentService.preview(tournament.pk, actor=self.staff)
        self.assertFalse(tournament.swiss_round_records.exists())
        self.assertFalse(tournament.matches.exists())
        self.assertTrue(all(seed is None for seed in tournament.registrations.values_list('seed', flat=True)))
        record = SwissTournamentService.publish(tournament.pk, actor=self.staff, token=plan['token'])
        self.assertEqual(list(record.matches.order_by('match_number').values_list('team1_id', 'team2_id')), plan['pairs'])
        self.assertEqual(sorted(record.entries.values_list('seed', flat=True)), list(range(1, 9)))
        self.assertEqual(record.input_digest, plan['digest'])
        self.assertEqual(record.standings_snapshot, plan['snapshot'])

    def test_incomplete_round_cannot_be_followed_by_another(self):
        self.publish()
        with self.assertRaisesMessage(TournamentError, 'alle Ergebnisse'):
            SwissTournamentService.preview(self.tournament.pk, actor=self.staff)
        self.assertEqual(self.tournament.swiss_round_records.count(), 1)

    def test_correction_invalidates_preview_and_next_publication_locks_previous_round(self):
        record, _ = self.publish()
        self.score_round()
        plan = SwissTournamentService.preview(self.tournament.pk, actor=self.staff)
        match = record.matches.first()
        TournamentMatchService.update_match_score(match.pk, 0, 1, actor=self.staff)
        with self.assertRaisesMessage(TournamentError, 'seit der Vorschau geändert'):
            SwissTournamentService.publish(self.tournament.pk, actor=self.staff, token=plan['token'])
        self.publish()
        with self.assertRaisesMessage(TournamentError, 'frühere Ergebnis ist gesperrt'):
            TournamentMatchService.update_match_score(match.pk, 1, 0, actor=self.staff)

    def test_token_cannot_be_replayed_or_used_for_another_tournament(self):
        _, plan = self.publish()
        with self.assertRaises(TournamentError):
            SwissTournamentService.publish(self.tournament.pk, actor=self.staff, token=plan['token'])
        other = self.make_tournament()
        with self.assertRaises(TournamentError):
            SwissTournamentService.publish(other.pk, actor=self.staff, token=plan['token'])
        with self.assertRaises(TournamentError):
            SwissTournamentService.publish(other.pk, actor=self.staff, token=plan['token'] + 'tampered')
        self.assertFalse(other.matches.exists())

    def test_expired_preview_is_rejected(self):
        plan = SwissTournamentService.preview(self.tournament.pk, actor=self.staff)
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 700):
            with self.assertRaisesMessage(TournamentError, 'abgelaufen'):
                SwissTournamentService.publish(self.tournament.pk, actor=self.staff, token=plan['token'])

    def test_optional_draws_and_participant_fairplay(self):
        tournament = self.make_tournament(draws=True)
        record, _ = self.publish(tournament)
        match = record.matches.first()
        user = match.team1.captain
        TournamentMatchService.update_match_score(match.pk, 2, 2, actor=user)
        standings = {r['team'].pk: r for r in SwissStandingService.calculate(tournament)}
        self.assertEqual(standings[match.team1_id]['points'], 1)
        self.assertEqual(standings[match.team2_id]['points'], 1)
        other = record.matches.last()
        with self.assertRaises(TournamentError):
            TournamentMatchService.update_match_score(other.pk, 1, 0, winner_id=other.team1_id, actor=other.team1.captain)
        TournamentMatchService.update_match_score(other.pk, 0, 1, actor=other.team1.captain)

    def test_disabled_draws_and_bye_edit_are_rejected(self):
        record, _ = self.publish()
        with self.assertRaises(TournamentError):
            TournamentMatchService.update_match_score(record.matches.first().pk, 0, 0, actor=self.staff)
        odd = self.make_tournament(count=7)
        record, _ = self.publish(odd)
        with self.assertRaises(TournamentError):
            TournamentMatchService.update_match_score(record.matches.get(is_bye=True).pk, 1, 0, actor=self.staff)

    def test_withdrawal_uses_walkover_and_preserves_history(self):
        record, _ = self.publish()
        match = record.matches.first()
        SwissTournamentService.withdraw(self.tournament.pk, match.team1_id, reason='Nicht erschienen', actor=self.staff)
        match.refresh_from_db()
        self.assertEqual(match.winner_id, match.team2_id)
        self.assertEqual(match.result_type, TournamentMatch.ResultType.WALKOVER)
        self.assertIsNone(match.score_team1)
        rows = {r['team'].pk: r for r in SwissStandingService.calculate(self.tournament)}
        self.assertEqual(rows[match.team2_id]['points'], 3)
        self.assertIsNone(rows[match.team1_id]['rank'])
        self.score_round()
        record, _ = self.publish()
        self.assertFalse(record.entries.filter(team_id=match.team1_id).exists())
        self.assertNotEqual(record.matches.get(is_bye=True).team1_id, match.team2_id)

    def test_withdrawal_invalidates_an_existing_preview(self):
        self.publish()
        self.score_round()
        plan = SwissTournamentService.preview(self.tournament.pk, actor=self.staff)
        SwissTournamentService.withdraw(self.tournament.pk, self.teams[0].pk, actor=self.staff)
        with self.assertRaises(TournamentError):
            SwissTournamentService.publish(self.tournament.pk, actor=self.staff, token=plan['token'])

    def test_forced_team_deletion_archives_and_bulk_deletion_is_protected(self):
        self.publish()
        team = self.teams[0]
        team.delete(force=True)
        team.refresh_from_db()
        self.assertTrue(team.is_archived)
        self.assertTrue(TournamentRegistration.objects.get(tournament=self.tournament, team=team).is_forfeited)
        self.assertTrue(self.tournament.matches.filter(team1=team).exists() or self.tournament.matches.filter(team2=team).exists())
        with self.assertRaises(RestrictedError):
            Team.objects.filter(pk=team.pk).delete()
        with self.assertRaises(RestrictedError):
            self.tournament.registrations.get(team=team).delete()

    def test_rules_seeds_and_roster_cannot_change_after_start(self):
        self.publish()
        self.tournament.swiss_rounds = 2
        with self.assertRaises(ValidationError):
            self.tournament.save()
        registration = self.tournament.registrations.first()
        registration.seed = 99
        with self.assertRaises(ValidationError):
            registration.save()
        user = User.objects.create_user(username='swiss-late')
        team = Team.objects.create(name='Late', game=self.game, captain=user, event=self.event)
        with self.assertRaises(ValidationError):
            TournamentRegistration.objects.create(tournament=self.tournament, team=team)
        stale = Tournament.objects.get(pk=self.tournament.pk)
        stale.is_generated = False
        with self.assertRaises(ValidationError):
            TournamentRegistration.objects.create(tournament=stale, team=team)

    def test_whole_tournament_can_be_deleted_without_losing_other_tournament_history(self):
        self.publish()
        other = self.make_tournament()
        self.publish(other)
        self.tournament.delete()
        self.assertEqual(other.swiss_round_records.count(), 1)
        self.assertEqual(other.swiss_round_records.first().entries.count(), 8)
        self.assertEqual(Team.objects.filter(pk__in=[t.pk for t in self.teams]).count(), 8)

    def test_invalid_round_count_and_duplicate_seeds_are_atomic(self):
        tournament = self.make_tournament(count=2, rounds=2)
        with self.assertRaises(TournamentError):
            self.publish(tournament)
        self.assertFalse(tournament.matches.exists())
        TournamentRegistration.objects.filter(tournament=self.tournament).update(seed=1)
        with self.assertRaises(TournamentError):
            self.publish()
        self.assertFalse(self.tournament.is_generated)

    def test_buchholz_sonneborn_and_shared_places_are_used_in_certificates(self):
        tournament = self.make_tournament(count=4, rounds=1, draws=True)
        self.publish(tournament)
        self.score_round(tournament, draw=True)
        standings = SwissStandingService.calculate(tournament)
        self.assertEqual([(r['points'], r['buchholz'], r['sonneborn_berger'], r['rank']) for r in standings], [(1, 1, 1, 1)] * 4)
        self.assertEqual(len(TournamentPodiumService.placements(tournament)), 4)
        self.assertEqual(TournamentPodiumService.calculate(tournament), {'first': None, 'second': None, 'third': None})
        rows = certificate_rows(self.teams[:4], tournament, '')
        self.assertEqual([r['team.placement'] for r in rows], ['1. Platz'] * 4)
        response = self.client.get(reverse('tournament_detail', args=[tournament.slug]))
        self.assertContains(response, 'Abschlusstabelle')
        self.assertEqual(len(response.context['swiss_placements']), 4)

    def test_bye_uses_virtual_opponent_instead_of_zero_strength(self):
        tournament = self.make_tournament(count=3, rounds=1)
        record, _ = self.publish(tournament)
        bye = record.matches.get(is_bye=True)
        self.score_round(tournament)
        row = next(r for r in SwissStandingService.calculate(tournament) if r['team'].pk == bye.team1_id)
        self.assertEqual((row['points'], row['buchholz'], row['sonneborn_berger']), (3, 1, 3))

    def test_pairing_failure_does_not_create_partial_rounds(self):
        tournament = self.make_tournament(count=2, rounds=1)
        standings = SwissStandingService.calculate(tournament)
        with self.assertRaises(TournamentError):
            SwissPairingService.pair(standings, {tuple(sorted(t.pk for t in self.teams[:2]))}, set(), 1, 1)
        self.assertFalse(tournament.matches.exists())

    def test_publication_requires_manager_post_csrf_and_preview(self):
        preview_url = reverse('tournament_swiss_preview', args=[self.tournament.slug])
        publish_url = reverse('tournament_swiss_publish', args=[self.tournament.slug])
        self.assertEqual(self.client.get(publish_url).status_code, 405)
        self.assertEqual(self.client.post(preview_url).status_code, 405)
        self.client.post(publish_url)
        self.assertFalse(self.tournament.matches.exists())
        response = self.client.get(preview_url)
        token = response.context['plan']['token']
        self.client.force_login(self.teams[0].captain)
        self.assertEqual(self.client.get(preview_url).status_code, 403)
        self.assertEqual(self.client.post(publish_url, {'preview_token': token}).status_code, 403)
        self.client.force_login(self.staff)
        self.client.post(publish_url, {'preview_token': token})
        self.assertEqual(self.tournament.swiss_round_records.count(), 1)

    def test_unique_round_entry_prevents_double_participation(self):
        record, _ = self.publish()
        entry = record.entries.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SwissRoundEntry.objects.create(round=record, match=entry.match, registration=entry.registration,
                                           team=entry.team, seed=entry.seed)

    def test_reset_cleans_rounds_but_is_blocked_after_play(self):
        self.publish()
        TournamentBracketService.reset_bracket(self.tournament.pk, actor=self.staff)
        self.tournament.refresh_from_db()
        self.assertFalse(self.tournament.swiss_round_records.exists())
        self.assertFalse(self.tournament.is_generated)
        self.publish()
        self.score_round()
        with self.assertRaises(TournamentError):
            TournamentBracketService.reset_bracket(self.tournament.pk, actor=self.staff)

    def test_event_end_and_cancelled_tournament_block_new_rounds(self):
        Event.objects.filter(pk=self.event.pk).update(status=Event.Status.FINISHED)
        with self.assertRaises(TournamentError):
            self.publish()
        Event.objects.filter(pk=self.event.pk).update(status=Event.Status.REGISTRATION_OPEN)
        Tournament.objects.filter(pk=self.tournament.pk).update(status=Tournament.Status.CANCELLED)
        with self.assertRaises(TournamentError):
            self.publish()

    def test_pairings_prefer_equal_points_after_first_round(self):
        self.publish()
        self.score_round()
        points = {r['team'].pk: r['points'] for r in SwissStandingService.calculate(self.tournament)}
        record, _ = self.publish()
        for match in record.matches.all():
            self.assertEqual(points[match.team1_id], points[match.team2_id])

    def test_four_player_final_tiebreak_values_and_certificate_places(self):
        tournament = self.make_tournament(count=4, rounds=3)
        for _ in range(3):
            self.publish(tournament)
            self.score_round(tournament)
        rows = SwissStandingService.calculate(tournament)
        self.assertEqual([(r['points'], r['buchholz'], r['sonneborn_berger'], r['rank']) for r in rows],
                         [(9, 9, 27, 1), (6, 12, 9, 2), (3, 15, 0, 3), (0, 18, 0, 4)])
        self.assertEqual([p['rank'] for p in TournamentPodiumService.placements(tournament)], [1, 2, 3, 4])
        self.assertEqual([r['team.placement'] for r in certificate_rows(self.teams[:4], tournament, '')],
                         ['1. Platz', '2. Platz', '3. Platz', '4. Platz'])

    def test_preview_fails_cleanly_if_every_active_participant_has_received_a_bye(self):
        standings = SwissStandingService.calculate(self.make_tournament(count=3, rounds=2))
        with self.assertRaisesMessage(TournamentError, 'Freilos berechtigt'):
            SwissPairingService.pair(standings, set(), {r['team'].pk for r in standings}, 1, 2)

    def test_public_detail_shows_pending_release_and_locked_result_buttons(self):
        self.publish()
        self.score_round()
        response = self.client.get(reverse('tournament_detail', args=[self.tournament.slug]))
        self.assertContains(response, 'Nächste Runde auslosen')
        self.assertContains(response, 'Ergebnis korrigieren', count=8)
        self.publish()
        response = self.client.get(reverse('tournament_detail', args=[self.tournament.slug]))
        old = [m for m in response.context['match_list_cards'] if m.round_number == 1]
        self.assertTrue(all(not m.swiss_editable for m in old))
        self.client.logout()
        response = self.client.get(reverse('tournament_detail', args=[self.tournament.slug]))
        self.assertContains(response, 'Aktuelle Rangliste')
        self.assertNotContains(response, 'Rückzug bestätigen')

    def test_withdrawal_endpoint_requires_reason_and_manager(self):
        self.publish()
        url = reverse('tournament_swiss_withdraw', args=[self.tournament.slug, self.teams[0].pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url)
        self.assertFalse(self.tournament.registrations.get(team=self.teams[0]).is_forfeited)
        self.client.post(url, {'reason': 'x' * 256})
        self.assertFalse(self.tournament.registrations.get(team=self.teams[0]).is_forfeited)
        self.client.force_login(self.teams[0].captain)
        self.assertEqual(self.client.post(url, {'reason': 'Aufgabe'}).status_code, 403)
        self.client.force_login(self.staff)
        self.client.post(url, {'reason': 'Aufgabe'})
        self.assertTrue(self.tournament.registrations.get(team=self.teams[0]).is_forfeited)

    def test_csrf_is_enforced_on_publication(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        token = SwissTournamentService.preview(self.tournament.pk, actor=self.staff)['token']
        response = client.post(reverse('tournament_swiss_publish', args=[self.tournament.slug]), {'preview_token': token})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.tournament.matches.exists())

    def test_one_remaining_active_participant_does_not_receive_infinite_byes(self):
        standings = SwissStandingService.calculate(self.tournament)
        for row in standings[1:]:
            row['withdrawn'] = True
        with self.assertRaisesMessage(TournamentError, 'mindestens zwei'):
            SwissPairingService.pair(standings, set(), set(), 1, 1)

    def test_admin_locks_previous_results_and_routes_start_through_preview(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from tournaments.admin import TournamentAdmin, TournamentMatchAdmin
        request = RequestFactory().post('/')
        request.user = self.staff
        admin = TournamentAdmin(Tournament, AdminSite())
        with patch.object(admin, 'message_user') as message:
            admin.action_close_registration_and_generate_bracket(request, [self.tournament])
        self.assertIn('/swiss/preview/', str(message.call_args.args[1]))
        self.assertFalse(self.tournament.matches.exists())
        self.publish()
        self.score_round()
        old_match = self.tournament.matches.filter(is_bye=False).first()
        self.publish()
        match_admin = TournamentMatchAdmin(TournamentMatch, AdminSite())
        readonly = match_admin.get_readonly_fields(request, old_match)
        self.assertIn('score_team1', readonly)
        self.assertIn('winner', readonly)
        old_match.score_team1 = None
        with self.assertRaises(ValidationError):
            match_admin.save_model(request, old_match, None, True)


class SwissPairingPropertyTests(TestCase):
    def test_varied_field_sizes_produce_complete_deterministic_pairings_without_rematches(self):
        import math
        import random
        from types import SimpleNamespace
        for count in (2, 3, 7, 8, 16, 32, 64):
            standings = [{'team': SimpleNamespace(pk=i), 'seed': i, 'points': 0, 'withdrawn': False}
                         for i in range(1, count + 1)]
            history, byes = set(), set()
            rng = random.Random(count)
            rounds = min(math.ceil(math.log2(count)), count - (count % 2 == 0))
            for number in range(1, rounds + 1):
                with self.subTest(count=count, round=number):
                    standings.sort(key=lambda r: (-r['points'], r['seed']))
                    pairs = SwissPairingService.pair(standings, history, byes, 123, number)
                    self.assertEqual(pairs, SwissPairingService.pair(standings, history, byes, 123, number))
                    ids = [team for pair in pairs for team in pair if team is not None]
                    self.assertEqual(sorted(ids), list(range(1, count + 1)))
                    by_id = {r['team'].pk: r for r in standings}
                    for a, b in pairs:
                        if b is None:
                            self.assertNotIn(a, byes)
                            byes.add(a)
                            by_id[a]['points'] += 3
                        else:
                            pair = tuple(sorted((a, b)))
                            self.assertNotIn(pair, history)
                            history.add(pair)
                            outcome = rng.choice(((3, 0), (0, 3), (1, 1)))
                            by_id[a]['points'] += outcome[0]
                            by_id[b]['points'] += outcome[1]
