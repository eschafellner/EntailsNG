from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.core import mail, signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms.models import inlineformset_factory
from django.forms.models import model_to_dict
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from configuration.cache import clear_request_cache
from configuration.contact_admin import ContactCategoryFormSet
from configuration.models import ContactCategory, GeneralConfiguration, NavigationItem
from configuration.validators import parse_contact_recipients
from emails.backends import ConfiguredSMTPBackend
from emails.defaults import DEFAULT_EMAIL_TEMPLATES
from emails.models import EmailTemplate, GeneralEmailSettings, OutgoingEmail
from emails.services import process_email_queue, queue_system_email, send_system_email
from users.services import UserService
from .services import submit_contact
from .tokens import TOKEN_SALT, make_submission_token


class ContactFixtures:
    def setUp(self):
        super().setUp()
        cache.clear()
        clear_request_cache()
        self.cfg = GeneralConfiguration.load()
        self.cfg.contact_enabled = True
        self.cfg.contact_recipient_emails = 'orga@example.com; backup@example.com'
        self.cfg.save()
        self.category = ContactCategory.objects.create(configuration=self.cfg, name='Allgemeine Anfrage')
        self.mail_cfg = GeneralEmailSettings.load()
        self.mail_cfg.transport_mode = GeneralEmailSettings.TransportMode.ENV
        self.mail_cfg.sender_email = 'system@example.com'
        self.mail_cfg.reply_to_email = 'default-reply@example.com'
        self.mail_cfg.is_enabled = True
        self.mail_cfg.is_sandbox = False
        self.mail_cfg.save()
        self.template, _ = EmailTemplate.objects.update_or_create(
            key='contact_request', defaults=DEFAULT_EMAIL_TEMPLATES['contact_request'],
        )
        self.url = reverse('contact:form')

    def contact_request(self, user=None, ip='127.0.0.1'):
        request = RequestFactory().post(self.url, REMOTE_ADDR=ip)
        request.user = user or AnonymousUser()
        request.session = {}
        token = make_submission_token(request)
        return request, token

    def submit(self, request=None, token=None, **kwargs):
        if request is None:
            request, token = self.contact_request()
        return submit_contact(request, **{
            'email': 'guest@example.com', 'category_id': self.category.pk,
            'message': 'Hallo Orga-Team!\nIch habe eine Frage.', 'submission_token': token,
            **kwargs,
        })

    def post_data(self, client=None, **kwargs):
        response = (client or self.client).get(self.url)
        return {
            'email': 'guest@example.com', 'category': self.category.pk,
            'message': 'Hallo Orga-Team!',
            'submission_token': response.context['form'].initial['submission_token'],
            **kwargs,
        }


