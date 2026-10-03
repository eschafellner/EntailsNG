"""Real row locks are required to verify role changes against clan succession."""
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, skipUnlessDBFeature

from tournaments import test_audit_concurrency as audit_tests
from users.services import UserService
from .models import Clan, ClanMembership
from .services import ClanManagementError, leave_clan, manage_member


@skipUnlessDBFeature('has_select_for_update')
class ClanAdminRoleConcurrencyTests(TransactionTestCase):
    compete = audit_tests.TournamentAuditConcurrencyTests.compete
    separate_connection = staticmethod(audit_tests.TournamentAuditConcurrencyTests.separate_connection)
    client_for = audit_tests.TournamentAuditConcurrencyTests.client_for

    def setUp(self):
        self.clan = Clan.objects.create(name='Concurrent clan admins')
        self.a = get_user_model().objects.create_user('clan-admin-a')
        self.b = get_user_model().objects.create_user('clan-admin-b')
        self.ma = ClanMembership.objects.create(clan=self.clan, user=self.a, role=ClanMembership.Role.ADMIN)
        self.mb = ClanMembership.objects.create(clan=self.clan, user=self.b, role=ClanMembership.Role.ADMIN)

    @staticmethod
    def attempt(action):
        try:
            action()
        except ClanManagementError:
            return False
        return True

    def demote(self, actor, membership):
        return manage_member(self.clan.pk, actor.pk, membership.pk, 'demote')

    def test_mutual_demotions_recheck_actor_privileges(self):
        result = self.compete(lambda: self.demote(self.a, self.mb),
            lambda: self.attempt(lambda: self.demote(self.b, self.ma)))
        self.assertFalse(result)
        self.assertTrue(self.clan.is_admin(self.a))
        self.assertFalse(self.clan.is_admin(self.b))

    def test_waiting_edit_cannot_save_after_actor_is_demoted(self):
        from django.urls import reverse
        client = self.client_for(self.a)
        response = self.compete(lambda: self.demote(self.b, self.ma),
            lambda: client.post(reverse('clan_edit', args=[self.clan.slug]),
                {'name': 'Unauthorized concurrent rename', 'tag': '', 'website': '', 'password': ''}))
        self.assertEqual(response.status_code, 302)
        self.clan.refresh_from_db()
        self.assertEqual(self.clan.name, 'Concurrent clan admins')

    def test_parallel_self_demotions_keep_one_admin(self):
        result = self.compete(lambda: self.demote(self.a, self.ma),
            lambda: self.attempt(lambda: self.demote(self.b, self.mb)))
        self.assertFalse(result)
        self.assertTrue(self.clan.is_admin(self.b))

    def test_departure_blocks_waiting_last_admin_demotion(self):
        result = self.compete(lambda: leave_clan(self.clan.pk, self.a.pk),
            lambda: self.attempt(lambda: self.demote(self.b, self.mb)))
        self.assertFalse(result)
        self.assertTrue(self.clan.is_admin(self.b))

    def test_departure_after_demotion_assigns_a_successor(self):
        self.compete(lambda: self.demote(self.a, self.ma), lambda: leave_clan(self.clan.pk, self.b.pk))
        self.assertTrue(self.clan.is_admin(self.a))
        self.assertFalse(ClanMembership.objects.filter(user=self.b).exists())

    def test_account_deletion_blocks_waiting_last_admin_demotion(self):
        self.a.set_password('clan-role-delete-test')
        self.a.save(update_fields=['password'])
        result = self.compete(lambda: UserService.delete_account(self.a, 'clan-role-delete-test'),
            lambda: self.attempt(lambda: self.demote(self.b, self.mb)))
        self.assertFalse(result)
        self.assertTrue(self.clan.is_admin(self.b))

    def test_waiting_promotion_rechecks_target_activation(self):
        self.mb.role = ClanMembership.Role.MEMBER
        self.mb.save(update_fields=['role'])
        def deactivate():
            user = get_user_model().objects.select_for_update(no_key=True).get(pk=self.b.pk)
            user.is_active = False
            user.save(update_fields=['is_active'])
        result = self.compete(deactivate,
            lambda: self.attempt(lambda: manage_member(self.clan.pk, self.a.pk, self.mb.pk, 'promote')))
        self.assertFalse(result)
        self.mb.refresh_from_db()
        self.assertEqual(self.mb.role, ClanMembership.Role.MEMBER)
