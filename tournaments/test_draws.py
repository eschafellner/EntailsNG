"""Organizer draw plans: pairing constraints, exact publication and stale form guards."""
from datetime import timedelta
from unittest.mock import patch
import time

from django.contrib import admin
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from clans.models import Clan, ClanMembership
from events.models import Event
from tournaments.admin import TournamentAdmin, TournamentDrawAdmin
from tournaments.exceptions import TournamentError
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentDraw, TournamentRegistration
from tournaments.services.brackets import TournamentBracketService
from tournaments.services.draws import TOKEN_SALT, TOKEN_MAX_AGE, TournamentDrawService
from users.models import User


class DrawTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.staff = User.objects.create_superuser('draw-orga')
        cls.other_staff = User.objects.create_superuser('draw-other-orga')
        cls.guest = User.objects.create_user('draw-guest')
        cls.event = Event.objects.create(title='Draw LAN', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=now, end_date=now + timedelta(days=3))
        cls.game = Game.objects.create(name='Draw Game', team_size=1)
        cls.clan = Clan.objects.create(name='Draw Clan A', password='')
        cls.other_clan = Clan.objects.create(name='Draw Clan B', password='')
        cls.teams = []
        for number in range(16):
            captain = User.objects.create_user(f'draw-captain-{number}')
            team = Team.objects.create(name=f'Draw Team {number:02}', captain=captain, game=cls.game, event=cls.event)
            TeamMember.objects.create(team=team, user=captain, status=TeamMember.Status.ACCEPTED,
                role=TeamMember.Role.CAPTAIN)
            cls.teams.append(team)

    def setUp(self):
        cache.clear()

    def tournament(self, count=8, mode=Tournament.Mode.SINGLE_ELIMINATION, seeded=0, clans=()):
        now = timezone.now()
        tournament = Tournament.objects.create(title=f'Draw {mode} {Tournament.objects.count()}', event=self.event,
            game=self.game, mode=mode, status=Tournament.Status.REGISTRATION_OPEN, max_teams=64,
            swiss_rounds=2, registration_start=now - timedelta(hours=1), registration_end=now + timedelta(hours=1))
        for index, team in enumerate(self.teams[:count]):
            TournamentRegistration.objects.create(tournament=tournament, team=team,
                seed=index + 1 if index < seeded else None,
                draw_clan=clans[index] if index < len(clans) else None)
        return tournament

    def preview(self, tournament):
        return TournamentDrawService.preview(tournament.pk, actor=self.staff)

    def revise(self, tournament, plan, action='shuffle', **values):
        data = dict(actor=self.staff, token=plan['token'], action=action,
            clans={str(row['id']): row['clan_id'] for row in plan['rows']},
            respect_seeds=plan['respect_seeds'], avoid_clans=plan['avoid_clans'])
        data.update(values)
        return TournamentDrawService.revise(tournament.pk, **data)

    def publish(self, tournament, plan, **values):
        return TournamentDrawService.publish(tournament.pk, actor=self.staff, token=plan['token'], **values)

    def assert_published_pairs(self, tournament, plan):
        expected = [(p['team1']['team'].pk, p['team2']['team'].pk if p['team2'] else None) for p in plan['pairs']]
        matches = tournament.matches.filter(round_number=1)
        if tournament.mode == Tournament.Mode.DOUBLE_ELIMINATION:
            matches = matches.filter(bracket_type='WINNERS')
        self.assertEqual(list(matches.order_by('match_number').values_list('team1_id', 'team2_id')), expected)

    def test_preview_and_revisions_are_read_only(self):
        tournament = self.tournament()
        plan = self.preview(tournament)
        assigned = {str(row['id']): self.clan.pk for row in plan['rows'][:2]}
        clans = {str(row['id']): assigned.get(str(row['id'])) for row in plan['rows']}
        plan = self.revise(tournament, plan, clans=clans)
        self.revise(tournament, plan, 'swap', swap_first=plan['rows'][0]['id'], swap_second=plan['rows'][1]['id'])
        tournament.refresh_from_db()
        self.assertFalse(tournament.is_generated)
        self.assertEqual(tournament.status, Tournament.Status.REGISTRATION_OPEN)
        self.assertFalse(tournament.matches.exists())
        self.assertFalse(TournamentDraw.objects.exists())
        self.assertFalse(tournament.registrations.exclude(draw_clan=None).exists())

    def test_ko_modes_counts_byes_and_exact_pairings(self):
        for mode in (Tournament.Mode.SINGLE_ELIMINATION, Tournament.Mode.DOUBLE_ELIMINATION):
            for count in (2, 3, 5, 8, 16):
                with self.subTest(mode=mode, count=count):
                    tournament = self.tournament(count, mode)
                    plan = self.revise(tournament, self.preview(tournament))
                    log, created = self.publish(tournament, plan)
                    self.assertTrue(created)
                    self.assert_published_pairs(tournament, plan)
                    self.assertEqual(len(log.snapshot['participants']), count)
                    tournament.refresh_from_db()
                    self.assertTrue(tournament.is_generated)
                    self.assertEqual(tournament.status, Tournament.Status.IN_PROGRESS)

    def test_avoidable_and_unavoidable_clan_conflicts(self):
        for members, expected in ((2, 0), (4, 0), (5, 1), (6, 2), (8, 4)):
            with self.subTest(members=members):
                tournament = self.tournament(clans=[self.clan] * members)
                plan = self.revise(tournament, self.preview(tournament))
                self.assertEqual(plan['conflict_count'], expected)
                if expected:
                    with self.assertRaises(TournamentError):
                        self.publish(tournament, plan)
                    with self.assertRaises(TournamentError):
                        self.publish(tournament, plan, approve_conflicts=True, reason=' ')
                log, _ = self.publish(tournament, plan, approve_conflicts=True, reason='Orga bestätigt die Verteilung.')
                self.assertEqual(log.conflict_count, expected)
                self.assert_published_pairs(tournament, plan)

    def test_clan_rule_can_be_disabled_explicitly(self):
        tournament = self.tournament(clans=[self.clan] * 8)
        plan = self.revise(tournament, self.preview(tournament), avoid_clans=False)
        self.assertFalse(plan['needs_approval'])
        self.assertTrue(self.publish(tournament, plan)[0])

    def test_byes_allow_clan_separation_with_majority(self):
        tournament = self.tournament(5, clans=[self.clan] * 4)
        plan = self.revise(tournament, self.preview(tournament))
        self.assertEqual(plan['conflict_count'], 0)
        self.assertEqual(sum(pair['team2'] is None for pair in plan['pairs']), 3)
        self.publish(tournament, plan)
        self.assert_published_pairs(tournament, plan)

    def test_groups_balance_clans_and_publish_exact_membership_and_schedule(self):
        for count in (4, 5, 8, 16):
            with self.subTest(count=count):
                tournament = self.tournament(count, Tournament.Mode.GROUP_STAGE, clans=[self.clan] * 3)
                plan = self.revise(tournament, self.preview(tournament))
                self.assertEqual(plan['conflict_count'], 1)
                self.assertLessEqual(abs(len(plan['groups'][0]['rows']) - len(plan['groups'][1]['rows'])), 1)
                self.publish(tournament, plan, approve_conflicts=True, reason='Drei Clan-Teams in zwei Gruppen.')
                for group in plan['groups']:
                    self.assertEqual(set(tournament.registrations.filter(group_name=group['name']).values_list('team_id', flat=True)),
                        {row['team'].pk for row in group['rows']})
                expected = {(group['name'], round_index, match['match_number'], match['team1'], match['team2'])
                    for group in plan['preview']['group_rounds'] for round_index, round in enumerate(group['rounds'], 1)
                    for match in round['matches']}
                actual = {(match.group_name, match.round_number, match.match_number, match.team1.name, match.team2.name)
                    for match in tournament.matches.filter(bracket_type='GROUP').select_related('team1', 'team2')}
                self.assertEqual(actual, expected)

    def test_group_manual_swap_and_seed_constraints(self):
        tournament = self.tournament(8, Tournament.Mode.GROUP_STAGE, seeded=1)
        plan = self.preview(tournament)
        first, second = plan['groups'][0]['rows'][1]['id'], plan['groups'][1]['rows'][0]['id']
        changed = self.revise(tournament, plan, 'swap', swap_first=first, swap_second=second)
        self.assertIn(second, [row['id'] for row in changed['groups'][0]['rows']])
        self.assertIn(first, [row['id'] for row in changed['groups'][1]['rows']])
        self.assertEqual(changed['rows'][0]['id'], plan['rows'][0]['id'])
        self.publish(tournament, changed)

    def test_group_two_clan_teams_can_be_separated_and_small_fields_rejected(self):
        tournament = self.tournament(4, Tournament.Mode.GROUP_STAGE, clans=[self.clan] * 2)
        plan = self.revise(tournament, self.preview(tournament))
        self.assertEqual(plan['conflict_count'], 0)
        self.publish(tournament, plan)
        too_small = self.tournament(3, Tournament.Mode.GROUP_STAGE)
        with self.assertRaises(TournamentError):
            self.preview(too_small)

    def test_swiss_exact_first_round_and_normal_following_round(self):
        from .services.matches import TournamentMatchService
        from .services.swiss import SwissTournamentService
        for count in (2, 3, 5, 8):
            with self.subTest(count=count):
                tournament = self.tournament(count, Tournament.Mode.SWISS, clans=[self.clan] * (count // 2))
                tournament.swiss_rounds = min(2, count - (count % 2 == 0))
                tournament.save()
                plan = self.revise(tournament, self.preview(tournament))
                self.assertEqual(plan['conflict_count'], 0)
                self.publish(tournament, plan)
                self.assert_published_pairs(tournament, plan)
                self.assertEqual(tournament.swiss_round_records.count(), 1)
                self.assertEqual(tournament.swiss_round_records.first().entries.count(), count)
                for match in tournament.matches.filter(is_bye=False):
                    TournamentMatchService.update_match_score(match.pk, 1, 0, actor=self.staff)
                if tournament.swiss_rounds > 1:
                    next_plan = SwissTournamentService.preview(tournament.pk, actor=self.staff)
                    self.assertEqual(next_plan['number'], 2)
                    SwissTournamentService.publish(tournament.pk, actor=self.staff, token=next_plan['token'])
                    previous = {frozenset(pair) for pair in tournament.matches.filter(round_number=1,
                        is_bye=False).values_list('team1_id', 'team2_id')}
                    following = {frozenset(pair) for pair in tournament.matches.filter(round_number=2,
                        is_bye=False).values_list('team1_id', 'team2_id')}
                    self.assertFalse(previous.intersection(following))

    def test_swiss_manual_swap_preserves_roster_and_effective_seeds(self):
        tournament = self.tournament(5, Tournament.Mode.SWISS, seeded=1)
        plan = self.preview(tournament)
        changed = self.revise(tournament, plan, 'swap', swap_first=plan['rows'][1]['id'], swap_second=plan['rows'][4]['id'])
        self.publish(tournament, changed)
        self.assert_published_pairs(tournament, changed)
        self.assertEqual(list(tournament.registrations.order_by('seed').values_list('pk', flat=True)),
                         [row['id'] for row in changed['rows']])

    def test_swiss_first_round_routes_use_draw_editor(self):
        tournament = self.tournament(4, Tournament.Mode.SWISS)
        self.client.force_login(self.staff)
        url = reverse('tournament_draw_preview', args=[tournament.slug])
        self.assertRedirects(self.client.get(reverse('tournament_swiss_preview', args=[tournament.slug])), url)
        self.assertRedirects(self.client.post(reverse('tournament_swiss_publish', args=[tournament.slug])), url)

    def test_league_first_round_and_full_schedule_match_preview(self):
        for count in (2, 3, 5, 8):
            with self.subTest(count=count):
                tournament = self.tournament(count, Tournament.Mode.LEAGUE, clans=[self.clan] * (count // 2))
                plan = self.revise(tournament, self.preview(tournament))
                self.assertEqual(plan['conflict_count'], 0)
                self.publish(tournament, plan)
                expected = [(round['round'], m['match_number'], m['team1'], m['team2'])
                    for round in plan['preview']['rounds'] for m in round['matches']]
                actual = [(m.round_number, m.match_number, m.team1.name, m.team2.name)
                    for m in tournament.matches.select_related('team1', 'team2').order_by('round_number', 'match_number')]
                self.assertEqual(actual, expected)
                meetings = [frozenset(pair) for pair in tournament.matches.values_list('team1_id', 'team2_id')]
                self.assertEqual(len(set(meetings)), count * (count - 1) // 2)
                self.assertEqual(len(meetings), len(set(meetings)))

    def test_league_manual_swap_rebuilds_valid_round_robin_schedule(self):
        tournament = self.tournament(5, Tournament.Mode.LEAGUE)
        plan = self.preview(tournament)
        changed = self.revise(tournament, plan, 'swap', swap_first=plan['rows'][0]['id'], swap_second=plan['rows'][2]['id'])
        self.publish(tournament, changed)
        self.assertEqual(tournament.matches.count(), 10)
        first_round = set(tournament.matches.filter(round_number=1).values_list('team1_id', 'team2_id'))
        self.assertEqual(first_round, {(p['team1']['team'].pk, p['team2']['team'].pk)
                                      for p in changed['pairs'] if p['team2']})

    def test_ffa_reviews_participants_without_pairing_or_shuffle(self):
        tournament = self.tournament(5, Tournament.Mode.FFA, clans=[self.clan] * 5)
        plan = self.preview(tournament)
        self.assertFalse(plan['editable_positions'])
        self.assertFalse(plan['pairs'])
        self.assertFalse(plan['needs_approval'])
        self.assertEqual(plan['preview']['participants'], [team.name for team in self.teams[:5]])
        with self.assertRaises(TournamentError):
            self.revise(tournament, plan, 'shuffle')
        self.publish(tournament, plan)
        match = tournament.matches.get()
        self.assertEqual(match.bracket_type, 'FFA')
        self.assertEqual(set(match.participants.values_list('team_id', flat=True)), {team.pk for team in self.teams[:5]})

    def test_all_modes_require_preview_and_revalidate_rosters(self):
        self.client.force_login(self.staff)
        for mode in Tournament.Mode.values:
            with self.subTest(mode=mode):
                tournament = self.tournament(4, mode)
                url = reverse('tournament_draw_preview', args=[tournament.slug])
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIsNotNone(response.context['plan'])
                self.assertRedirects(self.client.post(reverse('tournament_generate_bracket', args=[tournament.slug])), url)
                self.assertFalse(tournament.matches.exists())
                TeamMember.objects.filter(team=self.teams[0]).update(status=TeamMember.Status.PENDING)
                with self.assertRaises(TournamentError):
                    self.publish(tournament, response.context['plan'])
                TeamMember.objects.filter(team=self.teams[0]).update(status=TeamMember.Status.ACCEPTED)

    def test_seeds_stay_fixed_and_manual_unlock_is_explicit(self):
        tournament = self.tournament(seeded=2)
        base = self.preview(tournament)
        plan = self.revise(tournament, base)
        self.assertEqual([row['id'] for row in plan['rows'][:2]], [row['id'] for row in base['rows'][:2]])
        with self.assertRaises(TournamentError):
            self.revise(tournament, plan, 'swap', swap_first=plan['rows'][0]['id'], swap_second=plan['rows'][3]['id'])
        changed = self.revise(tournament, plan, 'swap', respect_seeds=False,
            swap_first=plan['rows'][0]['id'], swap_second=plan['rows'][3]['id'])
        self.assertEqual(changed['rows'][3]['id'], base['rows'][0]['id'])
        self.publish(tournament, changed)
        self.assert_published_pairs(tournament, changed)

    def test_fully_seeded_conflicts_require_approval_or_unlock(self):
        tournament = self.tournament(seeded=8, clans=[self.clan, None, None, None, None, None, None, self.clan])
        plan = self.revise(tournament, self.preview(tournament))
        self.assertEqual(plan['conflict_count'], 1)
        unlocked = self.revise(tournament, plan, respect_seeds=False)
        self.assertEqual(unlocked['conflict_count'], 0)

    def test_duplicate_seeds_are_rejected(self):
        tournament = self.tournament()
        tournament.registrations.update(seed=1)
        with self.assertRaises(TournamentError):
            self.preview(tournament)

    def test_suggestions_require_organizer_action(self):
        tournament = self.tournament(2)
        ClanMembership.objects.create(user=self.teams[0].captain, clan=self.clan)
        plan = self.preview(tournament)
        self.assertIsNone(plan['rows'][0]['clan_id'])
        self.assertEqual(plan['rows'][0]['suggested_clan'], self.clan)
        plan = self.revise(tournament, plan, 'suggest')
        self.assertEqual(plan['rows'][0]['clan_id'], self.clan.pk)
        self.publish(tournament, plan)
        self.assertEqual(tournament.registrations.get(team=self.teams[0]).draw_clan, self.clan)

    def test_stale_preview_rejected_after_registration_seed_and_roster_changes(self):
        for mutation in ('registration', 'seed', 'roster', 'rule'):
            with self.subTest(mutation=mutation):
                tournament = self.tournament(4)
                plan = self.preview(tournament)
                if mutation == 'registration':
                    TournamentRegistration.objects.create(tournament=tournament, team=self.teams[4])
                elif mutation == 'seed':
                    tournament.registrations.filter(team=self.teams[0]).update(seed=1)
                elif mutation == 'roster':
                    TeamMember.objects.filter(team=self.teams[0]).update(status=TeamMember.Status.PENDING)
                else:
                    tournament.roster_rule = Tournament.RosterRule.ALLOW_INCOMPLETE
                    tournament.save()
                with self.assertRaisesMessage(TournamentError, 'seit der Vorschau'):
                    self.publish(tournament, plan)
                self.assertFalse(tournament.matches.exists())
                if mutation == 'roster':
                    TeamMember.objects.filter(team=self.teams[0]).update(status=TeamMember.Status.ACCEPTED)

    def test_token_permissions_and_invalid_inputs(self):
        tournament = self.tournament()
        plan = self.preview(tournament)
        with self.assertRaises(PermissionDenied):
            TournamentDrawService.preview(tournament.pk, actor=self.guest)
        with self.assertRaises(TournamentError):
            TournamentDrawService.publish(tournament.pk, actor=self.other_staff, token=plan['token'])
        with self.assertRaises(TournamentError):
            self.publish(tournament, {**plan, 'token': plan['token'] + 'x'})
        with self.assertRaises(TournamentError):
            self.revise(tournament, plan, clans={str(plan['rows'][0]['id']): self.clan.pk})
        with self.assertRaises(TournamentError):
            self.revise(tournament, plan, 'swap', swap_first=True, swap_second=plan['rows'][1]['id'])
        claim = signing.loads(plan['token'], salt=TOKEN_SALT)
        claim['order'][0] = claim['order'][1]
        bad = signing.dumps(claim, salt=TOKEN_SALT)
        with self.assertRaises(TournamentError):
            self.publish(tournament, {**plan, 'token': bad})

    def test_exact_publication_is_idempotent_and_history_survives_reset(self):
        tournament = self.tournament()
        plan = self.revise(tournament, self.preview(tournament))
        first, created = self.publish(tournament, plan)
        match_ids = list(tournament.matches.values_list('pk', flat=True))
        second, created_again = self.publish(tournament, plan)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(list(tournament.matches.values_list('pk', flat=True)), match_ids)
        with self.assertRaises(ValidationError):
            first.save()
        TournamentBracketService.reset_bracket(tournament.pk, actor=self.staff)
        self.assertTrue(TournamentDraw.objects.filter(pk=first.pk).exists())

    def test_routes_preview_revise_publish_and_csrf(self):
        tournament = self.tournament()
        self.client.force_login(self.staff)
        url = reverse('tournament_draw_preview', args=[tournament.slug])
        response = self.client.get(url)
        self.assertContains(response, 'Clan-Vorschläge übernehmen')
        self.assertContains(response, 'id="draw-confirm"')
        self.assertContains(response, 'js/tournament-draw.js')
        plan = response.context['plan']
        data = {'preview_token': plan['token'], 'action': 'shuffle', 'respect_seeds': 'yes', 'avoid_clans': 'yes',
                **{f"clan_{row['id']}": '' for row in plan['rows']}}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        plan = response.context['plan']
        start = reverse('tournament_generate_bracket', args=[tournament.slug])
        self.assertRedirects(self.client.post(start), url)
        self.assertFalse(tournament.matches.exists())
        self.client.post(start, {'preview_token': plan['token']})
        self.assert_published_pairs(tournament, plan)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        self.assertEqual(csrf_client.post(start, {'preview_token': plan['token']}).status_code, 403)

    def test_admin_actions_open_preview_and_journal_is_read_only(self):
        tournament = self.tournament()
        request = RequestFactory().post('/admin/tournaments/tournament/')
        request.user = self.staff
        model_admin = TournamentAdmin(Tournament, admin.site)
        response = model_admin.action_close_registration_and_generate_bracket(request, [tournament])
        self.assertEqual(response.url, reverse('tournament_draw_preview', args=[tournament.slug]))
        self.assertFalse(tournament.matches.exists())
        journal_admin = TournamentDrawAdmin(TournamentDraw, admin.site)
        self.assertFalse(journal_admin.has_add_permission(request))
        self.assertFalse(journal_admin.has_change_permission(request))
        self.assertFalse(journal_admin.has_delete_permission(request))

    def test_expired_drafts_are_rejected(self):
        tournament = self.tournament()
        plan = self.preview(tournament)
        expired_time = time.time() + TOKEN_MAX_AGE + 5
        with patch('django.core.signing.time.time', return_value=expired_time), self.assertRaises(TournamentError):
            self.publish(tournament, plan)
        self.assertFalse(tournament.matches.exists())

    def test_revoked_management_rights_are_checked_at_publication(self):
        tournament = self.tournament()
        plan = self.preview(tournament)
        User.objects.filter(pk=self.staff.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.publish(tournament, plan)
        self.assertFalse(tournament.matches.exists())

    def test_terminal_statuses_and_event_end_block_preview(self):
        for status in (Tournament.Status.DRAFT, Tournament.Status.CANCELLED, Tournament.Status.FINISHED):
            with self.subTest(status=status):
                tournament = self.tournament()
                Tournament.objects.filter(pk=tournament.pk).update(status=status)
                with self.assertRaises(TournamentError):
                    self.preview(tournament)
        tournament = self.tournament()
        Event.objects.filter(pk=self.event.pk).update(start_date=timezone.now() - timedelta(days=2),
            end_date=timezone.now() - timedelta(hours=1))
        with self.assertRaises(TournamentError):
            self.preview(tournament)

    def test_withdrawn_teams_are_excluded_and_clan_assignment_is_frozen_after_start(self):
        tournament = self.tournament(5)
        tournament.registrations.filter(team=self.teams[4]).update(is_forfeited=True)
        plan = self.preview(tournament)
        self.assertEqual(len(plan['rows']), 4)
        self.publish(tournament, plan)
        registration = tournament.registrations.first()
        registration.draw_clan = self.clan
        with self.assertRaises(ValidationError):
            registration.save()
        self.assertFalse(tournament.matches.filter(team1=self.teams[4]).exists())
        self.assertFalse(tournament.matches.filter(team2=self.teams[4]).exists())

    def test_invalid_roster_blocks_publication_atomically_even_with_fresh_draft(self):
        tournament = self.tournament()
        TeamMember.objects.filter(team=self.teams[0]).update(status=TeamMember.Status.PENDING)
        plan = self.preview(tournament)
        with self.assertRaises(TournamentError):
            self.publish(tournament, plan)
        self.assertFalse(tournament.matches.exists())
        self.assertFalse(tournament.draw_logs.exists())
        tournament.refresh_from_db()
        self.assertFalse(tournament.is_generated)

    def test_group_matching_minimizes_conflicts_for_large_clan(self):
        for members, expected in ((4, 2), (5, 4), (6, 6), (8, 12)):
            with self.subTest(members=members):
                tournament = self.tournament(8, Tournament.Mode.GROUP_STAGE, clans=[self.clan] * members)
                plan = self.revise(tournament, self.preview(tournament))
                self.assertEqual(plan['conflict_count'], expected)

    def test_restart_copies_confirmed_clan_associations_without_matches(self):
        from .services.restart import TournamentRestartService
        tournament = self.tournament(4, clans=[self.clan, self.other_clan])
        plan = self.preview(tournament)
        self.publish(tournament, plan)
        restart = TournamentRestartService.preview(tournament.pk, actor=self.staff)
        now = timezone.now()
        edition, created = TournamentRestartService.create(tournament.pk, actor=self.staff,
            preview_token=restart['token'], title='Draw restart', registration_start=now,
            registration_end=now + timedelta(hours=2), registration_ids=[row['id'] for row in restart['registrations']],
            reason='Neue Ausgabe mit bestätigten Clans.')
        self.assertTrue(created)
        self.assertEqual(edition.registrations.get(team=self.teams[0]).draw_clan, self.clan)
        self.assertFalse(edition.matches.exists())
