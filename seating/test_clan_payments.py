import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from clans.models import ClanMembership
from clans.services import leave_clan, ClanManagementError
from configuration.models import GeneralConfiguration
from emails.defaults import DEFAULT_EMAIL_TEMPLATES
from emails.models import EmailTemplate, OutgoingEmail
from events.models import Event, EventRegistration, TicketType
from events.services import RegistrationService, PaymentService, CheckInService
from events.exceptions import EventFullError
from events.payment_qr import generate_transfer_qr_payload
from users.services import UserService
from . import test_clan_holds as hold_tests
from .models import ClanSeatPayment, ClanSeatPaymentLog, ClanSeatHold, SeatingCell
from .clan_services import ClanSeatError, process_clan_holds, open_holds, update_selection, selection_status
from .clan_payments import payment_preview, create_payment, confirm_payment, assign_member, cancel_payment, reserved_ticket_count
from .services import SeatingPlanService, SeatingPlanValidationError, get_event_capacity_stats


@override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_BASE_URL='https://lan.example.test')
class ClanPaymentTests(TestCase):
    select = hold_tests.ClanHoldTests.select

    def setUp(self):
        hold_tests.ClanHoldTests.setUp(self)
        self.ticket = TicketType.objects.create(event=self.event, name='Clan Standard', price='30.00')
        bank = GeneralConfiguration.load()
        bank.kontoinhaber, bank.iban = 'LAN Orga', 'AT611904300234573201'
        bank.save()
        self.orga = get_user_model().objects.create_user('paymentorga', email='orga@example.test', is_staff=True)
        self.orga.user_permissions.add(Permission.objects.get(codename='manage_clan_payments'))
        for key, defaults in DEFAULT_EMAIL_TEMPLATES.items():
            if key.startswith('clan_payment_'):
                EmailTemplate.objects.get_or_create(key=key, defaults=defaults)

    def create(self, seats=None):
        self.select(self.seats[:2] if seats is None else seats)
        preview = payment_preview(self.clan, self.event)
        return create_payment(self.clan.pk, self.event.pk, self.admin.pk, preview['token'], confirmed=True)

    def pay(self, payment):
        return confirm_payment(payment.pk, self.orga.pk, received_at=timezone.now(), amount=payment.total_amount, confirmed=True)

    def assign(self, payment, user=None, hold=None, **kwargs):
        hold = hold or payment.holds.order_by('pk').first()
        hold.refresh_from_db()
        return assign_member(payment.pk, hold.pk, self.admin.pk, (user or self.member).pk,
            expected_registration_id=hold.funded_registration_id, confirmed=True, **kwargs)

    def test_exact_seats_price_bank_snapshot_and_deadlines(self):
        before = timezone.now()
        payment = self.create(self.seats[:3])
        self.assertEqual((payment.seat_count, payment.total_amount), (3, Decimal('90')))
        self.assertEqual(payment.holds.count(), 3)
        self.assertAlmostEqual((payment.payment_due_at - before).total_seconds(), 7 * 86400, delta=2)
        self.assertEqual(payment.release_at - payment.payment_due_at, timedelta(days=2))
        self.ticket.price = 99
        self.ticket.save()
        bank = GeneralConfiguration.load()
        bank.iban = 'DE89370400440532013000'
        bank.save()
        payment.refresh_from_db()
        self.assertEqual(payment.unit_price, Decimal('30'))
        self.assertEqual(payment.iban, 'AT611904300234573201')
        self.assertEqual(ClanSeatPaymentLog.objects.filter(action='CREATED').count(), 1)

    def test_only_open_seats_billed_and_personal_booking_survives(self):
        self.select(self.seats[:3])
        self.assertTrue(self.seats[0].reserve_for_user(self.reg)[0])
        preview = payment_preview(self.clan, self.event)
        payment = create_payment(self.clan.pk, self.event.pk, self.admin.pk, preview['token'], confirmed=True)
        self.assertEqual(payment.seat_count, 2)
        self.assertFalse(payment.holds.filter(cell=self.seats[0]).exists())
        self.assertTrue(self.seats[0].registration_id)

    def test_creation_needs_confirmation_and_admin(self):
        self.select()
        token = payment_preview(self.clan, self.event)['token']
        with self.assertRaises(ClanSeatError):
            create_payment(self.clan.pk, self.event.pk, self.admin.pk, token)
        with self.assertRaises(ClanSeatError):
            create_payment(self.clan.pk, self.event.pk, self.member.pk, token, confirmed=True)
        self.assertFalse(ClanSeatPayment.objects.exists())

    def test_tampered_stale_duplicate_and_changed_prices(self):
        self.select()
        token = payment_preview(self.clan, self.event)['token']
        with self.assertRaises(ClanSeatError):
            create_payment(self.clan.pk, self.event.pk, self.admin.pk, token+'bad', confirmed=True)
        self.ticket.price = 31
        self.ticket.save()
        with self.assertRaises(ClanSeatError):
            create_payment(self.clan.pk, self.event.pk, self.admin.pk, token, confirmed=True)
        token = payment_preview(self.clan, self.event)['token']
        create_payment(self.clan.pk, self.event.pk, self.admin.pk, token, confirmed=True)
        with self.assertRaises(ClanSeatError):
            create_payment(self.clan.pk, self.event.pk, self.admin.pk, token, confirmed=True)
        self.assertEqual(ClanSeatPayment.objects.count(), 1)

    def test_multiple_categories_need_configuration(self):
        second = TicketType.objects.create(event=self.event, name='VIP', price=50)
        self.select()
        with self.assertRaises(ClanSeatError):
            payment_preview(self.clan, self.event)
        self.config.payment_ticket_type = second
        self.config.save()
        self.assertEqual(payment_preview(self.clan, self.event)['unit_price'], Decimal('50'))

    def test_zero_price_and_foreign_category_rejected(self):
        self.ticket.price = 0
        self.ticket.save()
        self.select()
        with self.assertRaises(ClanSeatError):
            payment_preview(self.clan, self.event)

    def test_shortened_deadline_and_too_short_rejected(self):
        self.config.days = 5
        self.config.save()
        payment = self.create()
        self.assertLessEqual(payment.release_at, payment.allocation.expires_at)
        self.assertEqual(payment.release_at - payment.payment_due_at, timedelta(days=2))
        self.assertAlmostEqual((payment.payment_due_at-payment.created_at).total_seconds(), 3*86400, delta=2)

    def test_no_order_when_only_review_time_remains(self):
        self.config.days = 1
        self.config.save()
        self.select()
        with self.assertRaises(ClanSeatError):
            payment_preview(self.clan, self.event)

    def test_pending_capacity_blocks_regular_registration(self):
        self.event.max_guests = 4
        self.event.save()
        payment = self.create()
        self.assertTrue(self.event.is_full)
        self.assertEqual(reserved_ticket_count(self.event.pk), 2)
        with self.assertRaises(EventFullError):
            RegistrationService.register_user(self.admin, self.event.pk)
        self.assertEqual(get_event_capacity_stats(self.event)['reserved_seats'], 2)

    def test_cannot_purchase_more_than_event_capacity(self):
        self.event.max_guests = 3
        self.event.save()
        self.select()
        with self.assertRaises(ClanSeatError):
            payment_preview(self.clan, self.event)
        self.assertFalse(ClanSeatPayment.objects.exists())

    def test_selection_and_self_claim_locked(self):
        payment = self.create()
        self.assertFalse(selection_status(self.clan, self.event)['enabled'])
        with self.assertRaises(ClanSeatError):
            self.select(self.seats[2:4])
        self.assertFalse(self.seats[0].reserve_for_user(self.reg)[0])
        self.assertEqual(open_holds(self.event.pk).filter(payment=payment).count(), 2)

    def test_only_orga_can_confirm_full_timely_payment_once(self):
        payment = self.create()
        for actor, amount, date in [(self.admin, payment.total_amount, timezone.now()),
                                   (self.orga, Decimal('1'), timezone.now()),
                                   (self.orga, payment.total_amount, payment.payment_due_at+timedelta(seconds=1))]:
            with self.assertRaises(ClanSeatError):
                confirm_payment(payment.pk, actor.pk, received_at=date, amount=amount, confirmed=True)
        self.pay(payment)
        with self.assertRaises(ClanSeatError):
            self.pay(payment)
        self.assertEqual(ClanSeatPaymentLog.objects.filter(action='CONFIRMED').count(), 1)

    def test_existing_unpaid_and_new_user_registered_paid_with_seat(self):
        payment = self.pay(self.create())
        hold = self.assign(payment)
        self.reg.refresh_from_db()
        self.assertEqual((self.reg.payment_status, self.reg.paid_amount), ('PAID', Decimal('30')))
        self.assertEqual(self.reg.paid_at, payment.received_at)
        self.assertEqual(hold.cell.registration_id, self.reg.pk)
        second = payment.holds.exclude(pk=hold.pk).get()
        self.assign(payment, self.admin2, second)
        reg = EventRegistration.objects.get(user=self.admin2, event=self.event)
        self.assertEqual((reg.payment_status, reg.seats.get().pk), ('PAID', second.cell_id))
        self.assertEqual(reserved_ticket_count(self.event.pk), 0)

    def test_prepaid_new_registration_works_at_full_capacity(self):
        self.event.max_guests = 4
        self.event.save()
        payment = self.pay(self.create())
        self.assign(payment, self.admin2)
        self.assertEqual(self.event.active_registrations_count + reserved_ticket_count(self.event.pk), 4)

    def test_reactivate_cancelled_and_restore_on_removal(self):
        PaymentService.mark_cancelled(self.reg)
        payment = self.pay(self.create())
        hold = self.assign(payment)
        assign_member(payment.pk, hold.pk, self.admin.pk, None, expected_registration_id=self.reg.pk, confirmed=True)
        self.reg.refresh_from_db()
        self.assertEqual(self.reg.payment_status, 'CANCELLED')
        self.assertEqual(self.reg.paid_amount, 0)
        self.assertEqual(reserved_ticket_count(self.event.pk), 2)

    def test_paid_member_banned_pending_and_foreign_member_rejected(self):
        payment = self.pay(self.create())
        ClanMembership.objects.create(clan=self.clan, user=self.outsider)
        for user in [self.outsider]:
            with self.assertRaises(ClanSeatError): self.assign(payment, user)
        get_user_model().objects.filter(pk=self.member.pk).update(is_banned=True)
        with self.assertRaises(ClanSeatError): self.assign(payment)
        get_user_model().objects.filter(pk=self.member.pk).update(is_banned=False)
        ClanMembership.objects.filter(user=self.member).update(status='PENDING')
        with self.assertRaises(ClanSeatError): self.assign(payment)
        self.assertFalse(payment.holds.filter(funded_registration__isnull=False).exists())

    def test_ticket_mismatch_rolls_back_replacement(self):
        payment = self.pay(self.create())
        hold = self.assign(payment, self.admin2)
        self.reg.booking_price = 50
        self.reg.save()
        with self.assertRaises(ClanSeatError): self.assign(payment, hold=hold)
        hold.refresh_from_db()
        self.assertEqual(hold.funded_registration.user_id, self.admin2.pk)

    def test_replace_restores_existing_registration_and_removes_old_seat(self):
        self.reg.ticket_type = self.ticket
        self.reg.booking_price = Decimal('30')
        self.reg.save()
        self.seats[4].reserve_for_user(self.reg)
        payment = self.pay(self.create())
        hold = self.assign(payment)
        self.seats[4].refresh_from_db()
        self.assertIsNone(self.seats[4].registration_id)
        self.assign(payment, self.admin2, hold)
        self.reg.refresh_from_db()
        self.assertEqual((self.reg.payment_status, self.reg.ticket_type_id, self.reg.booking_price), ('UNPAID', self.ticket.pk, Decimal('30')))
        self.assertEqual(self.reg.paid_amount, 0)
        self.assertFalse(self.reg.seats.exists())

    def test_new_clan_registration_cancelled_when_replaced(self):
        payment = self.pay(self.create())
        hold = self.assign(payment, self.admin2)
        previous = hold.funded_registration
        self.assign(payment, self.admin, hold)
        previous.refresh_from_db()
        self.assertEqual(previous.payment_status, 'CANCELLED')
        self.assertFalse(previous.seats.exists())

    def test_checked_in_requires_orga_reason(self):
        payment = self.pay(self.create())
        hold = self.assign(payment)
        EventRegistration.objects.filter(pk=self.reg.pk).update(is_checked_in=True)
        with self.assertRaises(ClanSeatError): self.assign(payment, self.admin2, hold)
        with self.assertRaises(ClanSeatError):
            assign_member(payment.pk, hold.pk, self.orga.pk, self.admin2.pk, expected_registration_id=self.reg.pk, confirmed=True)
        assign_member(payment.pk, hold.pk, self.orga.pk, self.admin2.pk, expected_registration_id=self.reg.pk, confirmed=True, reason='Orga-Korrektur')
        self.reg.refresh_from_db()
        self.assertFalse(self.reg.is_checked_in)
        self.assertTrue(payment.logs.filter(reason='Orga-Korrektur').exists())

    def test_stale_assignment_rejected(self):
        payment = self.pay(self.create())
        hold = self.assign(payment)
        with self.assertRaises(ClanSeatError):
            assign_member(payment.pk, hold.pk, self.admin.pk, self.admin2.pk, expected_registration_id=None, confirmed=True)

    def test_guest_move_release_and_personal_payment_cannot_bypass_funding(self):
        payment = self.pay(self.create())
        hold = self.assign(payment)
        self.client.force_login(self.member)
        for name, data in [('api_reserve_seat', {'x': 5, 'y': 1}), ('api_release_seat', {})]:
            response = self.client.post(reverse(name, args=[self.event.pk]), json.dumps(data), content_type='application/json')
            self.assertEqual(response.status_code, 400)
        with self.assertRaises(ValidationError): PaymentService.mark_paid(self.reg)
        hold.refresh_from_db()
        self.assertEqual(hold.funded_registration_id, self.reg.pk)

    def test_payment_cancelled_ticket_returns_paid_slot(self):
        payment = self.pay(self.create())
        hold = self.assign(payment)
        PaymentService.mark_cancelled(self.reg)
        hold.refresh_from_db()
        self.assertIsNone(hold.funded_registration_id)
        self.assertEqual(hold.payment.status, 'PAID')
        self.assertTrue(open_holds(self.event.pk).filter(pk=hold.pk).exists())

    def test_expiry_effective_without_worker_and_persisted_once(self):
        payment = self.create()
        later = payment.release_at + timedelta(seconds=1)
        with patch('django.utils.timezone.now', return_value=later):
            self.assertEqual(reserved_ticket_count(self.event.pk), 0)
            self.assertFalse(open_holds(self.event.pk).filter(payment=payment).exists())
            process_clan_holds()
            process_clan_holds()
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'CANCELLED')
        self.assertFalse(payment.holds.filter(protection_active=True).exists())
        self.assertEqual(payment.logs.filter(action='CANCELLED').count(), 1)

    def test_pending_survives_configuration_disable_until_fixed_deadline(self):
        payment = self.create()
        self.config.enabled = False
        self.config.save()
        process_clan_holds()
        self.assertEqual(open_holds(self.event.pk).filter(payment=payment).count(), 2)

    def test_paid_survives_hold_expiry_disable_and_quota_zero(self):
        payment = self.pay(self.create())
        self.config.enabled = False
        self.config.save()
        self.clan.seat_limit_override = 0
        self.clan.save()
        later = payment.allocation.expires_at + timedelta(seconds=1)
        with patch('django.utils.timezone.now', return_value=later):
            process_clan_holds()
            self.assertEqual(open_holds(self.event.pk).filter(payment=payment).count(), 2)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'PAID')

    def test_paid_ticket_category_can_change_price_or_be_deactivated(self):
        payment = self.pay(self.create())
        self.ticket.price, self.ticket.is_active = 60, False
        self.ticket.save()
        hold = self.assign(payment, self.admin2)
        self.assertEqual(hold.funded_registration.booking_price, Decimal('30'))

    def test_admin_cancel_needs_reason_and_retains_history(self):
        payment = self.create()
        with self.assertRaises(ClanSeatError): cancel_payment(payment.pk, self.orga.pk, reason='', confirmed=True)
        cancel_payment(payment.pk, self.orga.pk, reason='Fehlbuchung', confirmed=True)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'CANCELLED')
        self.assertEqual(payment.holds.count(), payment.seat_count)
        with self.assertRaises(ProtectedError): self.clan.delete()

    def test_event_closure_cancels_pending_but_keeps_paid_history(self):
        payment = self.create()
        self.event.is_active = False
        self.event.save()
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'CANCELLED')

    def test_sitplan_editor_and_clean_protect_paid_seats(self):
        payment = self.pay(self.create())
        self.seats[0].seat_label = 'Changed'
        with self.assertRaises(ValidationError): self.seats[0].full_clean()
        with self.assertRaises(SeatingPlanValidationError):
            SeatingPlanService.save_grid(self.plan, [])

    def test_immutable_payment_admin_and_csrf(self):
        payment = self.create()
        self.client.force_login(self.orga)
        response = self.client.get(reverse('admin:seating_clanseatpayment_manage', args=[payment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, payment.reference)
        self.client.force_login(self.admin)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.admin)
        response = secure.post(reverse('clan_payment_create', args=[self.clan.slug]), {})
        self.assertEqual(response.status_code, 403)

    def test_private_preview_and_qr_bank_data_exact(self):
        payment = self.create()
        url = reverse('clan_payment_detail', args=[self.clan.slug])
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), payment.reference)
        qr = self.client.get(reverse('clan_payment_qr', args=[payment.pk]))
        self.assertEqual(qr['Content-Type'], 'image/png')
        lines = generate_transfer_qr_payload(payment.beneficiary_name, payment.iban, payment.bic, payment.total_amount, payment.reference).splitlines()
        self.assertEqual((lines[7], lines[10]), ('EUR60.00', payment.reference))

    def test_frontend_api_distinguishes_pending_paid_and_no_self_claim(self):
        payment = self.create()
        url = reverse('api_event_seating', args=[self.event.pk])
        for expected in ['CLAN_PAYMENT_PENDING', 'CLAN_PAID']:
            data = self.client.get(url).json()
            seat = next(c for c in data['cells'] if c['id'] == self.seats[0].pk)
            self.assertEqual(seat['status'], expected)
            self.assertFalse(seat['can_claim_hold'])
            self.assertNotIn(payment.iban, json.dumps(data))
            if expected == 'CLAN_PAYMENT_PENDING': self.pay(payment)

    def test_pending_order_requires_payment_before_assignment(self):
        payment = self.create()
        with self.assertRaises(ClanSeatError): self.assign(payment)

    def test_order_and_reminder_outbox_once_per_admin(self):
        payment = self.create()
        self.assertEqual(OutgoingEmail.objects.filter(template_key='clan_payment_created').count(), 2)
        for email in OutgoingEmail.objects.filter(template_key='clan_payment_created'):
            self.assertIn(f'?event={self.event.pk}', email.body_html)
        with patch('django.utils.timezone.now', return_value=payment.payment_due_at-timedelta(hours=12)):
            process_clan_holds()
            process_clan_holds()
        self.assertEqual(OutgoingEmail.objects.filter(template_key='clan_payment_reminder').count(), 2)
        self.assertEqual(OutgoingEmail.objects.filter(template_key='clan_seat_reminder').count(), 0)

    def test_last_member_cannot_dissolve_clan_or_delete_account(self):
        payment = self.create()
        self.clan.memberships.exclude(user=self.admin).delete()
        with self.assertRaises(ClanManagementError): leave_clan(self.clan.pk, self.admin.pk)
        self.assertTrue(any(code == 'clan_payment' for code, _ in UserService.deletion_blockers(self.admin)))

    def test_existing_registration_removal_cannot_overbook_event(self):
        self.event.max_guests = 4
        self.event.save()
        payment = self.pay(self.create())
        hold = self.assign(payment)
        RegistrationService.register_user(self.admin2, self.event.pk)
        with self.assertRaises(ClanSeatError):
            assign_member(payment.pk, hold.pk, self.admin.pk, None, expected_registration_id=self.reg.pk, confirmed=True)
        self.reg.refresh_from_db()
        hold.refresh_from_db()
        self.assertEqual((self.reg.payment_status, hold.funded_registration_id), ('PAID', self.reg.pk))
        self.assertEqual(self.reg.seats.get().pk, hold.cell_id)

    def test_arrival_before_deadline_can_be_confirmed_during_review(self):
        payment = self.create()
        with patch('django.utils.timezone.now', return_value=payment.payment_due_at+timedelta(days=1)):
            confirm_payment(payment.pk, self.orga.pk, received_at=payment.payment_due_at-timedelta(hours=1),
                amount=payment.total_amount, confirmed=True)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'PAID')

    def test_expired_order_does_not_block_another_clan_hold_before_worker(self):
        from clans.models import Clan
        payment = self.create()
        other = Clan.objects.create(name='Next Clan')
        ClanMembership.objects.create(clan=other, user=self.outsider, role='ADMIN')
        with patch('django.utils.timezone.now', return_value=payment.release_at+timedelta(seconds=1)):
            update_selection(other.pk, self.outsider.pk, self.event.pk, [self.seats[0].pk])
        self.assertTrue(ClanSeatHold.objects.filter(cell=self.seats[0], allocation__clan=other, protection_active=True).exists())

    def test_admin_force_routes_cannot_release_or_overwrite_paid_clan_seat(self):
        payment = self.pay(self.create())
        self.orga.user_permissions.add(Permission.objects.get(codename='change_seatingcell'))
        self.client.force_login(self.orga)
        for name, data in [
            ('admin_toggle_block_seat', {'event_id': self.event.pk, 'x': 1, 'y': 1}),
            ('admin_release_seat', {'event_id': self.event.pk, 'x': 1, 'y': 1}),
            ('admin_assign_seat', {'registration_id': self.reg.pk, 'x': 1, 'y': 1, 'force': True})]:
            self.assertEqual(self.client.post(reverse(name), json.dumps(data), content_type='application/json').status_code, 400)
        self.assertEqual(open_holds(self.event.pk).filter(payment=payment).count(), 2)

    def test_paid_history_remains_after_event_closure(self):
        payment = self.pay(self.create())
        hold = self.assign(payment)
        self.event.is_active = False
        self.event.save()
        process_clan_holds()
        payment.refresh_from_db()
        hold.refresh_from_db()
        self.assertEqual((payment.status, hold.funded_registration_id), ('PAID', self.reg.pk))
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('clan_payment_detail', args=[self.clan.slug])), payment.reference)

    def test_paid_entitlement_can_be_assigned_during_running_event(self):
        payment = self.pay(self.create())
        self.event.start_date = timezone.now()-timedelta(hours=1)
        self.event.status = 'RUNNING'
        self.event.save()
        self.assign(payment, self.admin2)
        self.assertEqual(EventRegistration.objects.get(user=self.admin2, event=self.event).payment_status, 'PAID')

    def test_calendar_day_deadlines_keep_vienna_wall_time_across_dst(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        date = datetime(2026, 10, 24, 12, 0, tzinfo=ZoneInfo('Europe/Vienna'))
        with patch('django.utils.timezone.now', return_value=date):
            payment = self.create()
        self.assertEqual(timezone.localtime(payment.payment_due_at).hour, 12)
        self.assertEqual(timezone.localtime(payment.payment_due_at).day, 31)
        self.assertEqual(timezone.localtime(payment.release_at).day, 2)

    def test_changed_bank_data_invalidates_preview(self):
        self.select()
        token = payment_preview(self.clan, self.event)['token']
        bank = GeneralConfiguration.load()
        bank.iban = 'DE89370400440532013000'
        bank.save()
        with self.assertRaises(ClanSeatError):
            create_payment(self.clan.pk, self.event.pk, self.admin.pk, token, confirmed=True)