class ContactConfigurationTests(ContactFixtures, TestCase):
    def test_recipient_lists_normalize_deduplicate_and_accept_trailing_separator(self):
        self.assertEqual(
            parse_contact_recipients(' ORGA@Example.com ; other@example.com; orga@example.com; '),
            ['orga@example.com', 'other@example.com'],
        )
        self.category.recipient_emails = ' TICKETS@Example.com ; tickets@example.com ;'
        self.category.save()
        self.category.refresh_from_db()
        self.assertEqual(self.category.recipient_emails, 'tickets@example.com')

    def test_invalid_addresses_and_other_separators_are_rejected(self):
        for value in ('invalid', 'one@example.com,two@example.com', 'one@example.com\nBcc: thief@example.com'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_contact_recipients(value)
        with self.assertRaises(ValidationError):
            parse_contact_recipients(';'.join(f'guest{i}@example.com' for i in range(21)))

    def test_enabled_configuration_requires_valid_default_recipients(self):
        self.cfg.contact_recipient_emails = ''
        with self.assertRaises(ValidationError) as result:
            self.cfg.full_clean()
        self.assertIn('contact_recipient_emails', result.exception.message_dict)

    def test_category_rejects_header_injection_and_duplicate_names(self):
        self.category.name = 'Thema\nBcc: other@example.com'
        with self.assertRaises(ValidationError):
            self.category.full_clean()
        duplicate = ContactCategory(configuration=self.cfg, name='allgemeine anfrage')
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_inline_cannot_remove_last_active_category_while_enabled(self):
        formset_class = inlineformset_factory(
            GeneralConfiguration, ContactCategory, formset=ContactCategoryFormSet,
            fields=('name', 'recipient_emails', 'order', 'is_active'), extra=0,
        )
        formset = formset_class(instance=self.cfg, prefix='categories', data={
            'categories-TOTAL_FORMS': '1', 'categories-INITIAL_FORMS': '1',
            'categories-0-id': str(self.category.pk), 'categories-0-configuration': '1',
            'categories-0-name': self.category.name, 'categories-0-recipient_emails': '',
            'categories-0-order': '0', 'categories-0-DELETE': 'on',
        })
        self.assertFalse(formset.is_valid())
        self.assertIn('mindestens eine Betreffkategorie', str(formset.non_form_errors()))

    def test_admin_exposes_inline_and_requires_configuration_permission(self):
        user = get_user_model().objects.create_user('contact_staff', 'staff@example.com', 'password', is_staff=True)
        self.client.force_login(user)
        url = reverse('admin:configuration_generalconfiguration_change', args=[1])
        self.assertEqual(self.client.get(url).status_code, 403)
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='configuration', codename__in=(
                'change_generalconfiguration', 'view_contactcategory', 'add_contactcategory',
                'change_contactcategory', 'delete_contactcategory',
            ),
        ))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Standardempfänger für Kontaktanfragen')
        self.assertContains(response, 'contact_categories-TOTAL_FORMS')

    def test_admin_saves_and_normalizes_multiple_category_recipients(self):
        user = get_user_model().objects.create_superuser('contact_admin', 'admin@example.com', 'password')
        self.client.force_login(user)
        data = model_to_dict(self.cfg)
        data.update({
            'contact_recipient_emails': ' ORGA@Example.com; backup@example.com; orga@example.com ',
            'contact_categories-TOTAL_FORMS': '1', 'contact_categories-INITIAL_FORMS': '1',
            'contact_categories-0-id': str(self.category.pk), 'contact_categories-0-configuration': '1',
            'contact_categories-0-name': 'Tickets', 'contact_categories-0-order': '0',
            'contact_categories-0-is_active': 'on',
            'contact_categories-0-recipient_emails': ' TICKET@Example.com ; finance@example.com ; ticket@example.com;',
            '_save': 'Speichern',
        })
        response = self.client.post(reverse('admin:configuration_generalconfiguration_change', args=[1]), data)
        self.assertEqual(response.status_code, 302)
        self.cfg.refresh_from_db()
        self.category.refresh_from_db()
        self.assertEqual(self.cfg.contact_recipient_emails, 'orga@example.com; backup@example.com')
        self.assertEqual(self.category.recipient_emails, 'ticket@example.com; finance@example.com')


