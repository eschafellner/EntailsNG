from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from clans.models import Clan, ClanMembership
from configuration.models import SystemErrorLog
from emails.models import GeneralEmailSettings, OutgoingEmail
from events.models import Event, EventRegistration
from events.services import PaymentService, RegistrationService
from seating.models import SeatingCell, SeatingPlan
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentRegistration
from users.auth_backends import EmailOrUsernameBackend
from users.exceptions import AccountDeletionError
from users.models import EmailVerificationCode
from users.services import UserService

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AccountDeletionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            'delete-me', 'delete-me@example.com', 'StrongPass123!',
            first_name='Personal', last_name='Name', birthday=date(2000, 1, 1),
        )
        self.other = User.objects.create_user('other', 'other@example.com', 'StrongPass123!')
        self.event = Event.objects.create(
            title='Test LAN', start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=2),
            status=Event.Status.REGISTRATION_OPEN, is_active=True, max_guests=100,
        )
        self.registration = EventRegistration.objects.create(user=self.user, event=self.event)
        self.game = Game.objects.create(name='Test Game', team_size=2)
        self.client.force_login(self.user)

    def delete(self, **data):
        return self.client.post(reverse('account_delete'), {
            'password': 'StrongPass123!', 'confirm_deletion': 'on', **data,
        })

    def create_team(self, *, solo=False, other_member=True):
        team = Team.objects.create(
            name=f'{self.user.username} (Solo)' if solo else 'Our Team',
            captain=self.user, game=self.game, is_solo=solo,
        )
        TeamMember.objects.create(team=team, user=self.user, role=TeamMember.Role.CAPTAIN)
        if other_member:
            TeamMember.objects.create(team=team, user=self.other)
        return team

    def create_tournament(self, team, status, generated=False):
        tournament = Tournament.objects.create(
            title='Test Cup', event=self.event, game=self.game, status=status,
            is_generated=generated,
            registration_start=timezone.now() - timedelta(hours=1),
            registration_end=timezone.now() + timedelta(hours=1),
        )
        TournamentRegistration.objects.create(tournament=tournament, team=team)
        return tournament

    def test_success_erases_profile_preserves_id_and_cancels_ticket_and_seat(self):
        original_token = self.registration.checkin_token
        plan = SeatingPlan.objects.create(event=self.event, name='Hall', rows=1, columns=1)
        seat = SeatingCell.objects.create(
            plan=plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT,
            registration=self.registration,
            reservation_status=SeatingCell.ReservationStatus.PRE_RESERVED,
        )
        self.user.groups.add(Group.objects.create(name='Guests'))
        self.user.user_permissions.add(Permission.objects.first())
        response = self.delete()
        self.assertRedirects(response, reverse('dashboard'))
        self.user.refresh_from_db()
        self.registration.refresh_from_db()
        seat.refresh_from_db()
        self.assertIsNotNone(self.user.deleted_at)
        self.assertFalse(self.user.is_active)
        self.assertFalse(self.user.has_usable_password())
        self.assertEqual(self.user.first_name, '')
        self.assertEqual(self.user.last_name, '')
        self.assertIsNone(self.user.birthday)
        self.assertIsNone(self.user.last_login)
        self.assertFalse(self.user.groups.exists())
        self.assertFalse(self.user.user_permissions.exists())
        self.assertNotEqual(self.user.username, 'delete-me')
        self.assertNotEqual(self.user.email, 'delete-me@example.com')
        self.assertEqual(self.user.display_name, 'Gelöschter Benutzer')
        self.assertEqual(self.registration.user_id, self.user.pk)
        self.assertEqual(self.registration.payment_status, EventRegistration.PaymentStatus.CANCELLED)
        self.assertNotEqual(self.registration.checkin_token, original_token)
        self.assertIsNone(seat.registration_id)
        self.assertEqual(seat.reservation_status, SeatingCell.ReservationStatus.FREE)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(self.registration.can_check_in().allowed)

    def test_paid_registration_blocks_even_for_past_event_and_changes_nothing(self):
        self.event.end_date = timezone.now() - timedelta(days=1)
        self.event.start_date = timezone.now() - timedelta(days=2)
        self.event.status = Event.Status.FINISHED
        self.event.save()
        self.registration.payment_status = EventRegistration.PaymentStatus.PAID
        self.registration.save()
        response = self.delete()
        self.assertContains(response, 'Bitte kläre die Stornierung zuerst mit der Orga')
        self.user.refresh_from_db()
        self.registration.refresh_from_db()
        self.assertIsNone(self.user.deleted_at)
        self.assertEqual(self.registration.payment_status, EventRegistration.PaymentStatus.PAID)
        self.assertEqual(self.user.username, 'delete-me')

    def test_paid_ticket_can_be_cancelled_by_orga_before_deletion(self):
        PaymentService.mark_paid(self.registration, amount=30, send_email=False)
        self.assertTrue(UserService.deletion_blockers(self.user))
        PaymentService.mark_cancelled(self.registration)
        self.assertRedirects(self.delete(), reverse('dashboard'))
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.paid_amount, 30)

    def test_running_tournament_blocks_without_paid_ticket(self):
        team = self.create_team()
        self.create_tournament(team, Tournament.Status.IN_PROGRESS)
        self.assertContains(self.delete(), 'Bitte kläre deinen Austritt zuerst mit der Turnierleitung')
        self.user.refresh_from_db()
        self.assertIsNone(self.user.deleted_at)
        self.assertEqual(team.memberships.count(), 2)

    def test_generated_tournament_blocks_accepted_member(self):
        team = self.create_team()
        team.captain = self.other
        team.save()
        self.create_tournament(team, Tournament.Status.REGISTRATION_CLOSED, generated=True)
        with self.assertRaises(AccountDeletionError) as error:
            UserService.delete_account(self.user, 'StrongPass123!')
        self.assertEqual(error.exception.code, 'active_tournament')

    def test_pending_request_does_not_block_or_remove_other_peoples_team(self):
        team = Team.objects.create(name='Other Team', captain=self.other, game=self.game)
        TeamMember.objects.create(team=team, user=self.other, role=TeamMember.Role.CAPTAIN)
        TeamMember.objects.create(team=team, user=self.user, status=TeamMember.Status.PENDING)
        self.create_tournament(team, Tournament.Status.IN_PROGRESS)
        self.assertRedirects(self.delete(), reverse('dashboard'))
        self.assertTrue(Team.objects.filter(pk=team.pk).exists())
        self.assertFalse(TeamMember.objects.filter(user=self.user).exists())

    def test_team_captain_transfers_and_incomplete_open_roster_is_unregistered(self):
        team = self.create_team()
        tournament = self.create_tournament(team, Tournament.Status.REGISTRATION_OPEN)
        self.delete()
        team.refresh_from_db()
        self.assertEqual(team.captain_id, self.other.pk)
        self.assertEqual(team.memberships.get(user=self.other).role, TeamMember.Role.CAPTAIN)
        self.assertFalse(team.memberships.filter(user=self.user).exists())
        self.assertFalse(tournament.registrations.exists())

    def test_last_member_without_history_removes_empty_team(self):
        team = self.create_team(other_member=False)
        self.delete()
        self.assertFalse(Team.objects.filter(pk=team.pk).exists())

    def test_historical_solo_team_and_results_survive_without_old_name_or_slug(self):
        team = self.create_team(solo=True, other_member=False)
        old_slug = team.slug
        tournament = self.create_tournament(team, Tournament.Status.FINISHED, generated=True)
        self.delete()
        team.refresh_from_db()
        self.assertTrue(team.is_archived)
        self.assertEqual(team.name, 'Gelöschter Benutzer')
        self.assertNotEqual(team.slug, old_slug)
        self.assertNotIn('delete-me', team.slug)
        self.assertEqual(tournament.registrations.get().team_id, team.pk)
        self.assertEqual(team.memberships.get().user_id, self.user.pk)
        response = self.client.get(reverse('tournament_detail', kwargs={'slug': tournament.slug}))
        self.assertContains(response, 'Gelöschter Benutzer')
        self.assertNotContains(response, 'delete-me')

    def test_clan_admin_transfers_and_pending_requests_disappear(self):
        clan = Clan.objects.create(name='Our Clan', password='clan-pass')
        ClanMembership.objects.create(clan=clan, user=self.user, role=ClanMembership.Role.ADMIN)
        ClanMembership.objects.create(clan=clan, user=self.other)
        pending_clan = Clan.objects.create(name='Other Clan', password='clan-pass')
        ClanMembership.objects.create(clan=pending_clan, user=self.other, status=ClanMembership.Status.PENDING)
        ClanMembership.objects.create(clan=pending_clan, user=self.user, status=ClanMembership.Status.PENDING)
        self.delete()
        self.assertEqual(clan.memberships.get(user=self.other).role, ClanMembership.Role.ADMIN)
        self.assertFalse(ClanMembership.objects.filter(user=self.user).exists())

    def test_last_clan_member_dissolves_clan(self):
        clan = Clan.objects.create(name='Empty Clan', password='clan-pass')
        ClanMembership.objects.create(clan=clan, user=self.user, role=ClanMembership.Role.ADMIN)
        self.delete()
        self.assertFalse(Clan.objects.filter(pk=clan.pk).exists())

    def test_wrong_password_preserves_data_and_rate_limits_repeated_attempts(self):
        for _ in range(5):
            self.assertContains(self.delete(password='wrong'), 'Das aktuelle Passwort ist nicht korrekt')
        self.assertContains(self.delete(), 'Zu viele Passwortfehlversuche')
        self.user.refresh_from_db()
        self.assertIsNone(self.user.deleted_at)
        self.assertEqual(self.user.failed_login_attempts, 5)
        self.assertIsNotNone(self.user.locked_until)
        self.assertEqual(self.user.username, 'delete-me')
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.payment_status, EventRegistration.PaymentStatus.UNPAID)

    def test_confirmation_and_password_are_required(self):
        self.assertContains(self.delete(confirm_deletion=''), 'Bitte bestätige')
        self.assertContains(self.delete(password=''), 'Bitte gib dein aktuelles Passwort ein')
        self.user.refresh_from_db()
        self.assertIsNone(self.user.deleted_at)

    def test_only_authenticated_post_with_csrf_can_delete(self):
        self.assertEqual(self.client.get(reverse('account_delete')).status_code, 405)
        self.assertEqual(Client().post(reverse('account_delete')).status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse('account_delete'), {
            'password': 'StrongPass123!', 'confirm_deletion': 'on',
        }).status_code, 403)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.deleted_at)

    def test_post_cannot_target_another_user(self):
        self.delete(user_id=self.other.pk)
        self.other.refresh_from_db()
        self.assertIsNone(self.other.deleted_at)
        self.assertTrue(self.other.is_active)

    def test_staff_account_cannot_delete_itself(self):
        self.user.is_staff = True
        self.user.save()
        self.assertContains(self.delete(), 'Mitarbeiterkonten können nicht selbst gelöscht werden')
        self.user.refresh_from_db()
        self.assertIsNone(self.user.deleted_at)

    def test_profile_shows_inline_confirmation_and_concrete_blockers(self):
        response = self.client.get(reverse('profile'))
        self.assertContains(response, 'Löschung vorbereiten')
        self.assertContains(response, reverse('account_delete'))
        self.registration.payment_status = EventRegistration.PaymentStatus.PAID
        self.registration.save()
        response = self.client.get(reverse('profile'))
        self.assertContains(response, 'Test LAN')
        self.assertNotContains(response, 'name="confirm_deletion"')

    def test_paid_status_is_rechecked_after_profile_was_loaded(self):
        self.client.get(reverse('profile'))
        PaymentService.mark_paid(self.registration, amount=30, send_email=False)
        self.delete()
        self.user.refresh_from_db()
        self.assertIsNone(self.user.deleted_at)

    def test_reregistration_uses_new_id_and_has_no_old_tickets_or_memberships(self):
        team = self.create_team()
        old_pk = self.user.pk
        self.delete()
        settings = GeneralEmailSettings.load()
        settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        settings.sender_email = 'noreply@example.com'
        settings.is_enabled = True
        settings.save()
        response = self.client.post(reverse('register'), {
            'username': 'delete-me', 'email': 'DELETE-ME@example.com', 'birthday': '2000-01-01',
            'password1': 'NewStrongPass123!', 'password2': 'NewStrongPass123!',
        })
        self.assertRedirects(response, reverse('verify_email'))
        new_user = User.objects.get(username='delete-me')
        self.assertNotEqual(new_user.pk, old_pk)
        response = self.client.post(reverse('verify_email'), {'code': new_user.verification_codes.get().code})
        self.assertRedirects(response, reverse('dashboard'))
        self.assertFalse(new_user.registrations.exists())
        self.assertFalse(new_user.tournament_memberships.exists())
        self.assertFalse(new_user.clan_memberships.exists())
        self.assertFalse(team.is_captain(new_user))
        self.assertEqual(self.client.get(reverse('registration_payment_qr', args=[self.registration.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('registration_checkin_qr', args=[self.registration.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse('profile')), 'Test LAN')
        new_reg, _, _ = RegistrationService.register_user(new_user, self.event.pk)
        self.assertNotEqual(new_reg.pk, self.registration.pk)
        self.assertEqual(new_reg.user_id, new_user.pk)

    def test_old_sessions_and_reset_tokens_cannot_access_tombstone(self):
        other_session = Client()
        other_session.force_login(self.user)
        old_token = default_token_generator.make_token(self.user)
        old_uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.delete()
        self.assertEqual(other_session.get(reverse('profile')).status_code, 302)
        self.assertNotIn('_auth_user_id', other_session.session)
        self.assertFalse(self.client.login(username='delete-me', password='StrongPass123!'))
        response = self.client.get(reverse('password_reset_confirm', args=[old_uid, old_token]))
        self.assertFalse(response.context['validlink'])

    def test_deleted_record_cannot_be_reactivated_or_overwritten_by_stale_object(self):
        stale = User.objects.get(pk=self.user.pk)
        self.delete()
        stale.email = 'delete-me@example.com'
        stale.birthday = date(2001, 2, 3)
        with self.assertRaises(ValidationError):
            stale.save()
        self.user.refresh_from_db()
        with self.assertRaises(ValidationError):
            EmailVerificationCode.generate_for_user(self.user)
        self.assertEqual(UserService.verify_registration_code(self.user, '123456')[0], 'invalid_or_expired')
        # Selbst ein versehentliches administratives DB-Update aktiviert den Login nicht.
        User.objects.filter(pk=self.user.pk).update(is_active=True)
        self.assertIsNone(EmailOrUsernameBackend().get_user(self.user.pk))

    def test_pending_activation_session_cannot_recreate_codes_after_deletion(self):
        pending_client = Client()
        session = pending_client.session
        session['pending_verification_user_id'] = self.user.pk
        session.save()
        self.delete()
        self.assertRedirects(pending_client.post(reverse('resend_verification_code')), reverse('login'))
        self.assertFalse(self.user.verification_codes.exists())

    def test_payment_and_event_registration_reject_stale_deleted_user(self):
        self.delete()
        with self.assertRaises(ValidationError):
            PaymentService.mark_paid(self.registration, send_email=False)
        from events.exceptions import RegistrationError
        with self.assertRaises(RegistrationError):
            RegistrationService.register_user(self.user, self.event.pk)

    def test_outbox_and_error_logs_are_erased_without_affecting_other_users(self):
        code = EmailVerificationCode.generate_for_user(self.user, new_email='new-target@example.com')
        for target, key, content in [
            (self.user.email, 'password_reset', 'Personal Name and old reset token'),
            (code.new_email, 'email_change_verification', f'Hello delete-me: {code.code}'),
            (self.other.email, 'password_reset', 'Other user mail'),
        ]:
            OutgoingEmail.objects.create(recipient_email=target, template_key=key, subject=content, body_text=content, body_html=content)
        SystemErrorLog.objects.create(
            path='/profile/', exception_type='TestError', user=self.user.username,
            ip_address='192.0.2.1', error_message='Personal Name', traceback='Personal Name',
        )
        self.delete()
        self.assertFalse(SystemErrorLog.objects.exists())
        self.assertFalse(EmailVerificationCode.objects.filter(user=self.user).exists())
        self.assertEqual(OutgoingEmail.objects.filter(status=OutgoingEmail.Status.EXPIRED).count(), 2)
        self.assertEqual(OutgoingEmail.objects.get(recipient_email=self.other.email).body_text, 'Other user mail')
        for outgoing in OutgoingEmail.objects.filter(status=OutgoingEmail.Status.EXPIRED):
            self.assertEqual(outgoing.body_text, '')
            self.assertEqual(outgoing.body_html, '')
            self.assertEqual(outgoing.subject, '')
            self.assertNotIn('delete-me', outgoing.recipient_email)

    def test_callback_prepared_before_deletion_does_not_queue_old_email(self):
        with patch('users.services.send_system_email') as send:
            with self.captureOnCommitCallbacks(execute=True):
                UserService.request_email_change(self.user, 'later@example.com')
                self.delete()
            send.assert_not_called()

    def test_failure_rolls_back_entire_deletion(self):
        with patch.object(UserService, '_leave_clans', side_effect=RuntimeError('test rollback')):
            with self.assertRaises(RuntimeError):
                UserService.delete_account(self.user, 'StrongPass123!')
        self.user.refresh_from_db()
        self.registration.refresh_from_db()
        self.assertIsNone(self.user.deleted_at)
        self.assertTrue(self.user.check_password('StrongPass123!'))
        self.assertEqual(self.user.username, 'delete-me')
        self.assertEqual(self.registration.payment_status, EventRegistration.PaymentStatus.UNPAID)


@skipUnlessDBFeature('has_select_for_update')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AccountDeletionConcurrencyTests(TransactionTestCase):
    """Prüft Zeilensperren mit getrennten PostgreSQL-Verbindungen."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('concurrent-delete', 'concurrent@example.com', 'StrongPass123!')
        self.event = Event.objects.create(
            title='Concurrent LAN', start_date=timezone.now() + timedelta(days=1),
            end_date=timezone.now() + timedelta(days=2),
            status=Event.Status.REGISTRATION_OPEN, is_active=True, max_guests=100,
        )
        self.registration = EventRegistration.objects.create(user=self.user, event=self.event)

    @staticmethod
    def in_separate_connection(action):
        from django.db import close_old_connections, connections
        close_old_connections()
        try:
            return action()
        finally:
            connections.close_all()

    def compete_with_deletion(self, competing_action, expected_exception):
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        from threading import Event as ThreadEvent
        paused, proceed = ThreadEvent(), ThreadEvent()
        original = UserService._leave_clans

        def pause(user):
            paused.set()
            if not proceed.wait(10):
                raise RuntimeError('Deletion test timed out')
            return original(user)

        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(UserService, '_leave_clans', side_effect=pause):
            deletion = pool.submit(self.in_separate_connection, lambda: UserService.delete_account(self.user, 'StrongPass123!'))
            self.assertTrue(paused.wait(10))
            competitor = pool.submit(self.in_separate_connection, competing_action)
            try:
                with self.assertRaises(TimeoutError):
                    competitor.result(timeout=0.2)
            finally:
                proceed.set()
            deletion.result(timeout=10)
            with self.assertRaises(expected_exception):
                competitor.result(timeout=10)

    def test_payment_waits_for_deletion_and_cannot_reactivate_ticket(self):
        self.compete_with_deletion(
            lambda: PaymentService.mark_paid(self.registration, send_email=False), ValidationError,
        )
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.payment_status, EventRegistration.PaymentStatus.CANCELLED)

    def test_registration_waits_for_deletion_and_cannot_reactivate_old_registration(self):
        from events.exceptions import RegistrationError
        self.compete_with_deletion(
            lambda: RegistrationService.register_user(self.user, self.event.pk), RegistrationError,
        )

    def test_stale_profile_save_waits_for_deletion_and_cannot_restore_personal_data(self):
        stale = User.objects.get(pk=self.user.pk)
        stale.birthday = date(2001, 1, 1)
        self.compete_with_deletion(lambda: stale.save(update_fields=['birthday']), ValidationError)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.birthday)

    def test_payment_committed_first_blocks_deletion(self):
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        from threading import Event as ThreadEvent
        from django.db import transaction
        paused, proceed = ThreadEvent(), ThreadEvent()

        def payment():
            with transaction.atomic():
                PaymentService.mark_paid(self.registration, amount=30, send_email=False)
                paused.set()
                if not proceed.wait(10):
                    raise RuntimeError('Payment test timed out')

        with ThreadPoolExecutor(max_workers=2) as pool:
            paying = pool.submit(self.in_separate_connection, payment)
            self.assertTrue(paused.wait(10))
            deletion = pool.submit(self.in_separate_connection, lambda: UserService.delete_account(self.user, 'StrongPass123!'))
            try:
                with self.assertRaises(TimeoutError):
                    deletion.result(timeout=0.2)
            finally:
                proceed.set()
            paying.result(timeout=10)
            with self.assertRaises(AccountDeletionError) as error:
                deletion.result(timeout=10)
            self.assertEqual(error.exception.code, 'paid_registration')
        self.user.refresh_from_db()
        self.assertIsNone(self.user.deleted_at)

    def test_two_team_members_can_delete_without_deadlock_during_captain_transfer(self):
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        from threading import Event as ThreadEvent
        second_user = User.objects.create_user('second-delete', 'second-delete@example.com', 'StrongPass123!')
        EventRegistration.objects.create(user=second_user, event=self.event)
        team = Team.objects.create(name='Concurrent Team', captain=self.user)
        TeamMember.objects.create(team=team, user=self.user, role=TeamMember.Role.CAPTAIN)
        TeamMember.objects.create(team=team, user=second_user)
        paused, proceed = ThreadEvent(), ThreadEvent()
        original = UserService._leave_clans

        def pause_first(user):
            if user.pk == self.user.pk:
                paused.set()
                if not proceed.wait(10):
                    raise RuntimeError('Captain transfer test timed out')
            return original(user)

        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(UserService, '_leave_clans', side_effect=pause_first):
            first = pool.submit(self.in_separate_connection, lambda: UserService.delete_account(self.user, 'StrongPass123!'))
            self.assertTrue(paused.wait(10))
            second = pool.submit(self.in_separate_connection, lambda: UserService.delete_account(second_user, 'StrongPass123!'))
            try:
                with self.assertRaises(TimeoutError):
                    second.result(timeout=0.2)
            finally:
                proceed.set()
            first.result(timeout=10)
            second.result(timeout=10)
        self.user.refresh_from_db()
        second_user.refresh_from_db()
        self.assertIsNotNone(self.user.deleted_at)
        self.assertIsNotNone(second_user.deleted_at)
        self.assertFalse(Team.objects.filter(pk=team.pk).exists())
