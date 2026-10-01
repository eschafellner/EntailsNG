"""Solo teams retain their identity and historical results across events."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventRegistration
from events.services import EventLifecycleService
from tournaments.exceptions import TournamentError
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentRegistration
from tournaments.services import TournamentRegistrationService, TournamentMatchService, get_or_create_solo_team
from tournaments.services.registration import archive_teams_for_event
from tournaments.services.swiss import SwissTournamentService, SwissStandingService


class SoloReactivationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.user = get_user_model().objects.create_user('returning-solo')
        cls.staff = get_user_model().objects.create_user('solo-orga', is_staff=True)
        cls.game = Game.objects.create(name='Solo reactivation game', team_size=1)
        cls.old_event = Event.objects.create(title='Previous solo LAN', status=Event.Status.FINISHED,
            start_date=now-timedelta(days=6), end_date=now-timedelta(days=4))
        cls.event = Event.objects.create(title='Next solo LAN', status=Event.Status.REGISTRATION_OPEN,
            is_active=True, start_date=now, end_date=now+timedelta(days=2))
        cls.team = Team.objects.create(name='My original solo team', captain=cls.user, game=cls.game,
            event=cls.old_event, is_solo=True, is_archived=True)
        TeamMember.objects.create(team=cls.team, user=cls.user, role=TeamMember.Role.CAPTAIN)
        EventRegistration.objects.create(user=cls.user, event=cls.event, is_checked_in=True)

    def tournament(self, event=None, **kwargs):
        now = timezone.now()
        return Tournament.objects.create(title='Solo registration', game=self.game, event=event or self.event,
            registration_start=now-timedelta(hours=1), registration_end=now+timedelta(hours=1),
            **({'status': Tournament.Status.REGISTRATION_OPEN} | kwargs))

    def register(self, tournament=None):
        return TournamentRegistrationService.register_team(
            (tournament or self.tournament()).pk, self.user, actor=self.user)

    def test_frontend_registration_reactivates_same_team_without_new_row(self):
        tournament = self.tournament()
        original = (self.team.pk, self.team.name, self.team.slug, self.team.invite_code)
        self.client.force_login(self.user)
        response = self.client.post(reverse('tournament_register', args=[tournament.slug]))
        self.assertEqual(response.status_code, 302)
        self.team.refresh_from_db()
        self.assertEqual((self.team.pk, self.team.name, self.team.slug, self.team.invite_code), original)
        self.assertEqual(self.team.event_id, self.event.pk)
        self.assertFalse(self.team.is_archived)
        self.assertEqual(tournament.registrations.get().team_id, self.team.pk)
        self.assertEqual(Team.objects.filter(captain=self.user, game=self.game).count(), 1)
        self.assertEqual(self.team.memberships.count(), 1)

    def test_completed_swiss_results_and_round_entries_survive_reactivation(self):
        Event.objects.filter(pk=self.old_event.pk).update(status=Event.Status.REGISTRATION_OPEN,
            end_date=timezone.now()+timedelta(days=1))
        Team.objects.filter(pk=self.team.pk).update(is_archived=False)
        opponent_user = get_user_model().objects.create_user('solo-old-opponent')
        opponent = Team.objects.create(name='Solo old opponent', captain=opponent_user, game=self.game,
            event=self.old_event, is_solo=True)
        TeamMember.objects.create(team=opponent, user=opponent_user, role=TeamMember.Role.CAPTAIN)
        old_tournament = self.tournament(event=self.old_event, mode=Tournament.Mode.SWISS, swiss_rounds=1)
        old_registration = TournamentRegistration.objects.create(tournament=old_tournament, team=self.team, seed=1)
        TournamentRegistration.objects.create(tournament=old_tournament, team=opponent, seed=2)
        preview = SwissTournamentService.preview(old_tournament.pk, actor=self.staff)
        record = SwissTournamentService.publish(old_tournament.pk, actor=self.staff, token=preview['token'])
        match = record.matches.get()
        TournamentMatchService.update_match_score(match.pk, 2, 0, actor=self.staff)
        EventLifecycleService.finish_event(self.old_event.pk)
        before_registration = TournamentRegistration.objects.filter(pk=old_registration.pk).values().get()
        before_match = record.matches.values().get()
        before_entries = list(record.entries.order_by('pk').values())
        before_standings = [(r['team'].pk, r['points'], r['rank']) for r in SwissStandingService.calculate(old_tournament)]
        new_registration, created = self.register()
        self.assertTrue(created)
        self.assertEqual(new_registration.team_id, self.team.pk)
        self.assertNotEqual(new_registration.pk, old_registration.pk)
        self.assertEqual(TournamentRegistration.objects.filter(pk=old_registration.pk).values().get(), before_registration)
        self.assertEqual(record.matches.values().get(), before_match)
        self.assertEqual(list(record.entries.order_by('pk').values()), before_entries)
        self.assertEqual([(r['team'].pk, r['points'], r['rank']) for r in SwissStandingService.calculate(old_tournament)], before_standings)
        old_tournament.refresh_from_db()
        self.assertEqual(old_tournament.event_id, self.old_event.pk)
        self.assertEqual(old_tournament.status, Tournament.Status.FINISHED)

    def test_previous_forfeit_is_not_carried_to_new_registration(self):
        old = TournamentRegistration.objects.create(tournament=self.tournament(event=self.old_event,
            status=Tournament.Status.FINISHED), team=self.team, is_forfeited=True, seed=7, score=42)
        new, _ = self.register()
        old.refresh_from_db()
        self.assertTrue(old.is_forfeited)
        self.assertEqual((old.seed, old.score), (7, 42))
        self.assertEqual(new.team_id, old.team_id)
        self.assertFalse(new.is_forfeited)
        self.assertIsNone(new.seed)
        self.assertEqual(new.score, 0)

    def test_repeated_and_multiple_tournament_registrations_use_one_team(self):
        first = self.tournament()
        self.register(first)
        with self.assertRaises(TournamentError):
            self.register(first)
        second, _ = self.register()
        self.assertEqual(second.team_id, self.team.pk)
        self.assertEqual(Team.objects.filter(captain=self.user, game=self.game).count(), 1)
        self.assertEqual(self.team.tournament_registrations.count(), 2)

    def test_archived_team_without_membership_restores_accepted_captain(self):
        self.team.memberships.all().delete()
        registration, _ = self.register()
        member = registration.team.memberships.get()
        self.assertEqual(member.user_id, self.user.pk)
        self.assertEqual(member.status, TeamMember.Status.ACCEPTED)
        self.assertEqual(member.role, TeamMember.Role.CAPTAIN)

    def test_unassigned_active_team_is_bound_to_destination(self):
        Team.objects.filter(pk=self.team.pk).update(event=None, is_archived=False)
        registration, _ = self.register()
        self.assertEqual(registration.team_id, self.team.pk)
        self.assertEqual(registration.team.event_id, self.event.pk)

    def test_active_team_of_another_event_requires_manual_resolution(self):
        Team.objects.filter(pk=self.team.pk).update(is_archived=False)
        with self.assertRaises(TournamentError):
            self.register()
        self.team.refresh_from_db()
        self.assertEqual(self.team.event_id, self.old_event.pk)
        self.assertEqual(Team.objects.filter(captain=self.user).count(), 1)

    def test_archive_for_another_game_is_left_untouched(self):
        other_game = Game.objects.create(name='Other archived solo game', team_size=1)
        Team.objects.filter(pk=self.team.pk).update(game=other_game)
        registration, _ = self.register()
        self.assertNotEqual(registration.team_id, self.team.pk)
        self.assertEqual(registration.team.game_id, self.game.pk)
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)
        self.assertEqual(self.team.game_id, other_game.pk)

    def test_duplicate_active_teams_require_resolution_instead_of_arbitrary_selection(self):
        Team.objects.filter(pk=self.team.pk).update(event=self.event, is_archived=False)
        Team.objects.create(name='Duplicate active solo', captain=self.user, game=self.game,
            event=self.event, is_solo=True)
        tournament = self.tournament()
        with self.assertRaises(TournamentError):
            self.register(tournament)
        self.assertFalse(tournament.registrations.exists())

    def test_pending_captain_membership_is_restored(self):
        self.team.memberships.update(status=TeamMember.Status.PENDING, role=TeamMember.Role.MEMBER)
        self.register()
        member = self.team.memberships.get()
        self.assertEqual((member.status, member.role), (TeamMember.Status.ACCEPTED, TeamMember.Role.CAPTAIN))

    def test_current_event_archive_has_priority_over_other_archives(self):
        current = Team.objects.create(name='Archived current solo', captain=self.user, game=self.game,
            event=self.event, is_solo=True, is_archived=True)
        registration, _ = self.register()
        self.assertEqual(registration.team_id, current.pk)
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)
        self.assertEqual(self.team.event_id, self.old_event.pk)

    def test_newest_archive_has_priority_and_other_histories_remain_separate(self):
        newest = Team.objects.create(name='Newer archived solo', captain=self.user, game=self.game,
            event=self.old_event, is_solo=True, is_archived=True)
        registration, _ = self.register()
        self.assertEqual(registration.team_id, newest.pk)
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)

    def test_other_players_archives_and_archived_regular_teams_are_not_reactivated(self):
        Team.objects.filter(pk=self.team.pk).update(is_solo=False)
        other = get_user_model().objects.create_user('other-solo-owner')
        other_team = Team.objects.create(name='Other solo archive', captain=other, game=self.game,
            event=self.old_event, is_solo=True, is_archived=True)
        registration, _ = self.register()
        self.assertNotIn(registration.team_id, (self.team.pk, other_team.pk))
        self.assertTrue(registration.team.is_solo)

    def test_extra_accepted_member_blocks_reactivation_without_altering_roster(self):
        other = get_user_model().objects.create_user('unexpected-solo-member')
        TeamMember.objects.create(team=self.team, user=other)
        with self.assertRaises(TournamentError):
            self.register()
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)
        self.assertEqual(self.team.memberships.count(), 2)
        self.assertEqual(Team.objects.filter(captain=self.user).count(), 1)

    def test_another_active_team_membership_blocks_duplicate_solo_creation(self):
        other = get_user_model().objects.create_user('current-solo-captain')
        current = Team.objects.create(name='Current other team', captain=other, game=self.game, event=self.event)
        TeamMember.objects.create(team=current, user=self.user)
        with self.assertRaises(TournamentError):
            self.register()
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)
        self.assertEqual(Team.objects.filter(captain=self.user).count(), 1)

    def test_running_or_generated_tournament_blocks_reactivation(self):
        for status, generated in ((Tournament.Status.IN_PROGRESS, False), (Tournament.Status.REGISTRATION_OPEN, True)):
            with self.subTest(status=status, generated=generated):
                old = self.tournament(event=self.old_event, status=status, is_generated=generated)
                registration = TournamentRegistration.objects.create(tournament=old, team=self.team)
                with self.assertRaises(TournamentError):
                    self.register()
                self.team.refresh_from_db()
                self.assertTrue(self.team.is_archived)
                self.assertEqual(self.team.event_id, self.old_event.pk)
                registration.delete()

    def test_unstarted_old_registration_must_be_resolved_before_event_change(self):
        old = self.tournament(event=self.old_event)
        TournamentRegistration.objects.create(tournament=old, team=self.team)
        with self.assertRaises(TournamentError):
            self.register()
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)

    def test_reactivation_and_membership_restore_roll_back_if_target_is_full(self):
        self.team.memberships.all().delete()
        tournament = self.tournament(max_teams=1)
        other = get_user_model().objects.create_user('full-solo-captain')
        team = Team.objects.create(name='Full solo entrant', captain=other, game=self.game, event=self.event)
        TournamentRegistration.objects.create(tournament=tournament, team=team)
        with self.assertRaises(TournamentError):
            self.register(tournament)
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)
        self.assertEqual(self.team.event_id, self.old_event.pk)
        self.assertFalse(self.team.memberships.exists())

    def test_new_account_with_old_username_cannot_access_archived_team(self):
        name = self.user.username
        get_user_model().objects.filter(pk=self.user.pk).update(username='deleted-solo-rest',
            email='deleted-solo-rest@example.invalid', deleted_at=timezone.now(), is_active=False)
        new_user = get_user_model().objects.create_user(name)
        registration, _ = TournamentRegistrationService.register_team(
            self.tournament().pk, new_user, actor=self.staff)
        self.assertNotEqual(registration.team_id, self.team.pk)
        self.assertEqual(registration.team.captain_id, new_user.pk)
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)

    def test_direct_helper_rejects_deleted_account_and_closed_destination(self):
        with self.assertRaises(TournamentError):
            get_or_create_solo_team(self.user, self.game, self.old_event)
        get_user_model().objects.filter(pk=self.user.pk).update(deleted_at=timezone.now(), is_active=False)
        with self.assertRaises(TournamentError):
            get_or_create_solo_team(self.user, self.game, self.event)
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)

    def test_finishing_old_event_again_does_not_archive_reactivated_team(self):
        old = self.tournament(event=self.old_event, status=Tournament.Status.FINISHED)
        TournamentRegistration.objects.create(tournament=old, team=self.team)
        self.register()
        _, count = EventLifecycleService.finish_event(self.old_event.pk)
        self.assertEqual(count, 0)
        self.team.refresh_from_db()
        self.assertFalse(self.team.is_archived)
        self.assertEqual(self.team.event_id, self.event.pk)

    def test_archival_still_includes_legacy_teams_without_event_binding(self):
        Team.objects.filter(pk=self.team.pk).update(event=None, is_archived=False)
        TournamentRegistration.objects.create(tournament=self.tournament(event=self.old_event,
            status=Tournament.Status.FINISHED), team=self.team)
        self.assertEqual(archive_teams_for_event(self.old_event), 1)
        self.team.refresh_from_db()
        self.assertTrue(self.team.is_archived)
        self.assertEqual(self.team.event_id, self.old_event.pk)