class ContactDeliveryTests(ContactFixtures, TestCase):
    def test_default_recipients_are_queued_separately_with_reply_to(self):
        result = self.submit(message='Hallo <script>alert(1)</script> & Orga!\nNoch eine Zeile {email}.')
        self.assertEqual([row.recipient_email for row in result], ['orga@example.com', 'backup@example.com'])
        self.assertEqual(len({row.contact_submission_id for row in result}), 1)
        for row in result:
            self.assertEqual(row.reply_to_email, 'guest@example.com')
            self.assertEqual(row.status, OutgoingEmail.Status.PENDING)
            self.assertNotIn('<script>', row.body_html)
            self.assertIn('&lt;script&gt;', row.body_html)
            self.assertIn('\nNoch eine Zeile {email}.', row.body_text)
            self.assertNotIn('127.0.0.1', row.contact_ip_hash)

    def test_category_recipients_replace_defaults_and_deduplicate(self):
        self.category.recipient_emails = 'tickets@example.com; payment@example.com; TICKETS@example.com'
        self.category.save()
        result = self.submit()
        self.assertEqual([row.recipient_email for row in result], ['tickets@example.com', 'payment@example.com'])

    def test_configuration_is_read_fresh_on_submission(self):
        GeneralConfiguration.load()  # Prime cache deliberately, then bypass cache invalidation.
        GeneralConfiguration.objects.filter(pk=1).update(contact_enabled=False)
        with self.assertRaises(ValidationError):
            self.submit()
        self.assertFalse(OutgoingEmail.objects.exists())

    def test_category_must_still_be_active_at_submission(self):
        self.category.is_active = False
        self.category.save()
        with self.assertRaises(ValidationError):
            self.submit()
        self.assertFalse(OutgoingEmail.objects.exists())

    def test_invalid_runtime_recipient_does_not_leak_address_to_guest(self):
        ContactCategory.objects.filter(pk=self.category.pk).update(recipient_emails='private-invalid-address')
        with self.assertRaises(ValidationError) as result:
            self.submit()
        self.assertNotIn('private-invalid-address', str(result.exception))
        self.assertFalse(OutgoingEmail.objects.exists())

    def test_missing_or_disabled_template_and_invalid_subject_roll_back(self):
        for subject, active in (('Kontakt', False), ('Bad\nBcc: hidden@example.com', True), ('{category}' * 20, True)):
            self.template.subject, self.template.is_active = subject, active
            self.template.save()
            with self.subTest(subject=subject), self.assertRaises(ValidationError):
                self.submit()
            self.assertFalse(OutgoingEmail.objects.exists())

    def test_failure_for_second_recipient_rolls_back_entire_batch(self):
        real_queue = queue_system_email
        counter = 0

        def queue(*args, **kwargs):
            nonlocal counter
            counter += 1
            return real_queue(*args, **kwargs) if counter == 1 else None

        with patch('contact.services.queue_system_email', side_effect=queue):
            with self.assertRaises(ValidationError):
                self.submit()
        self.assertFalse(OutgoingEmail.objects.exists())

    def test_double_submission_reuses_original_recipient_snapshot(self):
        request, token = self.contact_request()
        first = self.submit(request, token)
        self.category.recipient_emails = 'changed@example.com'
        self.category.save()
        again = self.submit(request, token)
        self.assertEqual([row.pk for row in first], [row.pk for row in again])
        self.assertEqual(OutgoingEmail.objects.count(), 2)

    def test_sender_cooldown_and_ip_limit_apply_before_queueing(self):
        self.submit()
        with self.assertRaisesMessage(ValidationError, 'Bitte warte'):
            self.submit()
        with override_settings(CONTACT_MAX_PER_IP_TEN_MINUTES=1):
            with self.assertRaisesMessage(ValidationError, 'zu viele Anfragen'):
                self.submit(email='different@example.com')
        self.assertEqual(OutgoingEmail.objects.count(), 2)

    @override_settings(CONTACT_MIN_INTERVAL_SECONDS=0)
    def test_hour_limit_counts_submissions_instead_of_recipient_jobs(self):
        for _ in range(5):
            self.submit()
        self.assertEqual(OutgoingEmail.objects.count(), 10)
        with self.assertRaises(ValidationError):
            self.submit()

    def test_smtp_failure_retains_reply_to_for_retry_and_success(self):
        rows = self.submit()
        with patch('emails.services.EmailMultiAlternatives.send', side_effect=TimeoutError('SMTP timeout')):
            sent, failed = process_email_queue(email_ids=[rows[0].pk])
        self.assertEqual((sent, failed), (0, 1))
        rows[0].refresh_from_db()
        self.assertEqual(rows[0].reply_to_email, 'guest@example.com')
        sent, failed = process_email_queue(email_ids=[row.pk for row in rows])
        self.assertEqual((sent, failed), (2, 0))
        self.assertEqual([message.reply_to for message in mail.outbox], [['guest@example.com']] * 2)
        self.assertTrue(all(len(message.to) == 1 and not message.cc and not message.bcc for message in mail.outbox))

    def test_kill_switch_prevents_submission(self):
        self.mail_cfg.is_enabled = False
        self.mail_cfg.save()
        with self.assertRaises(ValidationError):
            self.submit()
        self.assertFalse(OutgoingEmail.objects.exists())

    def test_configured_backend_preserves_individual_reply_to_in_sandbox(self):
        self.mail_cfg.is_sandbox = True
        self.mail_cfg.sandbox_redirect_email = 'sandbox@example.com'
        self.mail_cfg.save()
        self.submit()
        transport = mail.get_connection('django.core.mail.backends.locmem.EmailBackend')
        with override_settings(EMAIL_BACKEND='emails.backends.ConfiguredSMTPBackend'):
            with patch.object(ConfiguredSMTPBackend, '_build_backend', return_value=transport):
                self.assertEqual(process_email_queue()[0], 2)
        for message in mail.outbox:
            self.assertEqual(message.to, ['sandbox@example.com'])
            self.assertEqual(message.reply_to, ['guest@example.com'])
            self.assertEqual(message.from_email, 'system@example.com')
            self.assertTrue(message.subject.startswith('[TESTMODUS]'))

    def test_generic_immediate_email_supports_optional_reply_to(self):
        self.assertTrue(send_system_email(
            'contact_request', 'orga@example.com', {'category': 'Thema'},
            immediate=True, reply_to_email='guest@example.com',
        ))
        self.assertEqual(mail.outbox[0].reply_to, ['guest@example.com'])

    def test_reply_to_header_injection_cannot_be_queued(self):
        with self.assertRaises(ValidationError):
            queue_system_email('contact_request', 'orga@example.com', {}, reply_to_email='guest@example.com\nBcc: thief@example.com')
        self.assertFalse(OutgoingEmail.objects.exists())

    @override_settings(IS_TESTING=False)
    def test_worker_starts_once_after_the_complete_transaction_commits(self):
        with patch('emails.services.sys.argv', ['manage.py', 'runserver']):
            with patch('emails.services.threading.Thread') as worker:
                with self.captureOnCommitCallbacks(execute=True):
                    with transaction.atomic():
                        self.submit()
                        worker.assert_not_called()
                worker.return_value.start.assert_called_once()
                self.assertEqual(OutgoingEmail.objects.count(), 2)

    def test_account_deletion_erases_contact_copies_even_with_other_reply_address(self):
        user = get_user_model().objects.create_user('contact_guest', 'account@example.com', 'password')
        request, token = self.contact_request(user=user)
        rows = self.submit(request, token, email='other-reply@example.com')
        self.assertTrue(all(row.submitted_by == user for row in rows))
        UserService.delete_account(user, 'password')
        for row in rows:
            row.refresh_from_db()
            self.assertEqual(row.status, OutgoingEmail.Status.EXPIRED)
            self.assertEqual(row.body_html, '')
            self.assertEqual(row.reply_to_email, '')
            self.assertIsNone(row.submitted_by_id)
            self.assertIsNone(row.contact_submission_id)
            self.assertEqual(row.contact_ip_hash, '')


