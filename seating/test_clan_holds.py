import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from clans.models import Clan, ClanMembership
from configuration.models import ClanSeatConfiguration
from emails.defaults import DEFAULT_EMAIL_TEMPLATES
from emails.models import EmailTemplate, OutgoingEmail
from events.models import Event, EventRegistration
from .models import SeatingPlan, SeatingCell, ClanSeatAllocation, ClanSeatHold
from .services import SeatingPlanService, SeatingPlanValidationError
from .clan_services import update_selection, process_clan_holds, ClanSeatError, selection_status
from .clan_admin_forms import ClanQuotaForm, ClanSeatConfigurationForm


@override_settings(SECURE_SSL_REDIRECT=False, PUBLIC_BASE_URL='https://lan.example.test')
class ClanHoldTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.config = ClanSeatConfiguration.load()
        self.config.enabled = True
        self.config.duration = 'DAYS'
        self.config.days = 14
        self.config.save()
        self.event = Event.objects.create(title='Clan LAN', slug='clan-lan', is_active=True,
            status='OPEN', start_date=self.now + timedelta(days=60), end_date=self.now + timedelta(days=63))
        self.plan = SeatingPlan.objects.create(event=self.event, name='Hall', columns=12, rows=2)
        self.seats = [SeatingCell.objects.create(plan=self.plan, x=i, y=1,
            cell_type='SEAT', seat_label=f'A{i}') for i in range(1, 13)]
        self.admin = get_user_model().objects.create_user('clanadmin', email='a@example.test')
        self.admin2 = get_user_model().objects.create_user('clanadmin2', email='b@example.test')
        self.member = get_user_model().objects.create_user('member', email='m@example.test')
        self.outsider = get_user_model().objects.create_user('outsider', email='o@example.test')
        self.clan = Clan.objects.create(name='Test Clan', tag='TC')
        for user, role in [(self.admin, 'ADMIN'), (self.admin2, 'ADMIN'), (self.member, 'MEMBER')]:
            ClanMembership.objects.create(clan=self.clan, user=user, role=role)
        self.reg = EventRegistration.objects.create(user=self.member, event=self.event)
        self.other_reg = EventRegistration.objects.create(user=self.outsider, event=self.event, payment_status='PAID')
        for key in ('clan_seat_reminder', 'clan_seat_expired'):
            EmailTemplate.objects.get_or_create(key=key, defaults=DEFAULT_EMAIL_TEMPLATES[key])

    def select(self, seats=None, **kwargs):
        return update_selection(self.clan.pk, self.admin.pk, self.event.pk,
            [s.pk for s in (self.seats[:2] if seats is None else seats)], **kwargs)

    def test_default_eight_and_global_override(self):
        self.assertEqual(self.select()['limit'], 8)
        self.config.default_limit = 10
        self.config.save()
        self.assertEqual(selection_status(self.clan, self.event)['limit'], 10)
        self.clan.seat_limit_override = 3
        self.clan.save()
        self.assertEqual(selection_status(self.clan, self.event)['limit'], 3)

    def test_separate_clan_clocks(self):
        with patch('seating.clan_services.timezone.now', return_value=self.now):
            self.select()
        clan_b = Clan.objects.create(name='Clan B')
        ClanMembership.objects.create(clan=clan_b, user=self.outsider, role='ADMIN')
        later = self.now + timedelta(days=3)
        with patch('seating.clan_services.timezone.now', return_value=later):
            update_selection(clan_b.pk, self.outsider.pk, self.event.pk, [self.seats[3].pk])
        a = ClanSeatAllocation.objects.get(clan=self.clan)
        b = ClanSeatAllocation.objects.get(clan=clan_b)
        self.assertEqual(a.expires_at, self.now + timedelta(days=14))
        self.assertEqual(b.expires_at - a.expires_at, timedelta(days=3))

    def test_edits_and_empty_selection_do_not_reset_clock(self):
        self.select([])
        self.assertFalse(ClanSeatAllocation.objects.exists())
        self.select()
        expires = ClanSeatAllocation.objects.get().expires_at
        self.select([])
        self.select(self.seats[3:5])
        self.assertEqual(ClanSeatAllocation.objects.get().expires_at, expires)

    def test_zero_and_disabled_cannot_hold(self):
        self.clan.seat_limit_override = 0
        self.clan.save()
        with self.assertRaises(ClanSeatError): self.select()
        self.clan.seat_limit_override = None
        self.clan.save()
        self.config.enabled = False
        self.config.save()
        with self.assertRaises(ClanSeatError): self.select()

    def test_member_and_inactive_admin_cannot_select(self):
        with self.assertRaises(ClanSeatError):
            update_selection(self.clan.pk, self.member.pk, self.event.pk, [self.seats[0].pk])
        self.admin.is_active = False
        self.admin.save()
        with self.assertRaises(ClanSeatError): self.select()

    def test_pending_admin_cannot_select(self):
        ClanMembership.objects.filter(user=self.admin).update(status='PENDING')
        with self.assertRaises(ClanSeatError): self.select()

    def test_limit_atomic_conflict_and_duplicates(self):
        with self.assertRaises(ClanSeatError): self.select(self.seats[:9])
        self.assertFalse(ClanSeatAllocation.objects.exists())
        self.seats[1].reserve_for_user(self.other_reg)
        with self.assertRaises(ClanSeatError): self.select()
        self.assertFalse(ClanSeatHold.objects.exists())
        for values in ([self.seats[0].pk] * 2, [True], ['1'], None, [-1]):
            with self.assertRaises(ClanSeatError):
                update_selection(self.clan.pk, self.admin.pk, self.event.pk, values)

    def test_other_clan_and_nonseat_conflicts(self):
        self.select()
        clan_b = Clan.objects.create(name='Other')
        ClanMembership.objects.create(clan=clan_b, user=self.outsider, role='ADMIN')
        with self.assertRaises(ClanSeatError):
            update_selection(clan_b.pk, self.outsider.pk, self.event.pk, [self.seats[0].pk])
        self.seats[4].cell_type = 'WALL'
        self.seats[4].save()
        with self.assertRaises(ClanSeatError): self.select([self.seats[4]])

    def test_foreign_event_seat_cannot_be_selected(self):
        plan = SeatingPlan.objects.create(name='Template')
        seat = SeatingCell.objects.create(plan=plan, x=1, y=1, cell_type='SEAT')
        with self.assertRaises(ClanSeatError): self.select([seat])

    def test_member_claim_and_contingent_no_refill(self):
        self.config.default_limit = 2
        self.config.save()
        self.select()
        self.assertTrue(self.seats[0].reserve_for_user(self.reg)[0])
        status = selection_status(self.clan, self.event)
        self.assertEqual(status['claimed'], 1)
        with self.assertRaises(ClanSeatError): self.select(self.seats[1:3])
        self.assertEqual(ClanSeatHold.objects.filter(state='CLAIMED').count(), 1)

    def test_outsider_paid_blocked_direct_and_api(self):
        self.select()
        self.assertFalse(self.seats[0].reserve_for_user(self.other_reg)[0])
        self.client.force_login(self.outsider)
        response = self.client.post(reverse('api_reserve_seat', args=[self.event.pk]),
            json.dumps({'x': 1, 'y': 1}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.seats[0].refresh_from_db()
        self.assertIsNone(self.seats[0].registration_id)

    def test_paid_outsider_cannot_overwrite_unpaid_clan_claim(self):
        self.select()
        self.seats[0].reserve_for_user(self.reg)
        self.assertFalse(self.seats[0].reserve_for_user(self.other_reg)[0])

    def test_release_and_cancellation_restore_hold_with_original_deadline(self):
        self.select()
        deadline = ClanSeatAllocation.objects.get().expires_at
        self.seats[0].reserve_for_user(self.reg)
        self.reg.mark_as_cancelled()
        self.assertIn(self.seats[0].pk, selection_status(self.clan, self.event)['selected'])
        self.assertFalse(self.seats[0].reserve_for_user(self.other_reg)[0])
        self.assertEqual(ClanSeatAllocation.objects.get().expires_at, deadline)

    def test_claimed_released_slot_does_not_refund_consumed_quota(self):
        self.config.default_limit = 2
        self.config.save()
        self.select()
        self.seats[0].reserve_for_user(self.reg)
        self.seats[0].release_seat(registration=self.reg)
        with self.assertRaises(ClanSeatError): self.select(self.seats[1:3])

    def test_api_public_logo_tooltip_metadata_and_privacy(self):
        self.select()
        self.clan.logo = 'clan_logos/test.png'
        self.clan.save()
        data = self.client.get(reverse('api_event_seating', args=[self.event.pk])).json()
        seat = data['cells'][0]
        self.assertEqual(seat['status'], 'CLAN_HELD')
        self.assertEqual(seat['hold_clan_name'], self.clan.name)
        self.assertTrue(seat['hold_clan_logo'].endswith('test.png'))
        self.assertIsNone(seat['occupied_by'])
        self.assertFalse(seat['can_claim_hold'])
        self.client.force_login(self.member)
        self.assertTrue(self.client.get(reverse('api_event_seating', args=[self.event.pk])).json()['cells'][0]['can_claim_hold'])

    def test_selection_page_button_and_api(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('clan_detail', args=[self.clan.slug])), 'Sitzplätze für Clan vormerken')
        self.assertContains(self.client.get(reverse('clan_seat_selection', args=[self.clan.slug])), 'clan-seat-confirm')
        response = self.client.post(reverse('clan_seat_update', args=[self.clan.slug]),
            json.dumps({'event_id': self.event.pk, 'cell_ids': [self.seats[0].pk], 'revision': selection_status(self.clan, self.event)['revision']}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse('clan_seat_selection', args=[self.clan.slug])).status_code, 403)
        self.assertEqual(self.client.get(reverse('api_event_seating', args=[self.event.pk]), {'clan': self.clan.pk}).status_code, 403)

    def test_csrf_and_get_do_not_mutate(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        url = reverse('clan_seat_update', args=[self.clan.slug])
        self.assertEqual(client.get(url).status_code, 405)
        self.assertEqual(client.post(url, '{}', content_type='application/json').status_code, 403)
        self.assertFalse(ClanSeatHold.objects.exists())

    def test_expiry_is_immediate_without_worker_then_notifies_once(self):
        self.select()
        self.seats[0].reserve_for_user(self.reg)
        deadline = ClanSeatAllocation.objects.get().expires_at
        with patch('seating.clan_services.timezone.now', return_value=deadline):
            data = self.client.get(reverse('api_event_seating', args=[self.event.pk])).json()
            self.assertEqual(data['cells'][1]['status'], 'FREE')
            process_clan_holds()
            process_clan_holds()
        self.seats[0].refresh_from_db()
        self.assertEqual(self.seats[0].registration_id, self.reg.pk)
        mails = OutgoingEmail.objects.filter(template_key='clan_seat_expired')
        self.assertEqual(mails.count(), 2)
        self.assertIn('A2', mails.first().body_text)
        self.assertNotIn('A1', mails.first().body_text)

    def test_all_claimed_no_reminder_or_expiry_mail(self):
        self.select([self.seats[0]])
        self.seats[0].reserve_for_user(self.reg)
        deadline = ClanSeatAllocation.objects.get().expires_at
        with patch('seating.clan_services.timezone.now', return_value=deadline - timedelta(days=7)):
            process_clan_holds()
        with patch('seating.clan_services.timezone.now', return_value=deadline):
            process_clan_holds()
        self.assertFalse(OutgoingEmail.objects.exists())

    def test_reminder_seven_days_before_current_admins_only(self):
        self.select()
        self.admin2.is_active = False
        self.admin2.save()
        deadline = ClanSeatAllocation.objects.get().expires_at
        with patch('seating.clan_services.timezone.now', return_value=deadline - timedelta(days=7, seconds=1)):
            process_clan_holds()
        self.assertFalse(OutgoingEmail.objects.exists())
        with patch('seating.clan_services.timezone.now', return_value=deadline - timedelta(days=7)):
            process_clan_holds()
            process_clan_holds()
        mail = OutgoingEmail.objects.get()
        self.assertEqual(mail.recipient_email, self.admin.email)
        self.assertEqual(mail.expires_at, deadline)
        self.assertIn('https://lan.example.test/seating/clan/', mail.body_html)

    def test_short_duration_reminds_immediately(self):
        self.config.days = 3
        self.config.save()
        self.select()
        self.assertEqual(OutgoingEmail.objects.filter(template_key='clan_seat_reminder').count(), 2)

    def test_missed_reminder_after_deadline_only_sends_expiry(self):
        self.select()
        deadline = ClanSeatAllocation.objects.get().expires_at
        with patch('seating.clan_services.timezone.now', return_value=deadline + timedelta(days=1)):
            process_clan_holds()
        self.assertEqual(OutgoingEmail.objects.filter(template_key='clan_seat_reminder').count(), 0)
        self.assertEqual(OutgoingEmail.objects.filter(template_key='clan_seat_expired').count(), 2)

    def test_fixed_and_event_modes(self):
        self.config.duration = 'FIXED'
        self.config.deadline = self.now + timedelta(days=10)
        self.config.save()
        self.select()
        self.assertEqual(ClanSeatAllocation.objects.get().expires_at, self.config.deadline)

    def test_event_mode_follows_event_end_and_closes_on_deactivation(self):
        self.config.duration = 'EVENT'
        self.config.save()
        self.select()
        self.event.end_date += timedelta(days=1)
        self.event.save()
        self.assertEqual(selection_status(self.clan, self.event)['expires_at'], self.event.end_date.isoformat())
        process_clan_holds()
        self.assertEqual(ClanSeatAllocation.objects.get().expires_at, self.event.end_date)
        self.event.is_active = False
        self.event.save()
        self.assertIsNotNone(ClanSeatAllocation.objects.get().expired_at)
        self.assertEqual(OutgoingEmail.objects.filter(template_key='clan_seat_expired').count(), 2)

    def test_expired_allocation_cannot_restart(self):
        self.select()
        deadline = ClanSeatAllocation.objects.get().expires_at
        with patch('seating.clan_services.timezone.now', return_value=deadline):
            with self.assertRaises(ClanSeatError): self.select(self.seats[3:5])

    def test_no_hold_past_event_end(self):
        self.event.end_date = self.now - timedelta(seconds=1)
        self.event.start_date = self.now - timedelta(days=1)
        self.event.save()
        with self.assertRaises(ClanSeatError): self.select()

    def test_config_validation(self):
        self.config.days = 0
        with self.assertRaises(ValidationError): self.config.full_clean()
        self.config.duration = 'FIXED'
        self.config.deadline = None
        with self.assertRaises(ValidationError): self.config.full_clean()

    def test_disable_and_zero_release_immediately_without_reviving(self):
        self.select()
        self.seats[0].reserve_for_user(self.reg)
        self.config.enabled = False
        self.config.save()
        self.config.enabled = True
        self.config.save()
        self.assertEqual(selection_status(self.clan, self.event)['selected'], [])
        self.seats[0].refresh_from_db()
        self.assertEqual(self.seats[0].registration_id, self.reg.pk)
        self.select([self.seats[2]])
        self.clan.seat_limit_override = 0
        self.clan.save()
        self.clan.seat_limit_override = None
        self.clan.save()
        self.assertEqual(selection_status(self.clan, self.event)['selected'], [])

    def test_reduction_requires_selection_and_confirmation(self):
        self.select()
        hold = ClanSeatHold.objects.filter(cell=self.seats[0]).get()
        data = {'name': self.clan.name, 'slug': self.clan.slug, 'tag': 'TC', 'password': 'quota-test', 'seat_limit_override': 1}
        form = ClanQuotaForm(data=data, instance=self.clan)
        self.assertFalse(form.is_valid())
        data['release_seats'] = [str(hold.pk)]
        self.assertFalse(ClanQuotaForm(data=data, instance=self.clan).is_valid())
        data['confirm_release'] = 'on'
        form = ClanQuotaForm(data=data, instance=self.clan)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        form.apply_releases()
        self.assertEqual(selection_status(self.clan, self.event)['selected'], [self.seats[1].pk])

    def test_global_reduction_respects_override(self):
        self.select()
        self.clan.seat_limit_override = 3
        self.clan.save()
        data = {'enabled': 'on', 'default_limit': 1, 'duration': 'DAYS', 'days': 14}
        form = ClanSeatConfigurationForm(data=data, instance=self.config)
        self.assertTrue(form.is_valid(), form.errors)
        self.clan.seat_limit_override = None
        self.clan.save()
        self.assertFalse(ClanSeatConfigurationForm(data=data, instance=self.config).is_valid())

    def test_disable_requires_confirmation_in_admin_form(self):
        self.select()
        data = {'default_limit': 8, 'duration': 'DAYS', 'days': 14}
        form = ClanSeatConfigurationForm(data=data, instance=self.config)
        self.assertFalse(form.is_valid())
        data['confirm_release'] = 'on'
        form = ClanSeatConfigurationForm(data=data, instance=self.config)
        self.assertTrue(form.is_valid(), form.errors)

    def test_editor_and_resize_protect_holds_clone_starts_empty(self):
        self.select()
        with self.assertRaises(SeatingPlanValidationError): SeatingPlanService.save_grid(self.plan, [])
        self.plan.columns = 1
        with self.assertRaises(ValidationError): self.plan.full_clean()
        cloned = self.plan.clone_for_event()
        self.assertFalse(ClanSeatHold.objects.filter(cell__plan=cloned).exists())

    def test_admin_assignment_respects_hold_even_force(self):
        self.select()
        self.admin.is_staff = True
        self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_assign_seat'), json.dumps({
            'registration_id': self.other_reg.pk, 'x': 1, 'y': 1, 'force': True}), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_admin_explicit_release_makes_seat_public(self):
        self.select()
        self.admin.is_staff = self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        response = self.client.post(reverse('admin_release_seat'), json.dumps({
            'event_id': self.event.pk, 'x': 1, 'y': 1}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.seats[0].reserve_for_user(self.other_reg)[0])

    def test_clan_deletion_releases_only_hold(self):
        self.select()
        self.seats[0].reserve_for_user(self.reg)
        self.clan.delete()
        self.assertFalse(ClanSeatHold.objects.exists())
        self.seats[0].refresh_from_db()
        self.assertEqual(self.seats[0].registration_id, self.reg.pk)

    def test_edit_profile_cannot_change_override(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('clan_edit', args=[self.clan.slug]), {
            'name': self.clan.name, 'tag': 'TC', 'password': '', 'seat_limit_override': 100})
        self.clan.refresh_from_db()
        self.assertIsNone(self.clan.seat_limit_override)

    def test_stale_selection_cannot_erase_another_admin_change(self):
        revision = selection_status(self.clan, self.event)['revision']
        self.select()
        with self.assertRaises(ClanSeatError):
            self.select([self.seats[2]], expected_revision=revision)
        self.assertEqual(len(selection_status(self.clan, self.event)['selected']), 2)

    def test_stale_selection_detects_bulk_cancellation(self):
        self.select()
        self.seats[0].reserve_for_user(self.reg)
        revision = selection_status(self.clan, self.event)['revision']
        self.reg.mark_as_cancelled()
        with self.assertRaises(ClanSeatError):
            self.select([self.seats[1]], expected_revision=revision)

    def test_backend_configuration_reduction_flow(self):
        self.select()
        self.admin.is_staff = self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        url = reverse('admin:configuration_clanseatconfiguration_change', args=[1])
        data = {'enabled': 'on', 'default_limit': 1, 'duration': 'DAYS', 'days': 14, '_save': 'Speichern'}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.config.refresh_from_db()
        self.assertEqual(self.config.default_limit, 8)
        hold = ClanSeatHold.objects.get(cell=self.seats[0])
        data.update(release_seats=[str(hold.pk)], confirm_release='on')
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.config.refresh_from_db()
        self.assertEqual(self.config.default_limit, 1)
        self.assertEqual(selection_status(self.clan, self.event)['selected'], [self.seats[1].pk])

    def test_admin_delete_and_inline_delete_are_protected(self):
        self.select()
        self.admin.is_staff = self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('admin:seating_seatingcell_delete', args=[self.seats[0].pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin:seating_seatingplan_delete', args=[self.plan.pk])).status_code, 403)
        from .admin import ProtectedCellFormSet
        from django.forms import inlineformset_factory
        factory = inlineformset_factory(SeatingPlan, SeatingCell, formset=ProtectedCellFormSet, fields=('cell_type',), extra=0)
        formset = factory(data={
            'cells-TOTAL_FORMS': '1', 'cells-INITIAL_FORMS': '1',
            'cells-0-id': self.seats[0].pk, 'cells-0-cell_type': 'SEAT', 'cells-0-DELETE': 'on',
        }, instance=self.plan)
        self.assertFalse(formset.is_valid())

    def test_plan_cannot_be_reassigned_with_open_holds(self):
        self.select()
        event = Event.objects.create(title='Other LAN', start_date=self.now+timedelta(days=80), end_date=self.now+timedelta(days=83))
        self.plan.event = event
        with self.assertRaises(ValidationError): self.plan.full_clean()

    def test_active_hold_query_count_does_not_grow_per_seat(self):
        self.select()
        with self.assertNumQueries(4):
            self.client.get(reverse('api_event_seating', args=[self.event.pk]))
        SeatingCell.objects.bulk_create([
            SeatingCell(plan=self.plan, x=i, y=2, cell_type='SEAT') for i in range(1, 13)])
        with self.assertNumQueries(4):
            self.client.get(reverse('api_event_seating', args=[self.event.pk]))
