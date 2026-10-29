from importlib import import_module
from unittest.mock import patch

from django.apps import apps
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from tournaments.exceptions import TournamentError
from tournaments.models import Team, TeamMember, Tournament, TournamentMatch
from tournaments.services import GroupStageStandingService, forfeit_team_in_active_tournaments
from tournaments import test_audit as audit_tests


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class TournamentReviewTests(TestCase):
    setUpTestData = classmethod(audit_tests.TournamentAuditTests.setUpTestData.__func__)
    tournament = audit_tests.TournamentAuditTests.tournament
    start = audit_tests.TournamentAuditTests.start

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_invite_code_only_in_member_responses(self):
        team = self.teams[0]
        url = reverse('team_detail', args=[team.slug])
        self.assertNotContains(self.client.get(url), team.invite_code)
        self.client.force_login(self.teams[1].captain)
        self.assertNotContains(self.client.get(url), team.invite_code)
        self.client.force_login(team.captain)
        self.assertContains(self.client.get(url), team.invite_code)

    def test_exposed_codes_rotated_by_migration(self):
        module = import_module('tournaments.migrations.0017_rotate_exposed_invite_codes')
        before = dict(Team.objects.values_list('pk', 'invite_code'))
        with connection.schema_editor() as editor:
            module.rotate_codes(apps, editor)
        codes = list(Team.objects.values_list('invite_code', flat=True))
        self.assertEqual(len(codes), len(set(codes)))
        for team in Team.objects.all():
            self.assertNotEqual(team.invite_code, before[team.pk])
            self.assertEqual(len(team.invite_code), 32)

    def test_code_attempts_limited_before_roster_lookup(self):
        self.client.force_login(self.teams[1].captain)
        with patch('tournaments.views.Team.objects.select_for_update', wraps=Team.objects.select_for_update) as lookup:
            for _ in range(12):
                self.client.post(reverse('team_join_by_code'), {'invite_code': 'UNKNOWN'})
        self.assertEqual(lookup.call_count, 10)

    def test_admin_restore_uses_validated_wizard(self):
        team = self.teams[0]
        Team.objects.filter(pk=team.pk).update(is_archived=True)
        other = Team.objects.create(name='Conflicting team', game=team.game, captain=team.captain, event=self.event)
        TeamMember.objects.create(team=other, user=team.captain, status=TeamMember.Status.ACCEPTED)
        self.client.force_login(self.staff)
        response = self.client.post(reverse('admin:tournaments_team_changelist'), {
            'action': 'action_unarchive_teams', '_selected_action': [team.pk],
        })
        # A staff account without model permissions cannot invoke the admin action.
        self.assertEqual(response.status_code, 403)
        self.staff.is_superuser = True
        self.staff.save(update_fields=['is_superuser'])
        response = self.client.post(reverse('admin:tournaments_team_changelist'), {
            'action': 'action_unarchive_teams', '_selected_action': [team.pk],
        })
        self.assertRedirects(response, reverse('team_reactivate', args=[team.slug]))
        self.client.post(response.url, {'game_id': team.game_id})
        team.refresh_from_db()
        self.assertTrue(team.is_archived)
        self.assertEqual(team.event_id, self.event.pk)

    def test_pre_release_forfeit_recalculates_qualification(self):
        tournament = self.start(Tournament.Mode.GROUP_STAGE)
        for match in tournament.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP):
            TournamentMatch.objects.filter(pk=match.pk).update(status=TournamentMatch.Status.COMPLETED,
                score_team1=1, score_team2=0, winner=match.team1, loser=match.team2)
        GroupStageStandingService.check_and_advance_group_stage(tournament)
        final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.FINAL)
        withdrawn = final.team1
        self.assertEqual(final.status, TournamentMatch.Status.READY)
        self.assertIsNone(tournament.playoffs_released_at)
        forfeit_team_in_active_tournaments(withdrawn)
        self.assertTrue(tournament.registrations.get(team=withdrawn).is_forfeited)
        final.refresh_from_db()
        self.assertNotIn(withdrawn.pk, (final.team1_id, final.team2_id))
        self.assertEqual(final.status, TournamentMatch.Status.READY)
        self.assertIsNone(final.winner_id)
        self.assertTrue(tournament.result_logs.exists())

    def test_admin_reports_expected_forfeit_errors(self):
        self.staff.is_superuser = True
        self.staff.save(update_fields=['is_superuser'])
        self.start()
        self.client.force_login(self.staff)
        with patch('tournaments.services.forfeit_team_in_active_tournaments', side_effect=TournamentError('Gesperrt')):
            response = self.client.post(reverse('admin:tournaments_team_changelist'), {
                'action': 'action_forfeit_and_disqualify', '_selected_action': [self.teams[0].pk],
            }, follow=True)
        self.assertContains(response, 'Gesperrt')

    def test_invalid_identifiers_are_controlled_and_leave_archive_intact(self):
        team = self.teams[0]
        Team.objects.filter(pk=team.pk).update(is_archived=True)
        self.client.force_login(team.captain)
        for value in ('²', '9' * 5000, str(2**64)):
            with self.subTest(value=value[:20]):
                self.assertEqual(self.client.get(reverse('team_list'), {'game': value}).status_code, 400)
                response = self.client.post(reverse('team_reactivate', args=[team.slug]), {'keep_members': [value]})
                self.assertEqual(response.status_code, 302)
                team.refresh_from_db()
                self.assertTrue(team.is_archived)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class TournamentDetailTranslationPlaceholderTests(TestCase):
    """F-009: Die Mitglieder-Notiz übergibt dem Übersetzungstext nur Strings, kein Team-Objekt."""
    setUpTestData = classmethod(audit_tests.TournamentAuditTests.setUpTestData.__func__)

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_member_notice_does_not_expose_team_object(self):
        from datetime import timedelta
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from configuration.models import SystemTranslation
        from events.models import EventRegistration

        captain, member = self.teams[0].captain, get_user_model().objects.create_user('f009-member')
        team = Team.objects.create(name='F009 Team', game=self.team_game, captain=captain, event=self.event)
        TeamMember.objects.create(team=team, user=captain, role=TeamMember.Role.CAPTAIN)
        TeamMember.objects.create(team=team, user=member, status=TeamMember.Status.ACCEPTED)
        EventRegistration.objects.create(user=member, event=self.event, is_checked_in=True)
        now = timezone.now()
        tournament = Tournament.objects.create(title='F009 Turnier', event=self.event, game=self.team_game,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=now - timedelta(hours=1), registration_end=now + timedelta(hours=1))
        SystemTranslation.objects.update_or_create(key='tournament_detail_member_team_notice',
            defaults={'text': 'Team {team_name} / {team_name.__class__}'})
        cache.clear()

        self.client.force_login(member)
        response = self.client.get(reverse('tournament_detail', args=[tournament.slug]))

        self.assertContains(response, 'Team {team_name} / {team_name.__class__}')
        self.assertNotContains(response, 'tournaments.models')
