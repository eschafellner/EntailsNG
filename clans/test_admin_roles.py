from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from users.services import UserService

from .models import Clan, ClanMembership
from .forms import ClanForm
from .services import ClanManagementError, leave_clan, manage_member


class ClanAdminRoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.clan = Clan.objects.create(name='Admin roles')
        cls.leader = get_user_model().objects.create_user('role-leader')
        cls.member = get_user_model().objects.create_user('role-member')
        cls.leader_membership = ClanMembership.objects.create(
            clan=cls.clan, user=cls.leader, role=ClanMembership.Role.ADMIN,
        )
        cls.member_membership = ClanMembership.objects.create(clan=cls.clan, user=cls.member)

    def setUp(self):
        self.client.force_login(self.leader)

    def url(self, membership=None, name='clan_manage_member'):
        return reverse(name, args=[self.clan.slug, (membership or self.member_membership).pk])

    def post(self, action, membership=None, **extra):
        return self.client.post(self.url(membership), {'action': action, 'confirmed': '1', **extra}, follow=True)

    def promote(self):
        manage_member(self.clan.pk, self.leader.pk, self.member_membership.pk, 'promote')

    def test_unlimited_admins_and_public_overview(self):
        for index in range(6):
            user = get_user_model().objects.create_user(f'role-admin-{index}')
            membership = ClanMembership.objects.create(clan=self.clan, user=user)
            self.post('promote', membership)
        response = self.client.get(reverse('clan_detail', args=[self.clan.slug]))
        self.assertEqual(response.context['admin_count'], 7)
        for index in range(6):
            self.assertContains(response, f'role-admin-{index}')
        self.client.logout()
        self.assertContains(self.client.get(reverse('clan_detail', args=[self.clan.slug])), 'Clan-Admins (7)')

    def test_promoted_admin_can_manage_roles_equally(self):
        self.promote()
        self.client.force_login(self.member)
        response = self.post('demote', self.leader_membership)
        self.leader_membership.refresh_from_db()
        self.assertEqual(self.leader_membership.role, ClanMembership.Role.MEMBER)
        self.assertContains(response, 'role-leader ist jetzt Clan-Mitglied ohne Adminrechte.')
        self.assertTrue(self.clan.is_admin(self.member))

    def test_demotion_keeps_membership_and_join_date(self):
        self.promote()
        joined = self.member_membership.created_at
        self.post('demote')
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.status, ClanMembership.Status.ACCEPTED)
        self.assertEqual(self.member_membership.created_at, joined)
        self.assertEqual(self.member_membership.role, ClanMembership.Role.MEMBER)

    def test_admin_can_demote_self_when_another_admin_remains(self):
        self.promote()
        self.post('demote', self.leader_membership)
        self.assertFalse(self.clan.is_admin(self.leader))
        self.assertTrue(self.clan.is_admin(self.member))
        response = self.client.get(reverse('clan_detail', args=[self.clan.slug]))
        self.assertNotContains(response, 'Änderung bestätigen')

    def test_last_admin_self_demotion_blocked_in_backend_and_ui(self):
        response = self.post('demote', self.leader_membership)
        self.assertContains(response, 'Mindestens ein aktiver Clan-Admin muss erhalten bleiben.')
        self.assertContains(response, 'disabled aria-describedby="clan-last-admin-')
        self.assertTrue(self.clan.is_admin(self.leader))

    def test_inactive_admin_is_not_a_replacement(self):
        self.promote()
        get_user_model().objects.filter(pk=self.member.pk).update(is_active=False)
        self.post('demote', self.leader_membership)
        self.assertTrue(self.clan.is_admin(self.leader))

    def test_inactive_former_admin_can_be_demoted(self):
        self.promote()
        get_user_model().objects.filter(pk=self.member.pk).update(is_active=False)
        self.post('demote')
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, ClanMembership.Role.MEMBER)

    def test_pending_members_cannot_receive_admin_role(self):
        self.member_membership.status = ClanMembership.Status.PENDING
        self.member_membership.save(update_fields=['status'])
        self.post('promote')
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, ClanMembership.Role.MEMBER)
        self.assertEqual(self.member_membership.status, ClanMembership.Status.PENDING)

    def test_inactive_and_deleted_members_cannot_receive_admin_role(self):
        for changes in ({'is_active': False}, {'is_active': True, 'deleted_at': timezone.now()}):
            with self.subTest(changes=changes):
                get_user_model().objects.filter(pk=self.member.pk).update(**changes)
                self.post('promote')
                self.member_membership.refresh_from_db()
                self.assertEqual(self.member_membership.role, ClanMembership.Role.MEMBER)

    def test_confirmation_required_for_both_role_actions(self):
        self.client.post(self.url(), {'action': 'promote'})
        self.assertFalse(self.clan.is_admin(self.member))
        self.promote()
        self.client.post(self.url(), {'action': 'demote'})
        self.assertTrue(self.clan.is_admin(self.member))

    def test_non_admin_cannot_manage_roles(self):
        self.client.force_login(self.member)
        self.post('demote', self.leader_membership)
        self.assertTrue(self.clan.is_admin(self.leader))
        self.assertFalse(self.clan.is_admin(self.member))

    def test_service_rechecks_revoked_actor_rights(self):
        self.promote()
        manage_member(self.clan.pk, self.member.pk, self.leader_membership.pk, 'demote')
        with self.assertRaises(ClanManagementError):
            manage_member(self.clan.pk, self.leader.pk, self.member_membership.pk, 'demote')

    def test_edit_rechecks_admin_rights_before_saving_valid_form(self):
        self.promote()
        original_validation = ClanForm.is_valid

        def revoke_after_validation(form):
            valid = original_validation(form)
            manage_member(self.clan.pk, self.member.pk, self.leader_membership.pk, 'demote')
            return valid

        with patch.object(ClanForm, 'is_valid', revoke_after_validation):
            self.client.post(reverse('clan_edit', args=[self.clan.slug]),
                {'name': 'Unauthorized rename', 'tag': '', 'website': '', 'password': ''})
        self.clan.refresh_from_db()
        self.assertEqual(self.clan.name, 'Admin roles')
        self.assertFalse(self.clan.is_admin(self.leader))

    def test_service_rechecks_inactive_actor(self):
        get_user_model().objects.filter(pk=self.leader.pk).update(is_active=False)
        with self.assertRaises(ClanManagementError):
            manage_member(self.clan.pk, self.leader.pk, self.member_membership.pk, 'promote')

    def test_foreign_clan_membership_rejected(self):
        clan = Clan.objects.create(name='Other roles')
        outsider = get_user_model().objects.create_user('role-outsider')
        membership = ClanMembership.objects.create(clan=clan, user=outsider)
        self.assertEqual(self.client.post(self.url(membership), {'action': 'promote', 'confirmed': '1'}).status_code, 404)
        membership.refresh_from_db()
        self.assertEqual(membership.role, ClanMembership.Role.MEMBER)

    def test_get_csrf_and_unknown_action_do_not_change_roles(self):
        self.assertEqual(self.client.get(self.url()).status_code, 405)
        secured = Client(enforce_csrf_checks=True)
        secured.force_login(self.leader)
        self.assertEqual(secured.post(self.url(), {'action': 'promote', 'confirmed': '1'}).status_code, 403)
        self.post('arbitrary')
        self.assertFalse(self.clan.is_admin(self.member))

    def test_duplicate_role_change_reports_stale_form(self):
        self.promote()
        self.assertContains(self.post('promote'), 'Diese Rolle ist bereits gesetzt.')

    def test_request_endpoint_cannot_remove_or_accept_confirmed_admin(self):
        for action in ('reject', 'accept'):
            response = self.client.post(self.url(self.leader_membership, 'clan_manage_request'), {'action': action}, follow=True)
            self.assertContains(response, 'Diese Beitrittsanfrage ist nicht mehr offen.')
            self.assertTrue(self.clan.is_admin(self.leader))

    def test_accepted_request_always_becomes_regular_member(self):
        self.member_membership.status = ClanMembership.Status.PENDING
        self.member_membership.role = ClanMembership.Role.ADMIN
        self.member_membership.save()
        self.client.post(self.url(name='clan_manage_request'), {'action': 'accept'})
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, ClanMembership.Role.MEMBER)
        self.assertEqual(self.member_membership.status, ClanMembership.Status.ACCEPTED)

    def test_other_admin_can_be_removed_but_self_kick_is_blocked(self):
        self.promote()
        self.post('kick', self.leader_membership)
        self.assertTrue(self.clan.is_admin(self.leader))
        self.post('kick')
        self.assertFalse(ClanMembership.objects.filter(pk=self.member_membership.pk).exists())
        self.assertTrue(self.clan.is_admin(self.leader))

    def test_leave_preserves_other_admin(self):
        self.promote()
        self.client.post(reverse('clan_leave', args=[self.clan.slug]))
        self.assertTrue(self.clan.is_admin(self.member))
        self.assertFalse(ClanMembership.objects.filter(user=self.leader, clan=self.clan).exists())

    def test_succession_skips_inactive_member(self):
        get_user_model().objects.filter(pk=self.member.pk).update(is_active=False)
        successor = get_user_model().objects.create_user('role-successor')
        ClanMembership.objects.create(clan=self.clan, user=successor)
        self.client.post(reverse('clan_leave', args=[self.clan.slug]))
        self.assertTrue(self.clan.is_admin(successor))
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, ClanMembership.Role.MEMBER)

    def test_departure_without_active_successor_is_rolled_back(self):
        get_user_model().objects.filter(pk=self.member.pk).update(is_active=False)
        with self.assertRaises(ClanManagementError):
            leave_clan(self.clan.pk, self.leader.pk)
        self.assertTrue(self.clan.is_admin(self.leader))

    def test_account_deletion_assigns_active_successor_despite_inactive_admin(self):
        self.promote()
        get_user_model().objects.filter(pk=self.member.pk).update(is_active=False)
        successor = get_user_model().objects.create_user('role-delete-successor')
        ClanMembership.objects.create(clan=self.clan, user=successor)
        self.leader.set_password('clan-role-delete-test')
        self.leader.save(update_fields=['password'])
        UserService.delete_account(self.leader, 'clan-role-delete-test')
        self.assertTrue(self.clan.is_admin(successor))
