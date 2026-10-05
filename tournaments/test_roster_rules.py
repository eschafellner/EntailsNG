"""Per-tournament roster policy, start guards, UI and lifecycle regressions."""
from datetime import timedelta

from django.contrib import admin
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventRegistration
from users.models import User
from tournaments.admin import TournamentAdmin
from tournaments.exceptions import TournamentError, TournamentNotCheckedInError, TournamentRegistrationError
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentRegistration
from tournaments.services import TournamentBracketService, TournamentRegistrationService, TournamentRestartService
from tournaments.services.registration import validate_start_roster
from tournaments.services.swiss import SwissTournamentService


class RosterRuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.staff = User.objects.create_superuser('roster-orga')
        cls.event = Event.objects.create(title='Roster LAN', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=now, end_date=now + timedelta(days=3))
        cls.game = Game.objects.create(name='Roster Game', team_size=5)
        cls.teams = []
        for number in range(4):
            captain = User.objects.create_user(f'roster-captain-{number}')
            team = Team.objects.create(name=f'Roster Team {number}', captain=captain,
                game=cls.game, event=cls.event)
            TeamMember.objects.create(team=team, user=captain,
                role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
            EventRegistration.objects.create(user=captain, event=cls.event, is_checked_in=True)
            cls.teams.append(team)

    def setUp(self):
        cache.clear()
        now = timezone.now()
        self.tournament = Tournament.objects.create(title='Roster Cup', event=self.event,
            game=self.game, status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=now - timedelta(hours=1), registration_end=now + timedelta(hours=1))

    def set_rule(self, rule):
        self.tournament.roster_rule = rule
        self.tournament.save()

    def register(self, team=None, actor=None):
        team = team or self.teams[0]
        return TournamentRegistrationService.register_team(self.tournament.pk,
            user=team.captain, team_id=team.pk, actor=actor)

    def add_members(self, team, count, *, pending=False, checkin=True):
        offset = team.memberships.count()
        for number in range(offset, offset + count):
            user = User.objects.create_user(f'extra-{team.pk}-{number}')
            TeamMember.objects.create(team=team, user=user, status=(
                TeamMember.Status.PENDING if pending else TeamMember.Status.ACCEPTED))
            if checkin:
                EventRegistration.objects.create(user=user, event=self.event, is_checked_in=True)

    def raw_registrations(self):
        for team in self.teams:
            TournamentRegistration.objects.create(tournament=self.tournament, team=team)

    def test_default_is_strict_and_size_matrix_matches_registration_and_start(self):
        self.assertEqual(self.tournament.roster_rule, Tournament.RosterRule.STRICT)
        for rule in Tournament.RosterRule.values:
            self.set_rule(rule)
            for count in range(7):
                with self.subTest(rule=rule, count=count):
                    valid = 1 <= count <= 5
                    self.assertEqual(self.tournament.roster_size_allowed(count),
                        valid and (rule != Tournament.RosterRule.STRICT or count == 5))
                    self.assertEqual(self.tournament.roster_size_allowed(count, for_start=True),
                        valid and (rule == Tournament.RosterRule.ALLOW_INCOMPLETE or count == 5))
        self.game.team_size = 1
        for rule in Tournament.RosterRule.values:
            self.tournament.roster_rule = rule
            for count in (0, 1, 2):
                self.assertEqual(self.tournament.roster_size_allowed(count), count == 1)
                self.assertEqual(self.tournament.roster_size_allowed(count, for_start=True), count == 1)

    def test_invalid_rule_rejected_by_model(self):
        self.tournament.roster_rule = 'INVALID'
        with self.assertRaises(ValidationError):
            self.tournament.save()

    def test_strict_rejects_partial_team_even_for_organizer(self):
        for actor in (None, self.staff):
            with self.subTest(actor=actor), self.assertRaises(TournamentRegistrationError):
                self.register(actor=actor)
        self.assertFalse(self.tournament.can_register(self.teams[0].captain, self.teams[0])[0])
        self.assertFalse(self.tournament.registrations.exists())

    def test_loose_rules_accept_partial_team_and_count_regular_capacity(self):
        self.tournament.max_teams = 1
        for rule in (Tournament.RosterRule.BY_START, Tournament.RosterRule.ALLOW_INCOMPLETE):
            with self.subTest(rule=rule):
                self.set_rule(rule)
                registration, created = self.register()
                self.assertTrue(created)
                self.assertEqual(registration.team_id, self.teams[0].pk)
                with self.assertRaises(TournamentRegistrationError):
                    self.register(self.teams[1])
                self.tournament.registrations.all().delete()

    def test_full_teams_register_under_every_rule(self):
        self.add_members(self.teams[0], 4)
        for rule in Tournament.RosterRule.values:
            with self.subTest(rule=rule):
                self.set_rule(rule)
                self.assertTrue(self.register()[1])
                self.tournament.registrations.all().delete()

    def test_empty_and_oversized_rosters_rejected_under_every_rule(self):
        team = self.teams[0]
        for rule in Tournament.RosterRule.values:
            with self.subTest(rule=rule):
                self.set_rule(rule)
                team.memberships.update(status=TeamMember.Status.PENDING)
                with self.assertRaises(TournamentRegistrationError):
                    self.register(actor=self.staff)
                self.assertFalse(self.tournament.can_register(team.captain, team)[0])
                team.memberships.update(status=TeamMember.Status.ACCEPTED)
                if team.memberships.count() == 1:
                    self.add_members(team, 5)
                with self.assertRaises(TournamentRegistrationError):
                    self.register(actor=self.staff)
                self.assertFalse(self.tournament.can_register(team.captain, team)[0])

    def test_pending_members_do_not_complete_roster(self):
        self.add_members(self.teams[0], 4, pending=True)
        with self.assertRaises(TournamentRegistrationError):
            self.register()
        self.set_rule(Tournament.RosterRule.BY_START)
        self.register()
        with self.assertRaises(TournamentError) as error:
            validate_start_roster(self.tournament)
        self.assertIn('1/5', str(error.exception))
        self.teams[0].memberships.update(status=TeamMember.Status.ACCEPTED)
        validate_start_roster(self.tournament)

    def test_loose_rule_preserves_checkin_and_captain_requirements(self):
        self.set_rule(Tournament.RosterRule.ALLOW_INCOMPLETE)
        self.add_members(self.teams[0], 1, checkin=False)
        with self.assertRaises(TournamentNotCheckedInError):
            self.register()
        other_user = self.teams[1].captain
        with self.assertRaises(TournamentRegistrationError):
            TournamentRegistrationService.register_team(self.tournament.pk, user=other_user,
                team_id=self.teams[0].pk)

    def test_cancelled_checkin_not_ready_in_ui_or_service(self):
        self.set_rule(Tournament.RosterRule.BY_START)
        EventRegistration.objects.filter(user=self.teams[0].captain).update(
            payment_status=EventRegistration.PaymentStatus.CANCELLED)
        with self.assertRaises(TournamentNotCheckedInError):
            self.register()
        self.client.force_login(self.teams[0].captain)
        response = self.client.get(reverse('tournament_detail', args=[self.tournament.slug]))
        self.assertFalse(response.context['team_registration_ready'])
        self.assertEqual(response.context['team_readiness'][0]['checked_in'], 0)

    def test_by_start_reports_all_partial_teams_without_generating_matches(self):
        self.set_rule(Tournament.RosterRule.BY_START)
        self.raw_registrations()
        with self.assertRaises(TournamentError) as error:
            TournamentBracketService.generate_bracket(self.tournament.pk, actor=self.staff)
        for team in self.teams:
            self.assertIn(team.name, str(error.exception))
        self.assertIn('1/5', str(error.exception))
        self.tournament.refresh_from_db()
        self.assertFalse(self.tournament.is_generated)
        self.assertFalse(self.tournament.matches.exists())
        self.assertEqual(self.tournament.registrations.count(), 4)
        for team in self.teams:
            self.add_members(team, 4)
        TournamentBracketService.generate_bracket(self.tournament.pk, actor=self.staff)
        self.tournament.refresh_from_db()
        self.assertTrue(self.tournament.is_generated)

    def test_allow_incomplete_generates_all_six_modes(self):
        self.set_rule(Tournament.RosterRule.ALLOW_INCOMPLETE)
        for mode in Tournament.Mode.values:
            with self.subTest(mode=mode):
                tournament = Tournament.objects.create(title=f'Partial {mode}', game=self.game,
                    event=self.event, mode=mode, roster_rule=Tournament.RosterRule.ALLOW_INCOMPLETE,
                    swiss_rounds=1, registration_start=self.tournament.registration_start,
                    registration_end=self.tournament.registration_end,
                    status=Tournament.Status.REGISTRATION_OPEN)
                for team in self.teams:
                    TournamentRegistration.objects.create(tournament=tournament, team=team)
                TournamentBracketService.generate_bracket(tournament.pk, actor=self.staff)
                tournament.refresh_from_db()
                self.assertTrue(tournament.is_generated)
                self.assertTrue(tournament.matches.exists())

    def test_start_revalidates_roster_after_rule_change_or_member_departure(self):
        self.set_rule(Tournament.RosterRule.ALLOW_INCOMPLETE)
        self.raw_registrations()
        self.set_rule(Tournament.RosterRule.STRICT)
        with self.assertRaises(TournamentError):
            validate_start_roster(self.tournament)
        self.assertEqual(self.tournament.registrations.count(), 4)
        self.set_rule(Tournament.RosterRule.ALLOW_INCOMPLETE)
        self.teams[0].memberships.all().delete()
        with self.assertRaises(TournamentError) as error:
            validate_start_roster(self.tournament)
        self.assertIn('0/5', str(error.exception))

    def test_start_preserves_other_roster_integrity_checks(self):
        self.set_rule(Tournament.RosterRule.ALLOW_INCOMPLETE)
        self.raw_registrations()
        team = self.teams[0]
        team.is_archived = True
        team.save()
        with self.assertRaises(TournamentError):
            validate_start_roster(self.tournament)
        team.is_archived = False
        team.save()
        team.captain.is_active = False
        team.captain.save()
        with self.assertRaises(TournamentError):
            validate_start_roster(self.tournament)
        team.captain.is_active = True
        team.captain.save()
        TeamMember.objects.create(team=self.teams[1], user=team.captain,
            status=TeamMember.Status.ACCEPTED)
        with self.assertRaises(TournamentError):
            validate_start_roster(self.tournament)

    def test_generated_rules_frozen_in_model_and_admin(self):
        self.set_rule(Tournament.RosterRule.ALLOW_INCOMPLETE)
        self.raw_registrations()
        TournamentBracketService.generate_bracket(self.tournament.pk, actor=self.staff)
        self.tournament.refresh_from_db()
        request = RequestFactory().get('/')
        request.user = self.staff
        model_admin = TournamentAdmin(Tournament, admin.site)
        self.assertIn('roster_rule', model_admin.get_readonly_fields(request, self.tournament))
        self.tournament.roster_rule = Tournament.RosterRule.STRICT
        with self.assertRaises(ValidationError):
            self.tournament.full_clean()
        with self.assertRaises(ValidationError):
            self.tournament.save(update_fields=['roster_rule'])

    def test_restart_copies_roster_rule_and_allows_editing_new_edition(self):
        for rule in Tournament.RosterRule.values:
            with self.subTest(rule=rule):
                self.set_rule(rule)
                plan = TournamentRestartService.preview(self.tournament.pk, actor=self.staff)
                edition, created = TournamentRestartService.create(self.tournament.pk,
                    actor=self.staff, preview_token=plan['token'], title=f'Restart {rule}',
                    registration_start=self.tournament.registration_start,
                    registration_end=self.tournament.registration_end, reason='Roster test')
                self.assertTrue(created)
                self.assertEqual(edition.roster_rule, rule)
                edition.roster_rule = Tournament.RosterRule.BY_START
                edition.save()

    def test_swiss_preview_stale_after_roster_rule_change(self):
        for team in self.teams:
            self.add_members(team, 4)
        self.tournament.mode = Tournament.Mode.SWISS
        self.tournament.swiss_rounds = 1
        self.set_rule(Tournament.RosterRule.BY_START)
        self.raw_registrations()
        plan = SwissTournamentService.preview(self.tournament.pk, actor=self.staff)
        self.set_rule(Tournament.RosterRule.ALLOW_INCOMPLETE)
        with self.assertRaises(TournamentError):
            SwissTournamentService.publish(self.tournament.pk, actor=self.staff, token=plan['token'])
        self.assertFalse(self.tournament.matches.exists())

    def test_ui_readiness_obeys_rule_and_shows_accepted_count(self):
        self.add_members(self.teams[0], 4, pending=True)
        self.client.force_login(self.teams[0].captain)
        for rule in Tournament.RosterRule.values:
            with self.subTest(rule=rule):
                self.set_rule(rule)
                response = self.client.get(reverse('tournament_detail', args=[self.tournament.slug]))
                row = response.context['team_readiness'][0]
                self.assertEqual(row['count'], 1)
                self.assertEqual(row['ready'], rule != Tournament.RosterRule.STRICT)
                self.assertContains(response, self.tournament.get_roster_rule_display())

    def test_ui_notices_persist_after_registration_closes_and_admin_sees_all_teams(self):
        self.set_rule(Tournament.RosterRule.BY_START)
        self.raw_registrations()
        self.tournament.status = Tournament.Status.REGISTRATION_CLOSED
        self.tournament.save()
        self.client.force_login(self.teams[0].captain)
        url = reverse('tournament_detail', args=[self.tournament.slug])
        response = self.client.get(url)
        self.assertEqual(response.context['user_roster_notice']['count'], 1)
        self.assertContains(response, 'Kader bis zum Turnierstart vervollständigen')
        self.assertContains(response, '1/5 bestätigte Spieler')
        self.client.force_login(self.staff)
        response = self.client.get(url)
        self.assertEqual(len(response.context['roster_warnings']), 4)
        self.assertContains(response, 'Kaderprüfung vor dem Turnierstart')
        self.assertContains(response, 'Kader erfüllt die Startregel nicht')

    def test_ui_never_claims_empty_roster_is_allowed(self):
        self.set_rule(Tournament.RosterRule.ALLOW_INCOMPLETE)
        self.raw_registrations()
        self.teams[0].memberships.all().delete()
        self.client.force_login(self.staff)
        response = self.client.get(reverse('tournament_detail', args=[self.tournament.slug]))
        self.assertFalse(response.context['roster_warnings'][0]['start_allowed'])
        self.assertContains(response, '0/5 bestätigte Spieler')
        self.assertContains(response, 'Die Zahl der bestätigten Spieler liegt außerhalb der erlaubten Teamgröße.')
