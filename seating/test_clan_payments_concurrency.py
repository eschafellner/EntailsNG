"""Real PostgreSQL row-lock checks for clan purchases and ticket coverage."""
from django.test import TransactionTestCase, skipUnlessDBFeature, override_settings
from django.db import transaction
from django.utils import timezone

from clans.models import ClanMembership
from events.models import Event, EventRegistration
from events.services import RegistrationService, PaymentService
from events.exceptions import RegistrationError
from tournaments import test_audit_concurrency as concurrency
from . import test_clan_payments as payment_tests
from .models import ClanSeatPayment, ClanSeatHold
from .clan_services import ClanSeatError
from .clan_payments import create_payment, payment_preview, assign_member, confirm_payment, cancel_payment, reserved_ticket_count


@skipUnlessDBFeature('has_select_for_update')
@override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_BASE_URL='https://lan.example.test')
class ClanPaymentConcurrencyTests(TransactionTestCase):
    setUp = payment_tests.ClanPaymentTests.setUp
    select = payment_tests.ClanPaymentTests.select
    create = payment_tests.ClanPaymentTests.create
    pay = payment_tests.ClanPaymentTests.pay
    assign = payment_tests.ClanPaymentTests.assign
    compete = concurrency.TournamentAuditConcurrencyTests.compete
    separate_connection = staticmethod(concurrency.TournamentAuditConcurrencyTests.separate_connection)

    @staticmethod
    def attempt(action):
        try:
            return action()
        except (ClanSeatError, RegistrationError):
            return False

    def test_two_admins_create_only_one_order(self):
        self.select()
        token = payment_preview(self.clan, self.event)['token']
        result = self.compete(
            lambda: create_payment(self.clan.pk, self.event.pk, self.admin.pk, token, confirmed=True),
            lambda: self.attempt(lambda: create_payment(self.clan.pk, self.event.pk, self.admin2.pk, token, confirmed=True)))
        self.assertFalse(result)
        self.assertEqual(ClanSeatPayment.objects.count(), 1)
        self.assertEqual(ClanSeatHold.objects.filter(payment__isnull=False).count(), 2)

    def test_purchase_blocks_waiting_personal_claim(self):
        self.select()
        token = payment_preview(self.clan, self.event)['token']
        result = self.compete(
            lambda: create_payment(self.clan.pk, self.event.pk, self.admin.pk, token, confirmed=True),
            lambda: self.seats[0].reserve_for_user(self.reg))
        self.assertFalse(result[0])

    def test_claim_invalidates_waiting_payment_preview(self):
        self.select()
        token = payment_preview(self.clan, self.event)['token']
        result = self.compete(lambda: self.seats[0].reserve_for_user(self.reg),
            lambda: self.attempt(lambda: create_payment(self.clan.pk, self.event.pk, self.admin.pk, token, confirmed=True)))
        self.assertFalse(result)
        self.assertFalse(ClanSeatPayment.objects.exists())

    def test_purchase_reserves_capacity_before_waiting_registration(self):
        self.event.max_guests = 4
        self.event.save()
        self.select()
        token = payment_preview(self.clan, self.event)['token']
        result = self.compete(
            lambda: create_payment(self.clan.pk, self.event.pk, self.admin.pk, token, confirmed=True),
            lambda: self.attempt(lambda: RegistrationService.register_user(self.admin2, self.event.pk)))
        self.assertFalse(result)
        self.assertEqual(self.event.active_registrations_count + reserved_ticket_count(self.event.pk), 4)

    def test_two_assignments_do_not_overwrite_the_first(self):
        payment = self.pay(self.create())
        hold = payment.holds.order_by('pk').first()
        result = self.compete(
            lambda: assign_member(payment.pk, hold.pk, self.admin.pk, self.member.pk, expected_registration_id=None, confirmed=True),
            lambda: self.attempt(lambda: assign_member(payment.pk, hold.pk, self.admin2.pk, self.admin2.pk, expected_registration_id=None, confirmed=True)))
        self.assertFalse(result)
        hold.refresh_from_db()
        self.assertEqual(hold.funded_registration_id, self.reg.pk)

    def test_personal_payment_prevents_waiting_clan_assignment(self):
        payment = self.pay(self.create())
        result = self.compete(lambda: PaymentService.mark_paid(self.reg, send_email=False),
            lambda: self.attempt(lambda: self.assign(payment)))
        self.assertFalse(result)
        self.reg.refresh_from_db()
        self.assertEqual(self.reg.payment_status, 'PAID')
        self.assertFalse(payment.holds.filter(funded_registration=self.reg).exists())

    def test_checkin_prevents_waiting_clan_replacement(self):
        payment = self.pay(self.create())
        hold = self.assign(payment)
        def checkin():
            reg = EventRegistration.objects.select_for_update().get(pk=self.reg.pk)
            reg.is_checked_in = True
            reg.save(update_fields=['is_checked_in'])
        result = self.compete(checkin, lambda: self.attempt(lambda: self.assign(payment, self.admin2, hold)))
        self.assertFalse(result)
        hold.refresh_from_db()
        self.assertEqual(hold.funded_registration_id, self.reg.pk)

    def test_demoted_admin_cannot_apply_waiting_assignment(self):
        from clans.services import manage_member
        payment = self.pay(self.create())
        membership = ClanMembership.objects.get(clan=self.clan, user=self.admin)
        result = self.compete(lambda: manage_member(self.clan.pk, self.admin2.pk, membership.pk, 'demote'),
            lambda: self.attempt(lambda: self.assign(payment)))
        self.assertFalse(result)

    def test_cancellation_prevents_waiting_confirmation(self):
        payment = self.create()
        result = self.compete(lambda: cancel_payment(payment.pk, self.orga.pk, reason='Orga-Storno', confirmed=True),
            lambda: self.attempt(lambda: confirm_payment(payment.pk, self.orga.pk, received_at=timezone.now(), amount=payment.total_amount, confirmed=True)))
        self.assertFalse(result)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'CANCELLED')
