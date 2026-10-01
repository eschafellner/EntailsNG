"""Regression cases found during the review of all tournament formats."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventRegistration
from tournaments.exceptions import TournamentError
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentRegistration, TournamentMatch
from tournaments.services import (TournamentBracketService, TournamentMatchService, FFAMatchService,
    TournamentRegistrationService, GroupStageStandingService, forfeit_team_in_active_tournaments)


class TournamentAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.staff = get_user_model().objects.create_user('audit-orga', is_staff=True)
        cls.event = Event.objects.create(title='Audit LAN', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=now, end_date=now+timedelta(days=2))
        cls.game = Game.objects.create(name='Audit game', team_size=1)
        cls.team_game = Game.objects.create(name='Audit team game', team_size=2)
        cls.teams = []
        for number in range(16):
            user = get_user_model().objects.create_user(f'audit-player-{number}')
            team = Team.objects.create(name=f'Audit team {number}', game=cls.game, captain=user, event=cls.event)
            TeamMember.objects.create(team=team, user=user, role=TeamMember.Role.CAPTAIN)
            EventRegistration.objects.create(user=user, event=cls.event, is_checked_in=True)
            cls.teams.append(team)

    def tournament(self, mode=Tournament.Mode.SINGLE_ELIMINATION, count=4):
        now = timezone.now()
        tournament = Tournament.objects.create(title=f'Audit {mode}', event=self.event, game=self.game,
            mode=mode, swiss_rounds=1, status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=now-timedelta(hours=2), registration_end=now+timedelta(hours=1))
        for seed, team in enumerate(self.teams[:count], 1):
            TournamentRegistration.objects.create(tournament=tournament, team=team, seed=seed)
        return tournament

    def start(self, mode=Tournament.Mode.SINGLE_ELIMINATION, count=4):
        tournament = self.tournament(mode, count)
        TournamentBracketService.generate_bracket(tournament.pk, actor=self.staff)
        tournament.refresh_from_db()
        return tournament

    def test_cancelled_tournaments_cannot_be_started(self):
        for mode in Tournament.Mode.values:
            with self.subTest(mode=mode):
                tournament = self.tournament(mode)
                Tournament.objects.filter(pk=tournament.pk).update(status=Tournament.Status.CANCELLED)
                with self.assertRaises(TournamentError):
                    TournamentBracketService.generate_bracket(tournament.pk, actor=self.staff)
                self.assertFalse(tournament.matches.exists())

    def test_cancelled_matches_cannot_change_results_or_reopen_tournament(self):
        for mode in (Tournament.Mode.SINGLE_ELIMINATION, Tournament.Mode.DOUBLE_ELIMINATION,
                     Tournament.Mode.LEAGUE, Tournament.Mode.GROUP_STAGE, Tournament.Mode.SWISS):
            with self.subTest(mode=mode):
                tournament = self.start(mode)
                match = tournament.matches.filter(status=TournamentMatch.Status.READY, is_bye=False).first()
                Tournament.objects.filter(pk=tournament.pk).update(status=Tournament.Status.CANCELLED)
                with self.assertRaises(TournamentError):
                    TournamentMatchService.update_match_score(match.pk, 1, 0, actor=self.staff)
                with self.assertRaises(TournamentError):
                    TournamentBracketService.reset_bracket(tournament.pk, actor=self.staff)
                match.refresh_from_db()
                self.assertIsNone(match.winner_id)

    def test_closed_event_blocks_generation_reset_and_scoring(self):
        tournament = self.start()
        not_started = self.tournament()
        match = tournament.matches.filter(status=TournamentMatch.Status.READY).first()
        for status in (Event.Status.FINISHED, Event.Status.CANCELLED):
            with self.subTest(status=status):
                Event.objects.filter(pk=self.event.pk).update(status=status)
                for action in (
                    lambda: TournamentBracketService.generate_bracket(not_started.pk, actor=self.staff),
                    lambda: TournamentBracketService.reset_bracket(tournament.pk, actor=self.staff),
                    lambda: TournamentMatchService.update_match_score(match.pk, 1, 0, actor=self.staff),
                ):
                    with self.assertRaises(TournamentError):
                        action()

    def test_solo_registration_prefers_current_team_and_preserves_other_archive(self):
        user = self.teams[0].captain
        old_event = Event.objects.create(title='Old solo LAN', start_date=timezone.now()-timedelta(days=5),
            end_date=timezone.now()-timedelta(days=3), status=Event.Status.FINISHED)
        old = Team.objects.create(name='Old solo', captain=user, game=self.game, event=old_event,
                                  is_solo=True, is_archived=True)
        TeamMember.objects.create(team=old, user=user, role=TeamMember.Role.CAPTAIN)
        tournament = self.tournament(count=0)
        registration, _ = TournamentRegistrationService.register_team(tournament.pk, user, actor=user)
        self.assertNotEqual(registration.team_id, old.pk)
        self.assertEqual(registration.team_id, self.teams[0].pk)
        self.assertEqual(registration.team.event_id, self.event.pk)
        self.assertFalse(registration.team.is_archived)
        old.refresh_from_db()
        self.assertTrue(old.is_archived)
        self.assertEqual(old.event_id, old_event.pk)

    def test_invalid_team_and_game_ids_do_not_cause_server_errors(self):
        self.client.force_login(self.staff)
        tournament = self.tournament(count=0)
        tournament.game = self.team_game
        tournament.save()
        for value in ('abc', '1.5', str(2**100)):
            with self.subTest(value=value):
                self.assertEqual(self.client.post(reverse('tournament_register', args=[tournament.slug]),
                    {'team_id': value}).status_code, 302)
                self.assertEqual(self.client.post(reverse('tournament_unregister', args=[tournament.slug]),
                    {'team_id': value}).status_code, 302)
                self.assertEqual(self.client.post(reverse('team_create'),
                    {'name': 'Malformed', 'game_id': value}).status_code, 302)
        self.assertFalse(tournament.registrations.exists())

    def test_participant_malformed_winner_id_returns_validation_error(self):
        tournament = self.start()
        match = tournament.matches.filter(status=TournamentMatch.Status.READY).first()
        self.client.force_login(match.team1.captain)
        response = self.client.post(reverse('match_update_score', args=[match.pk]),
            {'score_team1': 0, 'score_team2': 1, 'winner_id': 'abc'})
        self.assertEqual(response.status_code, 400)
        match.refresh_from_db()
        self.assertIsNone(match.winner_id)

    def test_participant_cannot_submit_a_self_win_score_with_opponent_selected(self):
        tournament = self.start(Tournament.Mode.LEAGUE)
        match = tournament.matches.first()
        self.client.force_login(match.team1.captain)
        response = self.client.post(reverse('match_update_score', args=[match.pk]),
            {'score_team1': 99, 'score_team2': 0, 'winner_id': match.team2_id, 'decision_reason': 'Override'})
        self.assertEqual(response.status_code, 400)
        match.refresh_from_db()
        self.assertIsNone(match.score_team1)

    def test_score_limits_and_missing_scores_are_validated(self):
        tournament = self.start(Tournament.Mode.LEAGUE)
        match = tournament.matches.first()
        self.client.force_login(self.staff)
        for payload in ({'score_team1': 2**63, 'score_team2': 0}, {'score_team1': 1},
                        {'score_team1': 1, 'score_team2': 0, 'decision_reason': 'x'*256}):
            with self.subTest(payload=payload):
                response = self.client.post(reverse('match_update_score', args=[match.pk]), payload)
                self.assertEqual(response.status_code, 400)
        with self.assertRaises(TournamentError):
            TournamentMatchService.update_match_score(match.pk, 1.5, 0, actor=self.staff)

    def test_ffa_partial_correction_cannot_leave_two_winners(self):
        tournament = self.start(Tournament.Mode.FFA)
        match = tournament.matches.first()
        participants = list(match.participants.order_by('pk'))
        scores = [{'participant_id': p.pk, 'rank': rank, 'score': 100-rank}
                  for rank, p in enumerate(participants, 1)]
        FFAMatchService.update_ffa_scores(match.pk, scores, actor=self.staff)
        with self.assertRaises(TournamentError):
            FFAMatchService.update_ffa_scores(match.pk,
                [{'participant_id': participants[1].pk, 'rank': 1, 'score': 100}], actor=self.staff)
        self.assertEqual(match.participants.filter(rank=1).count(), 1)

    def test_ffa_rejects_malformed_duplicate_and_out_of_range_entries_atomically(self):
        tournament = self.start(Tournament.Mode.FFA)
        match = tournament.matches.first()
        participants = list(match.participants.order_by('pk'))
        valid = [{'participant_id': p.pk, 'rank': rank, 'score': 100-rank}
                 for rank, p in enumerate(participants, 1)]
        for field, value in (('rank', -1), ('rank', 0), ('rank', 99), ('rank', 'abc'),
                             ('rank', 1.5), ('score', 'abc'), ('score', 2**63), ('notes', 'x'*256)):
            with self.subTest(field=field, value=value):
                scores = [dict(p) for p in valid]
                scores[1][field] = value
                with self.assertRaises(TournamentError):
                    FFAMatchService.update_ffa_scores(match.pk, scores, actor=self.staff)
                self.assertFalse(match.participants.exclude(rank=None).exists())
        for scores in (valid+[valid[1]], [valid[0], valid[1], valid[2], dict(valid[3], participant_id=99999)]):
            with self.assertRaises(TournamentError):
                FFAMatchService.update_ffa_scores(match.pk, scores, actor=self.staff)

    def test_cancelled_ffa_cannot_be_completed(self):
        tournament = self.start(Tournament.Mode.FFA)
        match = tournament.matches.first()
        Tournament.objects.filter(pk=tournament.pk).update(status=Tournament.Status.CANCELLED)
        with self.assertRaises(TournamentError):
            FFAMatchService.update_ffa_scores(match.pk,
                [{'participant_id': p.pk, 'rank': rank, 'score': 0}
                 for rank, p in enumerate(match.participants.all(), 1)], actor=self.staff)

    def test_withdrawn_group_winner_does_not_qualify_for_playoffs(self):
        tournament = self.start(Tournament.Mode.GROUP_STAGE)
        group_matches = list(tournament.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP))
        for match in group_matches:
            TournamentMatch.objects.filter(pk=match.pk).update(status=TournamentMatch.Status.COMPLETED,
                score_team1=1, score_team2=0, winner=match.team1, loser=match.team2)
        leader = GroupStageStandingService.calculate_group_standings(tournament, 'Gruppe A')[0]['team']
        TournamentRegistration.objects.filter(tournament=tournament, team=leader).update(is_forfeited=True)
        GroupStageStandingService.check_and_advance_group_stage(tournament)
        final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.FINAL)
        self.assertNotIn(leader.pk, (final.team1_id, final.team2_id))
        self.assertEqual(final.status, TournamentMatch.Status.READY)

    def test_group_preview_shows_planned_playoffs(self):
        tournament = self.tournament(Tournament.Mode.GROUP_STAGE, count=8)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('tournament_detail', args=[tournament.slug]))
        self.assertContains(response, 'Geplante KO-Phase')

    def test_archived_or_previous_event_teams_cannot_gain_members(self):
        self.client.force_login(self.teams[1].captain)
        team = self.teams[0]
        Team.objects.filter(pk=team.pk).update(game=self.team_game, is_archived=True)
        self.client.post(reverse('team_join_by_code'), {'invite_code': team.invite_code})
        self.assertFalse(team.memberships.filter(user=self.teams[1].captain).exists())
        self.client.post(reverse('team_apply', args=[team.slug]))
        self.assertFalse(team.memberships.filter(user=self.teams[1].captain).exists())
        pending = TeamMember.objects.create(team=team, user=self.teams[1].captain, status=TeamMember.Status.PENDING)
        self.client.force_login(team.captain)
        self.client.post(reverse('team_accept_membership', args=[team.slug, pending.pk]))
        pending.refresh_from_db()
        self.assertEqual(pending.status, TeamMember.Status.PENDING)

    def test_reactivation_cannot_overfill_a_smaller_game(self):
        team = self.teams[0]
        Team.objects.filter(pk=team.pk).update(is_archived=True)
        for other in self.teams[1:3]:
            TeamMember.objects.create(team=team, user=other.captain)
        self.client.force_login(team.captain)
        response = self.client.post(reverse('team_reactivate', args=[team.slug]),
            {'game_id': self.team_game.pk, 'keep_members': [t.captain_id for t in self.teams[:3]]})
        self.assertEqual(response.status_code, 302)
        team.refresh_from_db()
        self.assertTrue(team.is_archived)

    def finish_legacy_matches(self, tournament, *, reverse=False):
        for step in range(300):
            tournament.refresh_from_db()
            if tournament.status == Tournament.Status.FINISHED:
                break
            ready = tournament.matches.filter(status=TournamentMatch.Status.READY, is_bye=False).order_by('round_number', 'pk').first()
            self.assertIsNotNone(ready, f'{tournament.mode}: blocked after {step} games')
            self.assertNotEqual(ready.team1_id, ready.team2_id)
            self.assertIsNotNone(ready.team1_id)
            self.assertIsNotNone(ready.team2_id)
            second_wins = reverse and step % 2 == 0
            # Exercise the grand-final reset for the second DE path.
            if reverse and ready.bracket_type == TournamentMatch.BracketType.GRAND_FINAL:
                second_wins = True
            TournamentMatchService.update_match_score(ready.pk,
                0 if second_wins else 1, 1 if second_wins else 0, actor=self.staff)
        self.assertEqual(tournament.status, Tournament.Status.FINISHED)
        self.assertFalse(tournament.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists())

    def test_complete_brackets_for_two_to_sixteen_teams(self):
        for mode in (Tournament.Mode.SINGLE_ELIMINATION, Tournament.Mode.DOUBLE_ELIMINATION,
                     Tournament.Mode.LEAGUE, Tournament.Mode.GROUP_STAGE):
            for count in range(4 if mode == Tournament.Mode.GROUP_STAGE else 2, 17):
                for reverse in ([False, True] if mode == Tournament.Mode.DOUBLE_ELIMINATION else [False]):
                    with self.subTest(mode=mode, count=count, reverse=reverse):
                        tournament = self.start(mode, count)
                        self.finish_legacy_matches(tournament, reverse=reverse)
                        played = tournament.matches.filter(is_bye=False)
                        if mode == Tournament.Mode.LEAGUE:
                            self.assertEqual(played.count(), count * (count-1)//2)
                            pairs = {frozenset((m.team1_id, m.team2_id)) for m in played}
                            self.assertEqual(len(pairs), played.count())
                        if mode == Tournament.Mode.DOUBLE_ELIMINATION:
                            losses = {team.pk: 0 for team in self.teams[:count]}
                            for match in played:
                                losses[match.loser_id] += 1
                            self.assertEqual(sum(value < 2 for value in losses.values()), 1)

    def test_withdrawals_preserve_history_of_cancelled_tournaments(self):
        for mode in Tournament.Mode.values:
            with self.subTest(mode=mode):
                tournament = self.start(mode)
                before = list(tournament.matches.values('pk', 'team1_id', 'team2_id', 'winner_id', 'status'))
                Tournament.objects.filter(pk=tournament.pk).update(status=Tournament.Status.CANCELLED)
                forfeit_team_in_active_tournaments(self.teams[0])
                self.assertEqual(before, list(tournament.matches.values('pk', 'team1_id', 'team2_id', 'winner_id', 'status')))
                self.assertFalse(tournament.registrations.filter(is_forfeited=True).exists())

    def test_withdrawals_do_not_block_legacy_formats(self):
        for mode in (Tournament.Mode.SINGLE_ELIMINATION, Tournament.Mode.DOUBLE_ELIMINATION,
                     Tournament.Mode.LEAGUE, Tournament.Mode.GROUP_STAGE):
            for count in (4, 5, 8):
                with self.subTest(mode=mode, count=count):
                    tournament = self.start(mode, count)
                    forfeit_team_in_active_tournaments(self.teams[0])
                    self.finish_legacy_matches(tournament)
                    self.assertTrue(tournament.registrations.get(team=self.teams[0]).is_forfeited)

    def test_public_generator_preserves_existing_results(self):
        from tournaments.services import generate_bracket
        tournament = self.start()
        before = list(tournament.matches.values_list('pk', flat=True))
        with self.assertRaises(TournamentError):
            generate_bracket(tournament)
        self.assertEqual(before, list(tournament.matches.values_list('pk', flat=True)))

    def test_ffa_view_rejects_partial_form_without_changing_any_results(self):
        tournament = self.start(Tournament.Mode.FFA)
        match = tournament.matches.first()
        participants = list(match.participants.all())
        FFAMatchService.update_ffa_scores(match.pk,
            [{'participant_id': p.pk, 'rank': index, 'score': index*10} for index, p in enumerate(participants, 1)], actor=self.staff)
        before = list(match.participants.values('pk', 'rank', 'score'))
        self.client.force_login(self.staff)
        response = self.client.post(reverse('match_update_ffa_score', args=[match.pk]),
            {f'rank_{participants[1].pk}': 1, f'score_{participants[1].pk}': 999})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(before, list(match.participants.values('pk', 'rank', 'score')))

    def test_admin_form_displays_invalid_score_error_and_validates_without_saving(self):
        from tournaments.forms import TournamentMatchAdminForm
        tournament = self.start()
        match = tournament.matches.filter(status=TournamentMatch.Status.READY).first()
        class AdminForm(TournamentMatchAdminForm):
            actor = self.staff
            class Meta(TournamentMatchAdminForm.Meta):
                fields = ('score_team1', 'score_team2', 'winner', 'decision_reason')
        form = AdminForm(instance=match, data={'score_team1': 1, 'score_team2': 0, 'winner': match.team2_id})
        self.assertFalse(form.is_valid())
        self.assertIn('widerspricht', str(form.errors))
        match.refresh_from_db()
        form = AdminForm(instance=match, data={'score_team1': 1, 'score_team2': 0, 'winner': match.team1_id})
        self.assertTrue(form.is_valid(), form.errors)
        match.refresh_from_db()
        self.assertEqual(match.status, TournamentMatch.Status.READY)
        self.assertIsNone(match.score_team1)

    def test_swiss_status_cannot_reopen_registration_after_start(self):
        from django.core.exceptions import ValidationError
        tournament = self.start(Tournament.Mode.SWISS)
        tournament.status = Tournament.Status.REGISTRATION_OPEN
        with self.assertRaises(ValidationError):
            tournament.save()

    def test_pending_applicant_leaves_without_forfeiting_the_team(self):
        tournament = self.start()
        team = self.teams[0]
        applicant = self.teams[4].captain
        TeamMember.objects.create(team=team, user=applicant, status=TeamMember.Status.PENDING)
        self.assertEqual(team.leave_team(applicant, force_forfeit=True), 'left')
        self.assertFalse(tournament.registrations.get(team=team).is_forfeited)

    def test_previous_event_team_cannot_be_joined_without_reactivation(self):
        previous = Event.objects.create(title='Previous event', status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now(), end_date=timezone.now()+timedelta(days=2))
        team = self.teams[0]
        Team.objects.filter(pk=team.pk).update(event=previous, game=self.team_game)
        self.client.force_login(self.teams[1].captain)
        self.client.post(reverse('team_join_by_code'), {'invite_code': team.invite_code})
        self.assertFalse(team.memberships.filter(user=self.teams[1].captain).exists())

    def test_deleted_applicant_cannot_be_accepted(self):
        team = self.teams[0]
        Team.objects.filter(pk=team.pk).update(game=self.team_game)
        applicant = self.teams[4].captain
        get_user_model().objects.filter(pk=applicant.pk).update(is_active=False, deleted_at=timezone.now())
        pending = TeamMember.objects.create(team=team, user=applicant, status=TeamMember.Status.PENDING)
        self.client.force_login(team.captain)
        self.client.post(reverse('team_accept_membership', args=[team.slug, pending.pk]))
        pending.refresh_from_db()
        self.assertEqual(pending.status, TeamMember.Status.PENDING)

    def test_ffa_admin_cannot_edit_results_outside_the_scoring_service(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from tournaments.admin import TournamentMatchAdmin, TournamentMatchParticipantAdmin
        from tournaments.models import TournamentMatchParticipant
        request = RequestFactory().get('/admin/')
        request.user = self.staff
        tournament = self.start(Tournament.Mode.FFA)
        match = tournament.matches.first()
        admin = TournamentMatchAdmin(TournamentMatch, AdminSite())
        self.assertIn('winner', admin.get_readonly_fields(request, match))
        self.assertFalse(admin.has_add_permission(request))
        self.assertFalse(admin.has_delete_permission(request, match))
        self.assertNotIn('delete_selected', admin.get_actions(request))
        participant_admin = TournamentMatchParticipantAdmin(TournamentMatchParticipant, AdminSite())
        self.assertIn('rank', participant_admin.get_readonly_fields(request, match.participants.first()))

    def test_ffa_scoring_cannot_restore_a_withdrawn_participant(self):
        tournament = self.start(Tournament.Mode.FFA)
        match = tournament.matches.first()
        forfeit_team_in_active_tournaments(self.teams[0])
        participants = list(match.participants.order_by('pk'))
        scores = [{'participant_id': p.pk, 'rank': index, 'score': 10, 'is_disqualified': False}
                  for index, p in enumerate(participants, 1)]
        with self.assertRaises(TournamentError):
            FFAMatchService.update_ffa_scores(match.pk, scores, actor=self.staff)
        scores[0]['rank'], scores[1]['rank'] = 2, 1
        FFAMatchService.update_ffa_scores(match.pk, scores, actor=self.staff)
        self.assertTrue(match.participants.get(team=self.teams[0]).is_disqualified)

    def test_shared_ffa_places_are_preserved_in_certificates(self):
        from tournaments.services import TournamentPodiumService
        from media_designer.data import certificate_rows
        tournament = self.start(Tournament.Mode.FFA)
        match = tournament.matches.first()
        participants = list(match.participants.order_by('pk'))
        FFAMatchService.update_ffa_scores(match.pk,
            [{'participant_id': p.pk, 'rank': rank, 'score': 10}
             for p, rank in zip(participants, (1, 2, 2, 4))], actor=self.staff)
        tournament.refresh_from_db()
        self.assertIsNone(TournamentPodiumService.calculate(tournament)['second'])
        rows = certificate_rows([p.team for p in participants], tournament, 'Audit')
        self.assertEqual([row['team.placement'] for row in rows], ['1. Platz', '2. Platz', '2. Platz', '4. Platz'])

    def test_certificates_receive_results_from_all_six_formats(self):
        from media_designer.data import certificate_rows
        for mode in Tournament.Mode.values:
            with self.subTest(mode=mode):
                tournament = self.start(mode)
                if mode == Tournament.Mode.FFA:
                    match = tournament.matches.first()
                    FFAMatchService.update_ffa_scores(match.pk,
                        [{'participant_id': p.pk, 'rank': index, 'score': 10}
                         for index, p in enumerate(match.participants.order_by('pk'), 1)], actor=self.staff)
                elif mode == Tournament.Mode.SWISS:
                    for match in tournament.matches.filter(is_bye=False):
                        TournamentMatchService.update_match_score(match.pk, 1, 0, actor=self.staff)
                else:
                    self.finish_legacy_matches(tournament)
                tournament.refresh_from_db()
                rows = certificate_rows(self.teams[:4], tournament, 'Audit')
                self.assertTrue(any(row['team.placement'] == '1. Platz' for row in rows))
                self.assertTrue(all(row['tournament.title'] == tournament.title for row in rows))

    def test_admin_invalid_result_is_a_form_error_instead_of_server_error(self):
        get_user_model().objects.filter(pk=self.staff.pk).update(is_superuser=True)
        self.staff.refresh_from_db()
        self.client.force_login(self.staff)
        tournament = self.start()
        match = tournament.matches.filter(status=TournamentMatch.Status.READY).first()
        data = {'score_team1': 2, 'score_team2': 0, 'winner': match.team2_id,
                'decision_reason': '', 'group_name': '', '_save': 'Speichern',
                'participants-TOTAL_FORMS': 0, 'participants-INITIAL_FORMS': 0,
                'participants-MIN_NUM_FORMS': 0, 'participants-MAX_NUM_FORMS': 1000}
        url = reverse('admin:tournaments_tournamentmatch_change', args=[match.pk])
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'widerspricht')
        match.refresh_from_db()
        self.assertEqual(match.status, TournamentMatch.Status.READY)
        data['winner'] = match.team1_id
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        match.refresh_from_db()
        self.assertEqual(match.status, TournamentMatch.Status.COMPLETED)

    def test_cancelled_tournament_hides_result_buttons(self):
        tournament = self.start()
        Tournament.objects.filter(pk=tournament.pk).update(status=Tournament.Status.CANCELLED)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('tournament_detail', args=[tournament.slug]))
        self.assertNotContains(response, 'data-score-url=')

    def test_solo_registration_reuses_the_current_single_player_team(self):
        tournament = self.tournament(count=0)
        team = self.teams[0]
        registration, _ = TournamentRegistrationService.register_team(tournament.pk, team.captain, actor=team.captain)
        self.assertEqual(registration.team_id, team.pk)
        self.assertEqual(TeamMember.objects.filter(user=team.captain, status=TeamMember.Status.ACCEPTED,
            team__game=self.game, team__is_archived=False).count(), 1)

    def test_cancelled_event_ticket_does_not_grant_tournament_checkin(self):
        user = self.teams[0].captain
        EventRegistration.objects.filter(user=user, event=self.event).update(payment_status=EventRegistration.PaymentStatus.CANCELLED)
        tournament = self.tournament(count=0)
        with self.assertRaises(TournamentError):
            TournamentRegistrationService.register_team(tournament.pk, user, actor=user)
        self.assertFalse(tournament.registrations.exists())

    def test_admin_cannot_change_or_delete_active_rosters_and_registrations(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from tournaments.admin import TeamMemberAdmin, TournamentRegistrationAdmin
        tournament = self.start()
        request = RequestFactory().get('/admin/')
        request.user = self.staff
        member = self.teams[0].memberships.first()
        admin = TeamMemberAdmin(TeamMember, AdminSite())
        self.assertIn('status', admin.get_readonly_fields(request, member))
        self.assertFalse(admin.has_delete_permission(request, member))
        self.assertNotIn('delete_selected', admin.get_actions(request))
        self.assertNotIn(self.teams[0], admin.formfield_for_foreignkey(TeamMember._meta.get_field('team'), request).queryset)
        registration_admin = TournamentRegistrationAdmin(TournamentRegistration, AdminSite())
        registration = tournament.registrations.first()
        self.assertIn('team', registration_admin.get_readonly_fields(request, registration))
        self.assertFalse(registration_admin.has_delete_permission(request, registration))

    def test_long_usernames_and_repeated_tournament_titles_fit_database_limits(self):
        user = get_user_model().objects.create_user('x'*150)
        EventRegistration.objects.create(user=user, event=self.event, is_checked_in=True)
        now = timezone.now()
        first = Tournament.objects.create(title='x'*150, game=self.game, event=self.event,
            status=Tournament.Status.REGISTRATION_OPEN, registration_start=now-timedelta(hours=1), registration_end=now+timedelta(hours=1))
        second = Tournament.objects.create(title='x'*150, game=self.game, event=self.event,
            registration_start=now, registration_end=now+timedelta(hours=1))
        self.assertLessEqual(len(first.slug), 150)
        self.assertLessEqual(len(second.slug), 150)
        self.assertNotEqual(first.slug, second.slug)
        registration, _ = TournamentRegistrationService.register_team(first.pk, user, actor=user)
        self.assertLessEqual(len(registration.team.name), 32)
        registration.team.full_clean()

    def test_organizer_start_revalidates_rosters_in_every_format(self):
        for mode in Tournament.Mode.values:
            with self.subTest(mode=mode):
                tournament = self.tournament(mode)
                membership = self.teams[0].memberships.first()
                membership.status = TeamMember.Status.PENDING
                membership.save(update_fields=['status'])
                with self.assertRaises(TournamentError):
                    TournamentBracketService.generate_bracket(tournament.pk, actor=self.staff)
                self.assertFalse(tournament.matches.exists())
                membership.status = TeamMember.Status.ACCEPTED
                membership.save(update_fields=['status'])

    def test_organizer_start_rejects_archived_foreign_game_and_duplicate_players(self):
        tournament = self.tournament()
        team = self.teams[0]
        for field, invalid, original in (('is_archived', True, False), ('game_id', self.team_game.pk, self.game.pk)):
            Team.objects.filter(pk=team.pk).update(**{field: invalid})
            with self.assertRaises(TournamentError):
                TournamentBracketService.generate_bracket(tournament.pk, actor=self.staff)
            Team.objects.filter(pk=team.pk).update(**{field: original})
        second = self.teams[1]
        second.memberships.update(user=team.captain)
        Team.objects.filter(pk=second.pk).update(captain=team.captain)
        with self.assertRaises(TournamentError):
            TournamentBracketService.generate_bracket(tournament.pk, actor=self.staff)
