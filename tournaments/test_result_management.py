"""Result editing, dependency integrity, review, admin and HTTP regressions."""
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from tournaments import test_audit as audit
from tournaments.models import Tournament, TournamentMatch, TournamentResultLog
from tournaments.exceptions import TournamentError
from tournaments.services import TournamentMatchService as Scores, FFAMatchService, TournamentLifecycleService as Life
from tournaments.services.results import match_version, tournament_version


class ResultManagementTests(TestCase):
    setUpTestData = classmethod(audit.TournamentAuditTests.setUpTestData.__func__)
    tournament = audit.TournamentAuditTests.tournament
    start = audit.TournamentAuditTests.start

    def play(self, match, a=2, b=0, reason=None):
        return Scores.update_match_score(match.pk, a, b, actor=self.staff, decision_reason=reason)

    def finish_games(self, tournament):
        for _ in range(200):
            tournament.refresh_from_db()
            if tournament.status == Tournament.Status.RESULTS_REVIEW:
                return
            if tournament.mode == Tournament.Mode.GROUP_STAGE and not tournament.playoffs_released_at:
                groups = tournament.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP)
                if not groups.exclude(status=TournamentMatch.Status.COMPLETED).exists():
                    Life.release_playoffs(tournament.pk, actor=self.staff)
            match = tournament.matches.filter(status=TournamentMatch.Status.READY, is_bye=False).first()
            self.assertIsNotNone(match)
            self.play(match)
        self.fail('Never reached review')

    def test_final_can_be_corrected_before_confirmation(self):
        t = self.start(count=2)
        m = t.matches.get(is_bye=False)
        self.play(m)
        t.refresh_from_db()
        self.assertEqual(t.status, Tournament.Status.RESULTS_REVIEW)
        self.play(m, 0, 2, 'Ergebnis vertauscht')
        m.refresh_from_db()
        self.assertEqual(m.winner_id, m.team2_id)
        self.assertEqual(t.result_logs.filter(action='RESULT').count(), 2)
        Life.confirm_results(t.pk, actor=self.staff)
        t.refresh_from_db()
        self.assertEqual(t.status, Tournament.Status.FINISHED)
        self.assertEqual(t.results_confirmed_by, self.staff)
        with self.assertRaises(TournamentError):
            self.play(m, 2, 0, 'Korrektur')

    def test_confirmation_requires_all_results_and_permissions(self):
        t = self.start()
        for actor in (self.staff, self.teams[0].captain):
            with self.assertRaises(TournamentError):
                Life.confirm_results(t.pk, actor=actor)
        self.assertFalse(t.result_logs.exists())

    def test_correction_requires_reason_and_preserves_original_on_failure(self):
        t = self.start()
        m = t.matches.filter(status='READY').first()
        self.play(m)
        with self.assertRaises(TournamentError):
            self.play(m, 0, 2)
        m.refresh_from_db()
        self.assertEqual(m.winner_id, m.team1_id)
        self.assertEqual(t.result_logs.filter(action='RESULT').count(), 1)

    def test_winner_change_updates_waiting_next_match(self):
        t = self.start()
        m = t.matches.filter(status='READY').first()
        self.play(m)
        self.play(m, 0, 2, 'Falscher Sieger')
        nxt = TournamentMatch.objects.get(pk=m.next_match_winner_id)
        self.assertEqual(getattr(nxt, f'team{m.next_match_winner_slot}_id'), m.team2_id)
        self.assertEqual(nxt.status, TournamentMatch.Status.PENDING)
        self.assertTrue(t.result_logs.filter(action='DEPENDENCY').exists())

    def test_started_followup_blocks_winner_but_allows_score_change(self):
        t = self.start()
        prelim = list(t.matches.filter(status='READY'))
        for m in prelim:
            self.play(m)
        nxt = t.matches.get(bracket_type=TournamentMatch.BracketType.FINAL)
        Life.start_match(nxt.pk, actor=self.staff)
        m = prelim[0]
        self.play(m, 3, 0, 'Punktestand korrigiert')
        with self.assertRaises(TournamentError):
            self.play(m, 0, 3, 'Sieger korrigiert')
        nxt.refresh_from_db()
        self.assertEqual(nxt.status, TournamentMatch.Status.IN_PROGRESS)
        self.assertEqual(getattr(nxt, f'team{m.next_match_winner_slot}_id'), m.team1_id)

    def test_played_followup_allows_score_correction(self):
        t = self.start(count=8)
        m = t.matches.filter(status='READY').first()
        self.play(m)
        sibling = t.matches.filter(next_match_winner_id=m.next_match_winner_id).exclude(pk=m.pk).get()
        self.play(sibling)
        nxt = TournamentMatch.objects.get(pk=m.next_match_winner_id)
        self.play(nxt)
        self.play(m, 3, 0, 'Punkte')
        nxt.refresh_from_db()
        self.assertEqual(nxt.status, TournamentMatch.Status.COMPLETED)
        self.assertEqual(nxt.score_team1, 2)

    def test_double_elimination_updates_winner_and_loser_slots(self):
        t = self.start(Tournament.Mode.DOUBLE_ELIMINATION, 8)
        m = t.matches.filter(status='READY', bracket_type=TournamentMatch.BracketType.WINNERS).first()
        self.play(m)
        self.play(m, 0, 2, 'Vertauscht')
        m.refresh_from_db()
        for field, slot_field, expected in [('next_match_winner_id', 'next_match_winner_slot', m.team2_id), ('next_match_loser_id', 'next_match_loser_slot', m.team1_id)]:
            nxt = TournamentMatch.objects.get(pk=getattr(m, field))
            self.assertEqual(getattr(nxt, f'team{getattr(m, slot_field)}_id'), expected)

    def test_winner_changes_rebuild_automatic_bye_chains_in_irregular_fields(self):
        from .services.results import descendants, snapshot
        saw_automatic = False
        for count in (3, 5, 6, 7, 9):
            with self.subTest(count=count):
                t = self.start(Tournament.Mode.DOUBLE_ELIMINATION, count)
                m = t.matches.filter(status='READY', is_bye=False).first()
                self.play(m)
                affected = {row.pk for row in descendants(m)}
                saw_automatic |= t.matches.filter(pk__in=affected, is_bye=True).exists()
                untouched = {row.pk: snapshot(row) for row in t.matches.exclude(pk__in=affected | {m.pk})}
                self.play(m, 0, 2, 'Sieger korrigiert')
                for row in t.matches.filter(pk__in=affected):
                    for slot in (1, 2):
                        expected = [f.winner_id for f in row.prev_matches_winner.filter(next_match_winner_slot=slot, status='COMPLETED')]
                        expected += [f.loser_id for f in row.prev_matches_loser.filter(next_match_loser_slot=slot, status='COMPLETED')]
                        expected = [pk for pk in expected if pk is not None]
                        if expected:
                            self.assertEqual(getattr(row, f'team{slot}_id'), expected[0])
                self.assertEqual(untouched, {row.pk: snapshot(row) for row in t.matches.filter(pk__in=untouched)})
        self.assertTrue(saw_automatic)

    def test_automatic_walkover_is_logged_and_cannot_be_overwritten(self):
        from .services import forfeit_team_in_active_tournaments
        t = self.start(count=2)
        m = t.matches.get()
        forfeit_team_in_active_tournaments(m.team1)
        m.refresh_from_db()
        self.assertEqual(m.result_type, TournamentMatch.ResultType.WALKOVER)
        self.assertEqual(m.result_logs.filter(action='RESULT').get().after['result_type'], 'WALKOVER')
        with self.assertRaises(TournamentError):
            self.play(m, 2, 0, 'Überschreiben')

    def test_grand_final_correction_adds_and_removes_reset(self):
        t = self.start(Tournament.Mode.DOUBLE_ELIMINATION, 2)
        self.play(t.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS))
        gf = t.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL)
        self.play(gf)
        self.play(gf, 0, 2, 'Reset erforderlich')
        t.refresh_from_db()
        self.assertEqual(t.status, Tournament.Status.IN_PROGRESS)
        self.assertTrue(t.matches.filter(bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET).exists())
        self.play(gf, 2, 0, 'Reset entfällt')
        t.refresh_from_db()
        self.assertEqual(t.status, Tournament.Status.RESULTS_REVIEW)
        self.assertFalse(t.matches.filter(bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET).exists())
        self.assertTrue(t.result_logs.filter(after={'removed': True}).exists())

    def test_swiss_last_round_review_and_earlier_round_lock(self):
        from tournaments.services import SwissTournamentService
        t = self.tournament(Tournament.Mode.SWISS, 4)
        t.swiss_rounds = 2
        t.save()
        SwissTournamentService.publish(t.pk, actor=self.staff)
        for m in t.matches.all():
            self.play(m)
        old = t.matches.first()
        token = SwissTournamentService.preview(t.pk, actor=self.staff)['token']
        SwissTournamentService.publish(t.pk, actor=self.staff, token=token)
        with self.assertRaises(TournamentError):
            self.play(old, 0, 2, 'Vertauscht')
        for m in t.matches.filter(round_number=2):
            self.play(m)
        last = t.matches.filter(round_number=2).first()
        self.play(last, 0, 2, 'Vertauscht')
        t.refresh_from_db()
        self.assertEqual(t.status, Tournament.Status.RESULTS_REVIEW)
        Life.confirm_results(t.pk, actor=self.staff)

    def test_league_previous_round_can_change(self):
        t = self.start(Tournament.Mode.LEAGUE)
        m = t.matches.first()
        self.play(m)
        other = t.matches.filter(round_number__gt=m.round_number).first()
        self.play(other)
        self.play(m, 0, 2, 'Vertauscht')
        m.refresh_from_db()
        self.assertEqual(m.winner_id, m.team2_id)

    def test_playoffs_must_be_released_and_then_preserve_qualification(self):
        t = self.start(Tournament.Mode.GROUP_STAGE, 4)
        groups = list(t.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP))
        for m in groups:
            self.play(m)
        final = t.matches.get(bracket_type=TournamentMatch.BracketType.FINAL)
        with self.assertRaises(TournamentError):
            self.play(final)
        self.play(groups[0], 0, 2, 'Vertauscht')
        Life.release_playoffs(t.pk, actor=self.staff)
        with self.assertRaises(TournamentError):
            self.play(groups[0], 2, 0, 'Andere Qualifikation')
        self.play(groups[0], 0, 3, 'Nur Score')
        Life.start_match(final.pk, actor=self.staff)
        self.play(final)
        t.refresh_from_db()
        self.assertEqual(t.status, Tournament.Status.RESULTS_REVIEW)

    def test_stale_edit_and_confirmation_are_rejected(self):
        t = self.start(count=2)
        m = t.matches.get()
        old = match_version(m)
        self.play(m)
        token = tournament_version(t)
        with self.assertRaises(TournamentError):
            Scores.update_match_score(m.pk, 0, 2, actor=self.staff, decision_reason='Vertauscht', expected_state=old)
        self.play(m, 3, 0, 'Score')
        with self.assertRaises(TournamentError):
            Life.confirm_results(t.pk, actor=self.staff, expected_state=token)

    def test_ffa_review_correction_and_final_lock(self):
        t = self.start(Tournament.Mode.FFA)
        m = t.matches.get()
        scores = [{'participant_id': p.pk, 'rank': i, 'score': 100-i} for i, p in enumerate(m.participants.order_by('pk'), 1)]
        FFAMatchService.update_ffa_scores(m.pk, scores, actor=self.staff)
        t.refresh_from_db()
        self.assertEqual(t.status, Tournament.Status.RESULTS_REVIEW)
        scores[0]['rank'], scores[1]['rank'] = 2, 1
        FFAMatchService.update_ffa_scores(m.pk, scores, actor=self.staff, decision_reason='Ränge vertauscht')
        Life.confirm_results(t.pk, actor=self.staff)
        with self.assertRaises(TournamentError):
            FFAMatchService.update_ffa_scores(m.pk, scores, actor=self.staff, decision_reason='Korrektur')
        self.assertIn('participants', t.result_logs.filter(action='RESULT').first().before)

    def test_participants_cannot_correct_or_start_matches(self):
        t = self.start()
        m = t.matches.filter(status='READY').first()
        with self.assertRaises(TournamentError):
            Life.start_match(m.pk, actor=m.team1.captain)
        Scores.update_match_score(m.pk, 0, 2, actor=m.team1.captain)
        with self.assertRaises(TournamentError):
            Scores.update_match_score(m.pk, 0, 3, actor=m.team1.captain, decision_reason='Score')

    def test_admin_editor_supports_all_modes_and_enforces_permissions(self):
        superuser = get_user_model().objects.create_superuser('results-super', password='test')
        self.client.force_login(superuser)
        for mode in Tournament.Mode.values:
            t = self.start(mode)
            response = self.client.get(reverse('admin:tournaments_tournament_results', args=[t.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Ergebnisse verwalten')
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('admin:tournaments_tournament_results', args=[t.pk])).status_code, 403)

    def test_admin_post_and_history(self):
        superuser = get_user_model().objects.create_superuser('results-post', password='test')
        self.client.force_login(superuser)
        t = self.start(count=2)
        m = t.matches.get()
        url = reverse('admin:tournaments_tournament_results', args=[t.pk])
        response = self.client.post(url, {'action':'score', 'match_id':m.pk, 'score_team1':2, 'score_team2':0,
            'winner_id':'', 'decision_reason':'', 'expected_state':match_version(m)})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(url), 'Änderungshistorie')
        self.client.post(url, {'action':'confirm', 'expected_state':tournament_version(t)})
        t.refresh_from_db()
        self.assertEqual(t.status, Tournament.Status.FINISHED)
        self.assertEqual(t.result_logs.filter(action='CONFIRM').count(), 1)

    def test_correction_controls_are_only_visible_to_orga(self):
        t = self.start(count=2)
        m = t.matches.get()
        self.play(m)
        url = reverse('tournament_detail', args=[t.slug])
        self.client.force_login(m.team1.captain)
        self.assertNotContains(self.client.get(url), 'Ergebnis korrigieren')
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(url), 'Ergebnis korrigieren')

    def test_swiss_admin_form_remains_editable_during_review(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from tournaments.services import SwissTournamentService
        t = self.tournament(Tournament.Mode.SWISS, 2)
        t.swiss_rounds = 1
        t.save()
        SwissTournamentService.publish(t.pk, actor=self.staff)
        m = t.matches.get()
        self.play(m)
        m.refresh_from_db()
        request = RequestFactory().get('/')
        request.user = self.staff
        match_admin = admin.site._registry[TournamentMatch]
        self.assertNotIn('score_team1', match_admin.get_readonly_fields(request, m))
        Life.confirm_results(t.pk, actor=self.staff)
        m.refresh_from_db()
        self.assertIn('score_team1', match_admin.get_readonly_fields(request, m))

    def test_frontend_actions_post_only_and_csrf(self):
        t = self.start(count=2)
        m = t.matches.get()
        self.client.force_login(self.staff)
        for url in (reverse('match_start', args=[m.pk]), reverse('tournament_confirm_results', args=[t.slug]), reverse('tournament_release_playoffs', args=[t.slug])):
            self.assertEqual(self.client.get(url).status_code, 405)
            secure = Client(enforce_csrf_checks=True)
            secure.force_login(self.staff)
            self.assertEqual(secure.post(url).status_code, 403)
        self.play(m)
        self.assertContains(self.client.get(reverse('tournament_detail', args=[t.slug])), 'Ergebnis korrigieren')
        self.client.post(reverse('tournament_confirm_results', args=[t.slug]), {'expected_state': tournament_version(t)})
        t.refresh_from_db()
        self.assertEqual(t.status, Tournament.Status.FINISHED)

    def test_admin_and_frontend_release_require_the_displayed_results(self):
        user = get_user_model().objects.create_superuser('release-post', password='test')
        self.client.force_login(user)
        for backend in (True, False):
            with self.subTest(backend=backend):
                t = self.start(Tournament.Mode.GROUP_STAGE, 4)
                for m in t.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP):
                    self.play(m)
                url = (reverse('admin:tournaments_tournament_results', args=[t.pk]) if backend
                    else reverse('tournament_release_playoffs', args=[t.slug]))
                old = tournament_version(t)
                m = t.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP).first()
                self.play(m, 0, 2, 'Vertauscht')
                self.client.post(url, {'action': 'release', 'expected_state': old})
                t.refresh_from_db()
                self.assertIsNone(t.playoffs_released_at)
                self.assertEqual(self.client.post(url, {'action': 'release',
                    'expected_state': tournament_version(t)}).status_code, 302)
                t.refresh_from_db()
                self.assertIsNotNone(t.playoffs_released_at)

    def test_completed_event_blocks_review_confirmation(self):
        from events.models import Event
        t = self.start(count=2)
        self.play(t.matches.get())
        Event.objects.filter(pk=self.event.pk).update(status=Event.Status.FINISHED)
        with self.assertRaises(TournamentError):
            Life.confirm_results(t.pk, actor=self.staff)

    def test_bronze_must_be_scored_before_confirmation(self):
        t = self.tournament(count=4)
        t.play_third_place = True
        t.save()
        from tournaments.services import TournamentBracketService
        TournamentBracketService.generate_bracket(t.pk, actor=self.staff)
        for m in t.matches.filter(status='READY'):
            self.play(m)
        self.play(t.matches.get(bracket_type=TournamentMatch.BracketType.FINAL))
        with self.assertRaises(TournamentError):
            Life.confirm_results(t.pk, actor=self.staff)
        self.play(t.matches.get(bracket_type=TournamentMatch.BracketType.THIRD_PLACE))
        Life.confirm_results(t.pk, actor=self.staff)
