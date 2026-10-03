"""Real row-lock tests; SQLite cannot verify concurrent recruitment."""
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from clans.models import Clan, ClanMembership
from events.models import Event
from tournaments import test_audit_concurrency as audit_tests
from tournaments.exceptions import TournamentError
from tournaments.models import TeamInvitation, TeamMember
from tournaments.services.recruitment import add_clan_members, recruit_player, respond_to_invitation


@skipUnlessDBFeature('has_select_for_update')
class TeamRecruitmentConcurrencyTests(TransactionTestCase):
    setUp = audit_tests.TournamentAuditConcurrencyTests.setUp
    compete = audit_tests.TournamentAuditConcurrencyTests.compete
    client_for = audit_tests.TournamentAuditConcurrencyTests.client_for
    separate_connection = staticmethod(audit_tests.TournamentAuditConcurrencyTests.separate_connection)

    def invitation(self, team, user):
        recruit_player(team.pk, team.captain, user.pk)
        return TeamInvitation.objects.get(team=team, user=user, status=TeamInvitation.Status.PENDING)

    @staticmethod
    def attempt(action):
        try:
            action()
        except TournamentError:
            return False
        return True

    def test_parallel_acceptances_do_not_overfill_last_slot(self):
        a = get_user_model().objects.create_user('invite-race-a')
        b = get_user_model().objects.create_user('invite-race-b')
        team = self.teams[0]
        first, second = self.invitation(team, a), self.invitation(team, b)
        result = self.compete(lambda: respond_to_invitation(team.pk, a, first.pk, 'accept'),
            lambda: self.attempt(lambda: respond_to_invitation(team.pk, b, second.pk, 'accept')))
        self.assertFalse(result)
        self.assertEqual(team.get_accepted_members().count(), 2)
        self.assertFalse(team.is_member(b))

    def test_same_player_cannot_accept_two_teams_for_one_game(self):
        user = get_user_model().objects.create_user('invite-race-same-player')
        a, b = self.teams[:2]
        first, second = self.invitation(a, user), self.invitation(b, user)
        result = self.compete(lambda: respond_to_invitation(a.pk, user, first.pk, 'accept'),
            lambda: self.attempt(lambda: respond_to_invitation(b.pk, user, second.pk, 'accept')))
        self.assertFalse(result)
        self.assertEqual(TeamMember.objects.filter(user=user, status=TeamMember.Status.ACCEPTED).count(), 1)

    def test_clan_addition_and_legacy_code_join_share_player_locks(self):
        user = get_user_model().objects.create_user('invite-race-clan-player')
        a, b = self.teams[:2]
        clan = Clan.objects.create(name='Race Clan', password='')
        for member in (a.captain, user):
            ClanMembership.objects.create(user=member, clan=clan)
        client = self.client_for(user)
        response = self.compete(lambda: add_clan_members(a.pk, a.captain, [user.pk]),
            lambda: client.post(reverse('team_join_by_code'), {'invite_code': b.invite_code}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TeamMember.objects.filter(user=user, status=TeamMember.Status.ACCEPTED).count(), 1)
        self.assertTrue(a.is_member(user))

    def test_duplicate_parallel_sends_create_one_invitation(self):
        user = get_user_model().objects.create_user('invite-race-duplicate')
        team = self.teams[0]
        result = self.compete(lambda: recruit_player(team.pk, team.captain, user.pk),
            lambda: self.attempt(lambda: recruit_player(team.pk, team.captain, user.pk)))
        self.assertFalse(result)
        self.assertEqual(TeamInvitation.objects.filter(team=team, user=user).count(), 1)

    def test_clan_departure_is_rechecked_after_waiting_for_membership_lock(self):
        user = get_user_model().objects.create_user('invite-race-leaving-clan')
        team = self.teams[0]
        clan = Clan.objects.create(name='Departing Race Clan', password='')
        for member in (team.captain, user):
            ClanMembership.objects.create(user=member, clan=clan)
        def leave_clan():
            membership = ClanMembership.objects.select_for_update().get(user=user)
            membership.delete()
        result = self.compete(leave_clan,
            lambda: self.attempt(lambda: add_clan_members(team.pk, team.captain, [user.pk])))
        self.assertFalse(result)
        self.assertFalse(team.is_member(user))

    def test_event_closure_blocks_waiting_invitation_acceptance(self):
        user = get_user_model().objects.create_user('invite-race-event-end')
        team = self.teams[0]
        invitation = self.invitation(team, user)
        def close_event():
            event = Event.objects.select_for_update().get(pk=self.event.pk)
            event.status = Event.Status.CANCELLED
            event.save(update_fields=['status'])
        result = self.compete(close_event,
            lambda: self.attempt(lambda: respond_to_invitation(team.pk, user, invitation.pk, 'accept')))
        self.assertFalse(result)
        self.assertFalse(team.is_member(user))