class ContactFrontendTests(ContactFixtures, TestCase):
    def test_anonymous_page_hides_recipients_and_shows_only_active_sorted_categories(self):
        ContactCategory.objects.create(configuration=self.cfg, name='Zuerst', order=0)
        self.category.order = 10
        self.category.save()
        ContactCategory.objects.create(configuration=self.cfg, name='Verborgene Kategorie', is_active=False)
        response = self.client.get(self.url)
        self.assertContains(response, 'Deine E-Mail-Adresse')
        self.assertNotContains(response, 'orga@example.com')
        self.assertNotContains(response, 'backup@example.com')
        self.assertNotContains(response, 'Verborgene Kategorie')
        self.assertLess(response.content.index(b'Zuerst'), response.content.index(b'Allgemeine Anfrage'))
        self.assertIn('no-store', response['Cache-Control'])

    def test_authenticated_email_is_prefilled_and_can_be_edited_without_changing_profile(self):
        user = get_user_model().objects.create_user('frontend_guest', 'account@example.com', 'password')
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.context['form'].initial['email'], 'account@example.com')
        response = self.client.post(self.url, self.post_data(email='other@example.com'))
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.email, 'account@example.com')
        self.assertEqual(OutgoingEmail.objects.first().reply_to_email, 'other@example.com')

    def test_success_uses_post_redirect_get_and_has_no_duplicate_jobs(self):
        data = self.post_data()
        response = self.client.post(self.url, data, follow=True)
        self.assertContains(response, 'Deine Anfrage wurde angenommen')
        self.assertEqual(len(response.redirect_chain), 1)
        self.client.post(self.url, data)
        self.assertEqual(OutgoingEmail.objects.count(), 2)

    def test_invalid_fields_keep_user_input_without_sending(self):
        data = self.post_data(email='wrong', message='Meine Nachricht bleibt erhalten.')
        response = self.client.post(self.url, data)
        self.assertContains(response, 'gültige E-Mail-Adresse')
        self.assertContains(response, 'Meine Nachricht bleibt erhalten.')
        self.assertFalse(OutgoingEmail.objects.exists())

    def test_honeypot_invalid_category_and_oversized_message_do_not_send(self):
        for changes in ({'website': 'https://spam.example'}, {'category': '999999'}, {'message': 'a' * 10001}):
            with self.subTest(changes=list(changes)):
                response = self.client.post(self.url, self.post_data(**changes))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.assertFalse(OutgoingEmail.objects.exists())

    def test_tampered_expired_and_other_session_tokens_do_not_send(self):
        data = self.post_data()
        original = signing.loads(data['submission_token'], salt=TOKEN_SALT)
        for token in ('tampered', signing.dumps({**original, 'scope': 'another-session'}, salt=TOKEN_SALT)):
            response = self.client.post(self.url, {**data, 'submission_token': token})
            self.assertContains(response, 'Bitte lade die Seite neu')
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 3601):
            response = self.client.post(self.url, data)
            self.assertContains(response, 'Bitte lade die Seite neu')
        self.assertFalse(OutgoingEmail.objects.exists())

    def test_another_browser_session_cannot_reuse_a_submission_token(self):
        data = self.post_data()
        other = Client()
        other.get(self.url)
        response = other.post(self.url, data)
        self.assertContains(response, 'Bitte lade die Seite neu')
        self.assertFalse(OutgoingEmail.objects.exists())

    def test_category_recipient_change_while_filling_form_uses_new_configuration(self):
        data = self.post_data()
        self.category.recipient_emails = 'new@example.com; alternate@example.com'
        self.category.save()
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(OutgoingEmail.objects.values_list('recipient_email', flat=True)), {'new@example.com', 'alternate@example.com'})

    def test_csrf_is_required_and_get_never_sends(self):
        client = Client(enforce_csrf_checks=True)
        data = self.post_data(client)
        self.assertEqual(client.post(self.url, data).status_code, 403)
        self.assertFalse(OutgoingEmail.objects.exists())

    def test_disabled_form_is_hidden_in_navigation_and_rejects_post(self):
        NavigationItem.objects.create(title='Kontakt', url_name='contact:form', icon_name='support')
        self.assertContains(self.client.get(reverse('dashboard')), 'href="/kontakt/"')
        data = self.post_data()
        self.cfg.contact_enabled = False
        with self.captureOnCommitCallbacks(execute=True):
            self.cfg.save()
        self.assertNotContains(self.client.get(reverse('dashboard')), 'href="/kontakt/"')
        response = self.client.post(self.url, data)
        self.assertContains(response, 'momentan nicht verfügbar')
        self.assertNotContains(response, 'name="message"')
        self.assertFalse(OutgoingEmail.objects.exists())

    def test_no_active_categories_or_mail_transport_shows_unavailable_message(self):
        self.category.is_active = False
        self.category.save()
        self.assertContains(self.client.get(self.url), 'momentan nicht verfügbar')
        self.category.is_active = True
        self.category.save()
        self.mail_cfg.transport_mode = GeneralEmailSettings.TransportMode.UNCONFIGURED
        self.mail_cfg.save()
        self.assertContains(self.client.get(self.url), 'momentan nicht verfügbar')
