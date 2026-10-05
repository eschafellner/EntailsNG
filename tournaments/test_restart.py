"""Independent editions, admin workflow, provenance and PostgreSQL publication races."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import Event as ThreadEvent
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from tournaments.exceptions import TournamentError
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentMatch, TournamentRegistration
from tournaments.services import (TournamentRestartService, TournamentBracketService,
    TournamentMatchService, FFAMatchService, SwissTournamentService, TournamentLifecycleService)


def fixture(target):
    now = timezone.now()
    target.staff = get_user_model().objects.create_superuser('restart-admin')
    target.event = Event.objects.create(title='Restart LAN', is_active=True,
        status=Event.Status.REGISTRATION_OPEN, start_date=now, end_date=now + timedelta(days=3))
    target.game = Game.objects.create(name='Restart Game', team_size=1)
    target.teams = []
    for seed in range(1, 5):
        captain = get_user_model().objects.create_user(f'restart-player-{seed}')
        team = Team.objects.create(name=f'Restart Team {seed}', game=target.game,
            event=target.event, captain=captain, is_solo=True)
        TeamMember.objects.create(team=team, user=captain, role=TeamMember.Role.CAPTAIN)
        target.teams.append(team)


class RestartHelpers:
    def source(self, mode=Tournament.Mode.SINGLE_ELIMINATION):
        now = timezone.now()
        source = Tournament.objects.create(title='Original', event=self.event, game=self.game,
            mode=mode, status=Tournament.Status.REGISTRATION_OPEN, max_teams=4, swiss_rounds=2,
            play_third_place=True, group_qualifiers_per_group=2,
            standings_tiebreak=Tournament.Tiebreak.HEAD_TO_HEAD,
            description='Regeln und Preise', tournament_admin=self.staff,
            registration_start=now - timedelta(hours=1), registration_end=now + timedelta(hours=1),
            tournament_start=now + timedelta(hours=2))
        for seed, team in enumerate(self.teams, 1):
            TournamentRegistration.objects.create(tournament=source, team=team, seed=seed)
        return source

    def options(self, source, **overrides):
        plan = TournamentRestartService.preview(source.pk, actor=self.staff)
        data = dict(actor=self.staff, preview_token=plan['token'], title='Neue Ausgabe',
            registration_start=source.registration_start, registration_end=source.registration_end,
            tournament_start=source.tournament_start, reason='Organisatorischer Neustart',
            registration_ids=[row['id'] for row in plan['registrations']])
        data.update(overrides)
        return data

    def copy(self, source, **overrides):
        return TournamentRestartService.create(source.pk, **self.options(source, **overrides))[0]

    def finish(self, source):
        TournamentBracketService.generate_bracket(source.pk, actor=self.staff)
        if source.mode == Tournament.Mode.FFA:
            match = source.matches.get()
            entries = [{'participant_id': p.pk, 'rank': i, 'score': 100-i,
                'is_disqualified': False, 'notes': ''} for i, p in enumerate(match.participants.all(), 1)]
            FFAMatchService.update_ffa_scores(match.pk, entries, actor=self.staff)
            return
        for _ in range(100):
            source.refresh_from_db()
            if source.status == Tournament.Status.FINISHED:
                return
            match = source.matches.filter(status=TournamentMatch.Status.READY, is_bye=False).first()
            if match:
                TournamentMatchService.update_match_score(match.pk, 2, 0, actor=self.staff)
            elif source.mode == Tournament.Mode.SWISS:
                token = SwissTournamentService.preview(source.pk, actor=self.staff)['token']
                SwissTournamentService.publish(source.pk, actor=self.staff, token=token)
            else:
                self.fail('Original tournament did not finish')
        self.fail('Original tournament did not finish')


@override_settings(SECURE_SSL_REDIRECT=False)
class TournamentRestartTests(RestartHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.staff)

    def test_finished_editions_of_all_six_modes_keep_history_and_copy_rules(self):
        fields = ('mode', 'description', 'game_id', 'event_id', 'max_teams', 'swiss_rounds',
            'swiss_allow_draws', 'play_third_place', 'group_qualifiers_per_group', 'standings_tiebreak', 'tournament_admin_id')
        for mode in Tournament.Mode.values:
            with self.subTest(mode=mode):
                source = self.source(mode)
                self.finish(source)
                source.refresh_from_db()
                before = list(source.matches.values())
                previous_rounds = source.swiss_round_records.count()
                edition = self.copy(source)
                source.refresh_from_db()
                self.assertEqual(source.status, Tournament.Status.FINISHED)
                self.assertEqual(list(source.matches.values()), before)
                self.assertEqual(source.swiss_round_records.count(), previous_rounds)
                self.assertEqual(edition.status, Tournament.Status.DRAFT)
                self.assertFalse(edition.is_generated)
                self.assertFalse(edition.matches.exists())
                self.assertFalse(edition.swiss_round_records.exists())
                self.assertIsNone(edition.swiss_pairing_seed)
                self.assertEqual(edition.registrations.count(), 4)
                for field in fields:
                    self.assertEqual(getattr(source, field), getattr(edition, field))
                TournamentLifecycleService.open_registration(edition.pk, actor=self.staff)
                self.finish(edition)
                edition.refresh_from_db()
                self.assertEqual(edition.status, Tournament.Status.FINISHED)
                self.assertEqual(list(source.matches.values()), before)

    def test_open_closed_draft_running_and_cancelled_originals_can_be_copied(self):
        for status in (Tournament.Status.DRAFT, Tournament.Status.REGISTRATION_OPEN,
                       Tournament.Status.REGISTRATION_CLOSED, Tournament.Status.IN_PROGRESS, Tournament.Status.CANCELLED):
            with self.subTest(status=status):
                source = self.source()
                source.status = status
                source.save()
                edition = self.copy(source)
                source.refresh_from_db()
                self.assertEqual(source.status, status)
                self.assertEqual(edition.restarted_from, source)

    def test_selected_teams_reset_stats_and_optionally_drop_seeds(self):
        source = self.source()
        registration = source.registrations.first()
        registration.is_forfeited, registration.score, registration.group_name = True, 123, 'Gruppe A'
        registration.save()
        edition = self.copy(source, registration_ids=[registration.pk], copy_seeds=False)
        copied = edition.registrations.get()
        self.assertEqual(copied.team_id, registration.team_id)
        self.assertEqual((copied.seed, copied.score, copied.group_name, copied.is_forfeited), (None, 0, '', False))
        self.assertTrue(edition.restart_team_snapshot[0]['previously_withdrawn'])
        registration.refresh_from_db()
        self.assertTrue(registration.is_forfeited)
        self.assertEqual(registration.score, 123)

    def test_empty_selection_creates_editable_template(self):
        source = self.source()
        edition = self.copy(source, registration_ids=[])
        self.assertFalse(edition.registrations.exists())
        edition.group_qualifiers_per_group = 1
        edition.standings_tiebreak = Tournament.Tiebreak.SHARED
        edition.save()
        source.refresh_from_db()
        self.assertEqual(source.group_qualifiers_per_group, 2)

    def test_cancellation_keeps_played_matches_and_is_optional(self):
        source = self.source()
        TournamentBracketService.generate_bracket(source.pk, actor=self.staff)
        match = source.matches.filter(status=TournamentMatch.Status.READY).first()
        TournamentMatchService.update_match_score(match.pk, 2, 0, actor=self.staff)
        before = list(source.matches.values())
        edition = self.copy(source, cancel_source=True)
        source.refresh_from_db()
        self.assertEqual(source.status, Tournament.Status.CANCELLED)
        self.assertEqual(list(source.matches.values()), before)
        self.assertTrue(edition.restart_cancelled_source)

    def test_repeated_submission_returns_one_edition_after_cancellation(self):
        source = self.source()
        data = self.options(source, cancel_source=True)
        first, created = TournamentRestartService.create(source.pk, **data)
        second, created_again = TournamentRestartService.create(source.pk, **data)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(source.restart_editions.count(), 1)

    def test_changes_after_preview_require_fresh_review(self):
        source = self.source()
        mutations = [lambda: Tournament.objects.filter(pk=source.pk).update(title='Changed'),
            lambda: source.registrations.filter(seed=1).update(is_forfeited=True),
            lambda: Team.objects.filter(pk=self.teams[0].pk).update(is_archived=True),
            lambda: source.registrations.filter(seed=2).delete()]
        for mutate in mutations:
            data = self.options(source)
            mutate()
            with self.assertRaises(TournamentError):
                TournamentRestartService.create(source.pk, **data)
        self.assertFalse(source.restart_editions.exists())

    def test_foreign_and_duplicate_registration_ids_are_rejected_atomically(self):
        source = self.source()
        foreign = self.source().registrations.first()
        registration = source.registrations.first()
        for ids in ([foreign.pk], [registration.pk, registration.pk]):
            with self.assertRaises(TournamentError):
                self.copy(source, registration_ids=ids, cancel_source=True)
        source.refresh_from_db()
        self.assertEqual(source.status, Tournament.Status.REGISTRATION_OPEN)
        self.assertFalse(source.restart_editions.exists())

    def test_failure_while_copying_rolls_back_entire_edition(self):
        source = self.source()
        original_create = TournamentRegistration.objects.create
        calls = []
        def fail_second(**kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise RuntimeError('Test write failure')
            return original_create(**kwargs)
        with patch.object(TournamentRegistration.objects, 'create', side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                self.copy(source, cancel_source=True)
        self.assertFalse(source.restart_editions.exists())
        self.assertEqual(TournamentRegistration.objects.count(), 4)
        source.refresh_from_db()
        self.assertEqual(source.status, Tournament.Status.REGISTRATION_OPEN)

    def test_terminal_status_cannot_be_changed_by_cancellation(self):
        source = self.source()
        for status in (Tournament.Status.FINISHED, Tournament.Status.CANCELLED):
            source.status = status
            source.save()
            with self.assertRaises(TournamentError):
                self.copy(source, cancel_source=True)
            source.refresh_from_db()
            self.assertEqual(source.status, status)

    def test_permission_requires_staff_and_all_three_model_permissions(self):
        source = self.source()
        actor = get_user_model().objects.create_user('restart-limited', is_staff=True)
        for codename in ('add_tournament', 'change_tournament', 'add_tournamentregistration'):
            with self.assertRaises(PermissionDenied):
                TournamentRestartService.preview(source.pk, actor=actor)
            actor.user_permissions.add(Permission.objects.get(content_type__app_label='tournaments', codename=codename))
            actor = get_user_model().objects.get(pk=actor.pk)
        self.assertTrue(TournamentRestartService.preview(source.pk, actor=actor)['token'])
        actor.is_staff = False
        actor.save()
        with self.assertRaises(PermissionDenied):
            TournamentRestartService.preview(source.pk, actor=actor)

    def test_tokens_are_bound_to_original_actor_and_expiry(self):
        source = self.source()
        other = self.source()
        data = self.options(source)
        with self.assertRaises(TournamentError):
            TournamentRestartService.create(other.pk, **data)
        actor = get_user_model().objects.create_superuser('restart-other-admin')
        with self.assertRaises(TournamentError):
            TournamentRestartService.create(source.pk, **{**data, 'actor': actor})
        with self.assertRaises(TournamentError):
            TournamentRestartService.create(source.pk, **{**data, 'preview_token': data['preview_token']+'bad'})
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp()+1900):
            with self.assertRaises(TournamentError):
                TournamentRestartService.create(source.pk, **data)

    def test_invalid_dates_reason_and_boolean_options_leave_original_untouched(self):
        source = self.source()
        for overrides in ({'reason': ''}, {'title': ' '}, {'copy_seeds': 'yes'},
            {'registration_end': source.registration_start-timedelta(hours=1)}, {'reason': 'x'*1001}):
            with self.assertRaises((TournamentError, ValidationError)):
                self.copy(source, cancel_source=True, **overrides)
        self.assertFalse(source.restart_editions.exists())
        source.refresh_from_db()
        self.assertEqual(source.status, Tournament.Status.REGISTRATION_OPEN)

    def test_archived_teams_can_be_prepared_but_do_not_start_or_reactivate(self):
        source = self.source()
        self.teams[0].is_archived = True
        self.teams[0].save()
        edition = self.copy(source)
        TournamentLifecycleService.open_registration(edition.pk, actor=self.staff)
        with self.assertRaises(TournamentError):
            TournamentBracketService.generate_bracket(edition.pk, actor=self.staff)
        self.teams[0].refresh_from_db()
        self.assertTrue(self.teams[0].is_archived)
        self.assertFalse(edition.matches.exists())

    def test_ended_event_allows_draft_copy_but_blocks_publication(self):
        source = self.source()
        self.event.status = Event.Status.FINISHED
        self.event.save()
        self.assertTrue(TournamentRestartService.preview(source.pk, actor=self.staff)['event_closed'])
        edition = self.copy(source)
        with self.assertRaises(TournamentError):
            TournamentLifecycleService.open_registration(edition.pk, actor=self.staff)
        with self.assertRaises(TournamentError):
            TournamentBracketService.generate_bracket(edition.pk, actor=self.staff)

    def test_lineage_does_not_disclose_drafts_to_guests(self):
        source = self.source()
        edition = self.copy(source)
        url = reverse('tournament_detail', args=[source.slug])
        self.assertContains(self.client.get(url), edition.title)
        self.client.logout()
        self.assertNotContains(self.client.get(url), edition.title)
        self.assertEqual(self.client.get(reverse('tournament_detail', args=[edition.slug])).status_code, 404)
        TournamentLifecycleService.open_registration(edition.pk, actor=self.staff)
        self.assertContains(self.client.get(url), edition.title)
        self.assertNotContains(self.client.get(reverse('tournament_detail', args=[edition.slug])), 'Originalturnier:')
        self.assertEqual(edition.restarted_from_id, source.pk)
        source.status = Tournament.Status.DRAFT
        source.save()
        self.assertNotContains(self.client.get(reverse('tournament_detail', args=[edition.slug])), source.title)

    def test_provenance_survives_source_deletion_and_duplicate_titles_have_unique_urls(self):
        source = self.source()
        first, second = self.copy(source, title='x'*150), self.copy(source, title='x'*150)
        self.assertNotEqual(first.slug, second.slug)
        self.assertLessEqual(len(first.slug), 150)
        self.assertEqual(first.restarted_by, self.staff)
        self.assertEqual(first.restart_reason, 'Organisatorischer Neustart')
        source.delete()
        first.refresh_from_db()
        self.assertIsNone(first.restarted_from)
        self.assertEqual(first.restart_source_title, 'Original')

    def post_data(self, response, **changes):
        form = response.context['form']
        data = {name: form[name].value() for name in form.fields}
        data.update(registration_start='2026-10-02T12:00', registration_end='2026-10-02T18:00',
            tournament_start='2026-10-02T19:00', reason='Backend-Neustart')
        data.pop('cancel_source', None)
        data.update(changes)
        return data

    def test_admin_preview_post_and_duplicate_post_work_end_to_end(self):
        source = self.source()
        change_url = reverse('admin:tournaments_tournament_change', args=[source.pk])
        url = reverse('admin:tournaments_tournament_restart', args=[source.pk])
        self.assertContains(self.client.get(change_url), 'Neustart vorbereiten')
        response = self.client.get(url)
        self.assertContains(response, self.teams[0].name)
        self.assertFalse(source.restart_editions.exists())
        data = self.post_data(response, registration_ids=[str(source.registrations.first().pk)], cancel_source='on')
        result = self.client.post(url, data)
        edition = source.restart_editions.get()
        self.assertRedirects(result, reverse('admin:tournaments_tournament_change', args=[edition.pk]))
        self.assertEqual(edition.registrations.count(), 1)
        self.assertEqual(edition.restart_reason, 'Backend-Neustart')
        self.assertEqual(edition.registration_end.hour, 16)  # CEST input, UTC storage.
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(source.restart_editions.count(), 1)
        self.assertContains(self.client.get(change_url), edition.title)

    def test_admin_csrf_permissions_method_and_invalid_form(self):
        source = self.source()
        url = reverse('admin:tournaments_tournament_restart', args=[source.pk])
        response = self.client.get(url)
        data = self.post_data(response)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.staff)
        self.assertEqual(csrf.post(url, data).status_code, 403)
        self.assertEqual(self.client.put(url).status_code, 405)
        self.assertContains(self.client.post(url, {**data, 'reason': ''}), 'errorlist')
        self.assertFalse(source.restart_editions.exists())
        limited = get_user_model().objects.create_user('restart-backend-limited', is_staff=True)
        self.client.force_login(limited)
        self.assertEqual(self.client.get(url).status_code, 403)
        model_admin = admin.site._registry[Tournament]
        readonly = model_admin.get_readonly_fields(None, source)
        for field in ('restarted_from', 'restarted_by', 'restart_reason', 'restart_team_snapshot'):
            self.assertIn(field, readonly)


@skipUnlessDBFeature('has_select_for_update')
class TournamentRestartConcurrencyTests(RestartHelpers, TransactionTestCase):
    def setUp(self):
        cache.clear()
        fixture(self)

    @staticmethod
    def separate_connection(action):
        close_old_connections()
        try:
            return action()
        finally:
            connections.close_all()

    def compete(self, first_action, second_action):
        paused, proceed, entered = ThreadEvent(), ThreadEvent(), ThreadEvent()
        def first():
            with transaction.atomic():
                result = first_action()
                paused.set()
                if not proceed.wait(10):
                    raise RuntimeError('Restart concurrency test timed out')
                return result
        def second():
            entered.set()
            return second_action()
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(self.separate_connection, first)
            self.assertTrue(paused.wait(10))
            two = pool.submit(self.separate_connection, second)
            self.assertTrue(entered.wait(10))
            try:
                with self.assertRaises(TimeoutError):
                    two.result(timeout=0.2)
            finally:
                proceed.set()
            first_result = one.result(timeout=10)
            return first_result, two.result(timeout=10)

    def test_concurrent_submissions_create_only_one_edition(self):
        source = self.source()
        data = self.options(source, cancel_source=True)
        first, second = self.compete(lambda: TournamentRestartService.create(source.pk, **data),
            lambda: TournamentRestartService.create(source.pk, **data))
        self.assertEqual(first[0].pk, second[0].pk)
        self.assertEqual((first[1], second[1]), (True, False))
        self.assertEqual(source.restart_editions.count(), 1)

    def test_registration_change_invalidates_waiting_copy(self):
        source = self.source()
        data = self.options(source)
        def withdraw():
            from tournaments.services.locking import lock_tournament
            locked = lock_tournament(source.pk)
            locked.registrations.filter(seed=1).update(is_forfeited=True)
        with self.assertRaises(TournamentError):
            self.compete(withdraw, lambda: TournamentRestartService.create(source.pk, **data))
        self.assertFalse(source.restart_editions.exists())
