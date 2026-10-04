from django.test import TransactionTestCase, skipUnlessDBFeature, override_settings

from clans.models import Clan, ClanMembership
from clans.services import manage_member
from events.models import Event
from tournaments import test_audit_concurrency as audit_tests
from . import test_clan_holds as hold_tests
from .clan_services import ClanSeatError, update_selection, selection_status
from .models import ClanSeatHold


@skipUnlessDBFeature('has_select_for_update')
@override_settings(SECURE_SSL_REDIRECT=False)
class ClanHoldConcurrencyTests(TransactionTestCase):
    setUp = hold_tests.ClanHoldTests.setUp
    select = hold_tests.ClanHoldTests.select
    compete = audit_tests.TournamentAuditConcurrencyTests.compete
    separate_connection = staticmethod(audit_tests.TournamentAuditConcurrencyTests.separate_connection)

    @staticmethod
    def attempt(action):
        try:
            return action()
        except ClanSeatError:
            return False

    def test_two_clans_cannot_hold_same_seat(self):
        clan_b = Clan.objects.create(name='Concurrent B')
        ClanMembership.objects.create(clan=clan_b, user=self.outsider, role='ADMIN')
        result = self.compete(lambda: self.select([self.seats[0]]), lambda: self.attempt(
            lambda: update_selection(clan_b.pk, self.outsider.pk, self.event.pk, [self.seats[0].pk])))
        self.assertFalse(result)
        self.assertEqual(ClanSeatHold.objects.filter(protection_active=True).count(), 1)

    def test_waiting_guest_cannot_book_new_clan_hold(self):
        result = self.compete(lambda: self.select([self.seats[0]]),
            lambda: self.seats[0].reserve_for_user(self.other_reg))
        self.assertFalse(result[0])

    def test_waiting_hold_cannot_take_booked_seat(self):
        result = self.compete(lambda: self.seats[0].reserve_for_user(self.other_reg),
            lambda: self.attempt(lambda: self.select([self.seats[0]])))
        self.assertFalse(result)
        self.assertFalse(ClanSeatHold.objects.exists())

    def test_waiting_selection_rechecks_demoted_admin(self):
        membership = ClanMembership.objects.get(clan=self.clan, user=self.admin)
        result = self.compete(lambda: manage_member(self.clan.pk, self.admin2.pk, membership.pk, 'demote'),
            lambda: self.attempt(self.select))
        self.assertFalse(result)

    def test_waiting_booking_rechecks_clan_removal(self):
        self.select()
        membership = ClanMembership.objects.get(clan=self.clan, user=self.member)
        result = self.compete(lambda: manage_member(self.clan.pk, self.admin.pk, membership.pk, 'kick'),
            lambda: self.seats[0].reserve_for_user(self.reg))
        self.assertFalse(result[0])

    def test_parallel_admin_selections_detect_stale_snapshot(self):
        revision = selection_status(self.clan, self.event)['revision']
        result = self.compete(lambda: self.select([self.seats[0]], expected_revision=revision),
            lambda: self.attempt(lambda: self.select([self.seats[1]], expected_revision=revision)))
        self.assertFalse(result)
        self.assertEqual(selection_status(self.clan, self.event)['selected'], [self.seats[0].pk])

    def test_waiting_selection_rechecks_disabled_configuration(self):
        def disable():
            self.config.enabled = False
            self.config.save()
        result = self.compete(disable, lambda: self.attempt(self.select))
        self.assertFalse(result)

    def test_event_finish_blocks_waiting_selection(self):
        def finish():
            event = Event.objects.select_for_update().get(pk=self.event.pk)
            event.status = 'FINISHED'
            event.is_active = False
            event.save()
        result = self.compete(finish, lambda: self.attempt(self.select))
        self.assertFalse(result)
