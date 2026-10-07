"""Result correction races on real PostgreSQL row locks."""
from django.test import TransactionTestCase, skipUnlessDBFeature
from tournaments import test_audit as audit, test_swiss_concurrency as swiss
from tournaments.models import Tournament, TournamentMatch
from tournaments.services import TournamentMatchService as Scores, TournamentLifecycleService as Life
from tournaments.services.results import tournament_version
from tournaments.exceptions import TournamentError


@skipUnlessDBFeature('has_select_for_update')
class ResultConcurrencyTests(TransactionTestCase):
    separate_connection = staticmethod(swiss.SwissConcurrencyTests.separate_connection)
    compete = swiss.SwissConcurrencyTests.compete
    tournament = audit.TournamentAuditTests.tournament
    start = audit.TournamentAuditTests.start

    def setUp(self):
        audit.TournamentAuditTests.setUpTestData.__func__(type(self))

    def test_start_before_winner_change_blocks_change(self):
        t = self.start()
        matches = list(t.matches.filter(status='READY'))
        for m in matches:
            Scores.update_match_score(m.pk, 2, 0, actor=self.staff)
        m = matches[0]
        self.compete(lambda: Life.start_match(m.next_match_winner_id, actor=self.staff),
            lambda: Scores.update_match_score(m.pk, 0, 2, actor=self.staff, decision_reason='Vertauscht'), TournamentError)
        m.refresh_from_db()
        self.assertEqual(m.winner_id, m.team1_id)
        self.assertEqual(t.result_logs.filter(action='RESULT').count(), 2)

    def test_correction_before_confirmation_invalidates_confirmation(self):
        t = self.start(count=2)
        m = t.matches.get()
        Scores.update_match_score(m.pk, 2, 0, actor=self.staff)
        version = tournament_version(t)
        self.compete(lambda: Scores.update_match_score(m.pk, 0, 2, actor=self.staff, decision_reason='Vertauscht'),
            lambda: Life.confirm_results(t.pk, actor=self.staff, expected_state=version), TournamentError)
        t.refresh_from_db()
        self.assertEqual(t.status, Tournament.Status.RESULTS_REVIEW)
        self.assertFalse(t.result_logs.filter(action='CONFIRM').exists())

    def test_confirmation_before_correction_blocks_correction(self):
        t = self.start(count=2)
        m = t.matches.get()
        Scores.update_match_score(m.pk, 2, 0, actor=self.staff)
        self.compete(lambda: Life.confirm_results(t.pk, actor=self.staff),
            lambda: Scores.update_match_score(m.pk, 0, 2, actor=self.staff, decision_reason='Vertauscht'), TournamentError)
        m.refresh_from_db()
        self.assertEqual(m.winner_id, m.team1_id)
        self.assertEqual(t.result_logs.filter(action='CONFIRM').count(), 1)

    def test_release_before_group_winner_change_blocks_change(self):
        t = self.start(Tournament.Mode.GROUP_STAGE, 4)
        for m in t.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP):
            Scores.update_match_score(m.pk, 2, 0, actor=self.staff)
        m = t.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP).first()
        self.compete(lambda: Life.release_playoffs(t.pk, actor=self.staff),
            lambda: Scores.update_match_score(m.pk, 0, 2, actor=self.staff, decision_reason='Vertauscht'), TournamentError)
        m.refresh_from_db()
        self.assertEqual(m.winner_id, m.team1_id)

    def test_group_correction_before_release_invalidates_preview(self):
        t = self.start(Tournament.Mode.GROUP_STAGE, 4)
        for m in t.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP):
            Scores.update_match_score(m.pk, 2, 0, actor=self.staff)
        m = t.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP).first()
        version = tournament_version(t)
        self.compete(lambda: Scores.update_match_score(m.pk, 0, 2, actor=self.staff, decision_reason='Vertauscht'),
            lambda: Life.release_playoffs(t.pk, actor=self.staff, expected_state=version), TournamentError)
        t.refresh_from_db()
        self.assertIsNone(t.playoffs_released_at)
        self.assertFalse(t.result_logs.filter(action='RELEASE').exists())
