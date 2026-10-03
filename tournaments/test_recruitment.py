from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from clans.models import Clan, ClanMembership
from configuration.models import NavigationItem
from events.models import Event
from tournaments.exceptions import TournamentError
from tournaments.models import Game, Team, TeamInvitation, TeamMember, Tournament, TournamentRegistration
from tournaments.services.recruitment import add_clan_members, recruit_player, respond_to_invitation, received_invitations


class TeamRecruitmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.event = Event.objects.create(title='Recruitment LAN', is_active=True,
            status=Event.Status.REGISTRATION_OPEN, start_date=now, end_date=now + timedelta(days=2))
        cls.game = Game.objects.create(name='Recruitment Game', team_size=3)
        cls.captain = get_user_model().objects.create_user('recruit-captain')
        cls.clanmate = get_user_model().objects.create_user('recruit-clanmate')
        cls.second_clanmate = get_user_model().objects.create_user('recruit-clanmate-two')
        cls.outsider = get_user_model().objects.create_user('recruit-outsider', email='hidden@example.com')
        cls.stranger = get_user_model().objects.create_user('recruit-stranger')
        cls.clan = Clan.objects.create(name='Recruitment Clan', password='')
        for user in (cls.captain, cls.clanmate, cls.second_clanmate):
            # A team captain does not need to be clan admin.
            ClanMembership.objects.create(clan=cls.clan, user=user, role=ClanMembership.Role.MEMBER)
        cls.team = Team.objects.create(name='Recruitment Team', captain=cls.captain, game=cls.game, event=cls.event)
        TeamMember.objects.create(team=cls.team, user=cls.captain, role=TeamMember.Role.CAPTAIN)
        NavigationItem.objects.get_or_create(url_name='team_list', defaults={'title': 'Teams'})

    def invitation(self, user=None):
        recruit_player(self.team.pk, self.captain, (user or self.outsider).pk)
        return TeamInvitation.objects.get(team=self.team, user=user or self.outsider, status=TeamInvitation.Status.PENDING)

    def client_for(self, user):
        client = Client()
        client.force_login(user)
        return client

    def test_batch_adds_clan_members_immediately_without_invitations(self):
        count = add_clan_members(self.team.pk, self.captain, [self.clanmate.pk, self.second_clanmate.pk, self.clanmate.pk])
        self.assertEqual(count, 2)
        self.assertEqual(self.team.get_accepted_members().count(), 3)
        self.assertFalse(TeamInvitation.objects.exists())
        member = TeamMember.objects.get(team=self.team, user=self.clanmate)
        self.assertEqual(member.added_by, self.captain)
        response = self.client_for(self.clanmate).get(reverse('team_list'))
        self.assertContains(response, 'hat dich dem Team Recruitment Team hinzugefügt')
        self.assertEqual(response.context['user_pending_team_requests_count'], 0)

    def test_later_clan_exit_keeps_team_membership(self):
        add_clan_members(self.team.pk, self.captain, [self.clanmate.pk])
        ClanMembership.objects.filter(user=self.clanmate).delete()
        self.assertTrue(self.team.is_member(self.clanmate))

    def test_pending_clan_membership_and_matching_tag_do_not_authorize_direct_addition(self):
        ClanMembership.objects.create(user=self.outsider, clan=self.clan, status=ClanMembership.Status.PENDING)
        self.team.tag = 'CLAN'
        self.team.save()
        with self.assertRaises(TournamentError):
            add_clan_members(self.team.pk, self.captain, [self.clanmate.pk, self.outsider.pk])
        self.assertFalse(self.team.is_member(self.clanmate))
        result, _ = recruit_player(self.team.pk, self.captain, self.outsider.pk)
        self.assertEqual(result, 'invited')
        self.assertFalse(self.team.is_member(self.outsider))

    def test_clanmate_recruited_through_search_is_added_directly(self):
        result, _ = recruit_player(self.team.pk, self.captain, self.clanmate.pk)
        self.assertEqual(result, 'added')
        self.assertTrue(self.team.is_member(self.clanmate))

    def test_batch_rolls_back_if_capacity_is_insufficient(self):
        self.game.team_size = 2
        self.game.save()
        with self.assertRaises(TournamentError):
            add_clan_members(self.team.pk, self.captain, [self.clanmate.pk, self.second_clanmate.pk])
        self.assertEqual(self.team.get_accepted_members().count(), 1)

    def test_clan_changed_since_page_load_is_rechecked(self):
        ClanMembership.objects.filter(user=self.clanmate).delete()
        response = self.client_for(self.captain).post(reverse('team_add_clan_members', args=[self.team.slug]),
            {'user_ids': [self.clanmate.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.team.is_member(self.clanmate))

    def test_only_current_captain_can_recruit_even_if_actor_is_staff(self):
        self.stranger.is_staff = True
        self.stranger.save()
        client = self.client_for(self.stranger)
        for endpoint, data in (
            ('team_add_clan_members', {'user_ids': [self.clanmate.pk]}),
            ('team_recruit_player', {'user_id': self.outsider.pk}),
        ):
            with self.subTest(endpoint=endpoint):
                response = client.post(reverse(endpoint, args=[self.team.slug]), data)
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.team.get_accepted_members().count(), 1)
        self.assertFalse(TeamInvitation.objects.exists())

    def test_invitation_requires_recipient_consent_and_displays_red_dots_until_resolved(self):
        invitation = self.invitation()
        self.assertFalse(TeamMember.objects.filter(team=self.team, user=self.outsider).exists())
        client = self.client_for(self.outsider)
        for _ in range(2):
            response = client.get(reverse('team_list'))
            self.assertContains(response, 'Meine Einladungen')
            self.assertContains(response, 'class="nav-notification-dot"')
            self.assertContains(response, 'class="mobile-notification-dot"')
            self.assertEqual(response.context['user_pending_team_requests_count'], 1)
        self.assertEqual(self.client_for(self.captain).get(reverse('team_list')).context['user_pending_team_requests_count'], 0)
        response = client.post(reverse('team_accept_invitation', args=[self.team.slug, invitation.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.team.is_member(self.outsider))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeamInvitation.Status.ACCEPTED)
        self.assertIsNotNone(invitation.resolved_at)
        self.assertEqual(client.get(reverse('team_list')).context['user_pending_team_requests_count'], 0)

    def test_captain_and_stranger_cannot_accept_or_decline_someone_elses_invitation(self):
        invitation = self.invitation()
        for actor in (self.captain, self.stranger):
            for endpoint in ('team_accept_invitation', 'team_decline_invitation'):
                with self.subTest(actor=actor.username, endpoint=endpoint):
                    response = self.client_for(actor).post(reverse(endpoint, args=[self.team.slug, invitation.pk]))
                    self.assertEqual(response.status_code, 403)
        self.assertFalse(self.team.is_member(self.outsider))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeamInvitation.Status.PENDING)

    def test_decline_then_reinvite_and_withdraw(self):
        invitation = self.invitation()
        respond_to_invitation(self.team.pk, self.outsider, invitation.pk, 'decline')
        self.assertFalse(self.team.is_member(self.outsider))
        second = self.invitation()
        self.assertNotEqual(second.pk, invitation.pk)
        with self.assertRaises(PermissionDenied):
            respond_to_invitation(self.team.pk, self.stranger, second.pk, 'withdraw')
        respond_to_invitation(self.team.pk, self.captain, second.pk, 'withdraw')
        with self.assertRaises(TournamentError):
            respond_to_invitation(self.team.pk, self.outsider, second.pk, 'accept')
        self.assertEqual(received_invitations(self.outsider, self.event).count(), 0)

    def test_pending_invitations_do_not_reserve_capacity_and_acceptance_rechecks_it(self):
        self.game.team_size = 2
        self.game.save()
        first = self.invitation()
        second = self.invitation(self.stranger)
        self.assertEqual(self.team.get_accepted_members().count(), 1)
        respond_to_invitation(self.team.pk, self.outsider, first.pk, 'accept')
        with self.assertRaises(TournamentError):
            respond_to_invitation(self.team.pk, self.stranger, second.pk, 'accept')
        second.refresh_from_db()
        self.assertEqual(second.status, TeamInvitation.Status.PENDING)

    def test_duplicate_invitation_is_prevented_in_service_and_database(self):
        self.invitation()
        with self.assertRaises(TournamentError):
            recruit_player(self.team.pk, self.captain, self.outsider.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamInvitation.objects.create(team=self.team, user=self.outsider)
        self.assertEqual(TeamInvitation.objects.count(), 1)

    def test_existing_application_is_not_silently_accepted_by_an_invitation(self):
        member = TeamMember.objects.create(team=self.team, user=self.outsider, status=TeamMember.Status.PENDING)
        with self.assertRaises(TournamentError):
            recruit_player(self.team.pk, self.captain, self.outsider.pk)
        member.refresh_from_db()
        self.assertEqual(member.status, TeamMember.Status.PENDING)
        self.assertFalse(TeamInvitation.objects.exists())

    def test_pending_invitation_does_not_create_a_second_application(self):
        self.invitation()
        response = self.client_for(self.outsider).post(reverse('team_apply', args=[self.team.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(TeamMember.objects.filter(team=self.team, user=self.outsider).exists())

    def test_captain_can_reject_applications_but_cannot_delete_accepted_members_this_way(self):
        member = TeamMember.objects.create(team=self.team, user=self.outsider, status=TeamMember.Status.PENDING)
        client = self.client_for(self.captain)
        response = client.post(reverse('team_reject_application', args=[self.team.slug, member.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(TeamMember.objects.filter(pk=member.pk).exists())
        self.assertEqual(client.get(reverse('team_list')).context['user_pending_team_requests_count'], 0)
        accepted = TeamMember.objects.get(team=self.team, user=self.captain)
        client.post(reverse('team_reject_application', args=[self.team.slug, accepted.pk]))
        self.assertTrue(TeamMember.objects.filter(pk=accepted.pk).exists())

    def test_code_join_stays_voluntary_and_resolves_personal_invitation(self):
        invitation = self.invitation()
        response = self.client_for(self.outsider).post(reverse('team_join_by_code'), {'invite_code': self.team.invite_code})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.team.is_member(self.outsider))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeamInvitation.Status.ACCEPTED)

    def test_other_active_team_blocks_direct_addition_and_invitation_acceptance(self):
        invitation = self.invitation()
        other = Team.objects.create(name='Other recruitment team', captain=self.stranger, game=self.game, event=self.event)
        for user in (self.outsider, self.clanmate):
            TeamMember.objects.create(team=other, user=user)
        with self.assertRaises(TournamentError):
            add_clan_members(self.team.pk, self.captain, [self.clanmate.pk])
        with self.assertRaises(TournamentError):
            respond_to_invitation(self.team.pk, self.outsider, invitation.pk, 'accept')
        self.assertFalse(self.team.is_member(self.outsider))

    def test_membership_in_a_different_game_or_archived_team_is_allowed(self):
        invitation = self.invitation()
        other_game = Game.objects.create(name='Other recruitment game', team_size=2)
        other = Team.objects.create(name='Other game team', captain=self.stranger, game=other_game)
        archived = Team.objects.create(name='Archived game team', captain=self.stranger, game=self.game, is_archived=True)
        TeamMember.objects.create(team=other, user=self.clanmate)
        TeamMember.objects.create(team=archived, user=self.clanmate)
        TeamMember.objects.create(team=archived, user=self.outsider)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeamInvitation.Status.PENDING)
        add_clan_members(self.team.pk, self.captain, [self.clanmate.pk])
        self.assertTrue(self.team.is_member(self.clanmate))

    def test_unavailable_users_are_blocked_and_not_listed(self):
        for field, value in (('is_active', False), ('deleted_at', timezone.now())):
            with self.subTest(field=field):
                get_user_model().objects.filter(pk=self.outsider.pk).update(**{field: value})
                with self.assertRaises(TournamentError):
                    recruit_player(self.team.pk, self.captain, self.outsider.pk)
                response = self.client_for(self.captain).get(reverse('team_detail', args=[self.team.slug]), {'q': 'outsider'})
                self.assertEqual(response.context['recruitment_results'], [])
                get_user_model().objects.filter(pk=self.outsider.pk).update(is_active=True, deleted_at=None)
        invitation = self.invitation()
        get_user_model().objects.filter(pk=self.captain.pk).update(is_active=False)
        with self.assertRaises(TournamentError):
            respond_to_invitation(self.team.pk, self.outsider, invitation.pk, 'accept')
        self.assertFalse(received_invitations(self.outsider, self.event).exists())

    def test_search_and_controls_are_captain_only_and_do_not_expose_email(self):
        url = reverse('team_detail', args=[self.team.slug])
        response = self.client_for(self.captain).get(url, {'q': 'outsider'})
        self.assertContains(response, 'Mitglieder hinzufügen')
        self.assertContains(response, self.outsider.username)
        self.assertNotContains(response, self.outsider.email)
        self.assertEqual(response.context['recruitment_results'][0]['user'], self.outsider)
        response = self.client_for(self.stranger).get(url, {'q': 'outsider'})
        self.assertNotContains(response, 'id="team-recruitment-title"')
        self.assertNotIn('recruitment_results', response.context)

    def test_search_is_bounded_and_escapes_nicknames(self):
        for index in range(23):
            get_user_model().objects.create_user(f'needle-{index:02}')
        response = self.client_for(self.captain).get(reverse('team_detail', args=[self.team.slug]), {'q': 'needle'})
        self.assertEqual(len(response.context['recruitment_results']), 20)
        player = get_user_model().objects.create_user('needle-<script>')
        response = self.client_for(self.captain).get(reverse('team_detail', args=[self.team.slug]), {'q': '<script>'})
        self.assertContains(response, 'needle-&lt;script&gt;')
        self.assertNotContains(response, player.username)

    def test_write_actions_require_post_and_csrf(self):
        invitation = self.invitation()
        for endpoint, args in (
            ('team_add_clan_members', [self.team.slug]),
            ('team_recruit_player', [self.team.slug]),
            ('team_accept_invitation', [self.team.slug, invitation.pk]),
            ('team_decline_invitation', [self.team.slug, invitation.pk]),
            ('team_withdraw_invitation', [self.team.slug, invitation.pk]),
            ('team_reject_application', [self.team.slug, 1]),
        ):
            with self.subTest(endpoint=endpoint):
                client = self.client_for(self.captain)
                self.assertEqual(client.get(reverse(endpoint, args=args)).status_code, 405)
                csrf_client = Client(enforce_csrf_checks=True)
                csrf_client.force_login(self.captain)
                self.assertEqual(csrf_client.post(reverse(endpoint, args=args)).status_code, 403)

    def test_malformed_missing_and_foreign_ids_cannot_modify_rosters(self):
        client = self.client_for(self.captain)
        for user_id in ('invalid', '-1', '999999', str(self.captain.pk)):
            client.post(reverse('team_recruit_player', args=[self.team.slug]), {'user_id': user_id})
        self.assertEqual(self.team.get_accepted_members().count(), 1)
        other = Team.objects.create(name='Foreign invite team', captain=self.captain, game=self.game)
        invitation = self.invitation()
        response = self.client_for(self.outsider).post(reverse('team_accept_invitation', args=[other.slug, invitation.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.team.is_member(self.outsider))

    def test_archived_solo_and_closed_teams_block_recruitment(self):
        for field, value in (('is_archived', True), ('is_solo', True)):
            with self.subTest(field=field):
                setattr(self.team, field, value)
                self.team.save()
                with self.assertRaises(TournamentError):
                    recruit_player(self.team.pk, self.captain, self.outsider.pk)
                setattr(self.team, field, False)
                self.team.save()
        self.event.status = Event.Status.CANCELLED
        self.event.save()
        with self.assertRaises(TournamentError):
            add_clan_members(self.team.pk, self.captain, [self.clanmate.pk])

    def test_generated_or_running_tournament_blocks_recruitment_and_expires_invitations(self):
        invitation = self.invitation()
        now = timezone.now()
        tournament = Tournament.objects.create(title='Recruitment Cup', game=self.game, event=self.event,
            status=Tournament.Status.REGISTRATION_OPEN, registration_start=now, registration_end=now + timedelta(hours=1))
        TournamentRegistration.objects.create(tournament=tournament, team=self.team)
        tournament.is_generated = True
        tournament.save()
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeamInvitation.Status.EXPIRED)
        with self.assertRaises(TournamentError):
            add_clan_members(self.team.pk, self.captain, [self.clanmate.pk])
        self.assertFalse(received_invitations(self.outsider, self.event).exists())

    def test_archiving_and_reactivation_do_not_revive_invitations(self):
        invitation = self.invitation()
        self.team.is_archived = True
        self.team.save()
        self.team.is_archived = False
        self.team.save()
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeamInvitation.Status.EXPIRED)
        self.assertFalse(received_invitations(self.outsider, self.event).exists())

    def test_event_end_account_deactivation_and_soft_deletion_expire_invitations(self):
        for mode in ('event', 'inactive', 'deleted'):
            with self.subTest(mode=mode):
                invitation = self.invitation()
                if mode == 'event':
                    self.event.status = Event.Status.CANCELLED
                    self.event.save()
                else:
                    setattr(self.outsider, 'is_active' if mode == 'inactive' else 'deleted_at',
                        False if mode == 'inactive' else timezone.now())
                    self.outsider.save()
                invitation.refresh_from_db()
                self.assertEqual(invitation.status, TeamInvitation.Status.EXPIRED)
                self.event.status = Event.Status.REGISTRATION_OPEN
                self.event.save()
                self.outsider.is_active, self.outsider.deleted_at = True, None
                # Soft-deleted users cannot be revived through save(). Restore test fixture explicitly.
                get_user_model().objects.filter(pk=self.outsider.pk).update(is_active=True, deleted_at=None)

    def test_old_event_invitations_are_hidden_and_cannot_be_accepted(self):
        invitation = self.invitation()
        Event.objects.filter(pk=self.event.pk).update(is_active=False)
        from django.core.cache import cache
        cache.clear()
        now = timezone.now()
        other_event = Event.objects.create(title='Next recruitment LAN', is_active=True,
            start_date=now, end_date=now + timedelta(days=3))
        self.assertFalse(received_invitations(self.outsider, other_event).exists())
        with self.assertRaises(TournamentError):
            respond_to_invitation(self.team.pk, self.outsider, invitation.pk, 'accept')
        self.team.event = None
        self.team.save()
        recruit_player(self.team.pk, self.captain, self.outsider.pk)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeamInvitation.Status.EXPIRED)
        self.assertEqual(received_invitations(self.outsider, other_event).count(), 1)

    def test_both_invitations_and_captains_applications_count_for_same_user(self):
        other = Team.objects.create(name='Recipient own team', captain=self.outsider, game=Game.objects.create(name='Recipient Game', team_size=2))
        TeamMember.objects.create(team=other, user=self.outsider, role=TeamMember.Role.CAPTAIN)
        TeamMember.objects.create(team=other, user=self.stranger, status=TeamMember.Status.PENDING)
        self.invitation()
        response = self.client_for(self.outsider).get(reverse('team_list'))
        self.assertEqual(response.context['user_pending_team_requests_count'], 2)
