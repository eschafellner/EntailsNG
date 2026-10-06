import shutil
import tempfile
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from configuration.models import NavigationItem
from events.models import Event
from .checks import private_storage_check
from .content import sanitize_content, content_text
from .forms import AttachmentForm
from .models import KnowledgeSpace, KnowledgePage, KnowledgeRevision, KnowledgeAttachment
from .services import save_space, save_page, publish_page, restore_revision, upload_attachment, EditConflict


class KnowledgeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user('knowledge-staff', is_staff=True)
        cls.other = get_user_model().objects.create_user('knowledge-other', is_staff=True)
        cls.guest = get_user_model().objects.create_user('knowledge-guest')
        cls.space = KnowledgeSpace.objects.create(name='Technik')
        cls.page = save_page(actor=cls.staff, space_id=cls.space.pk, title='Netzwerk',
            content='<p>VLAN 20 konfigurieren.</p>', publish=True)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.staff)
        self.private_root = tempfile.mkdtemp(prefix='entails-knowledge-')
        self.settings_override = override_settings(PRIVATE_MEDIA_ROOT=self.private_root)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.private_root)

    def edit(self, **overrides):
        self.page.refresh_from_db()
        values = {'actor': self.staff, 'space_id': self.space.pk, 'page_id': self.page.pk,
            'expected_version': self.page.version, 'title': self.page.title, 'content': self.page.content}
        values.update(overrides)
        return save_page(**values)

    def upload(self, name='plan.pdf', data=b'%PDF-1.4 test', actor=None):
        form = AttachmentForm(files={'file': SimpleUploadedFile(name, data)})
        self.assertTrue(form.is_valid(), form.errors)
        return upload_attachment(actor=actor or self.staff, page_id=self.page.pk,
            upload=form.cleaned_data['file'], metadata=form.metadata)

    def endpoints(self):
        revision = self.page.revisions.first()
        attachment = self.upload()
        return [
            ('knowledge:home', [], 'get'), ('knowledge:space', [self.space.pk], 'get'),
            ('knowledge:space_create', [], 'get'), ('knowledge:space_edit', [self.space.pk], 'post'),
            ('knowledge:create', [self.space.pk], 'post'), ('knowledge:page', [self.page.pk], 'get'),
            ('knowledge:edit', [self.page.pk], 'post'), ('knowledge:publish', [self.page.pk], 'post'),
            ('knowledge:history', [self.page.pk], 'get'), ('knowledge:revision', [self.page.pk, revision.pk], 'get'),
            ('knowledge:restore', [self.page.pk, revision.pk], 'post'), ('knowledge:upload', [self.page.pk], 'post'),
            ('knowledge:attachment', [attachment.pk], 'get'),
        ]

    def test_anonymous_users_cannot_read_or_write_any_endpoint(self):
        endpoints = self.endpoints()
        self.client.logout()
        for name, args, method in endpoints:
            with self.subTest(endpoint=name):
                response = getattr(self.client, method)(reverse(name, args=args))
                self.assertEqual(response.status_code, 302)
                self.assertIn('/login/', response.url)

    def test_guests_cannot_read_or_write_any_endpoint(self):
        endpoints = self.endpoints()
        self.client.force_login(self.guest)
        for name, args, method in endpoints:
            with self.subTest(endpoint=name):
                self.assertEqual(getattr(self.client, method)(reverse(name, args=args)).status_code, 403)

    def test_active_staff_need_no_additional_model_permissions(self):
        self.assertFalse(self.other.has_perm('knowledge.change_knowledgepage'))
        self.client.force_login(self.other)
        response = self.client.post(reverse('knowledge:edit', args=[self.page.pk]), {
            'title': 'Neuer Titel', 'content': '<p>Ergänzung</p>', 'order': 0,
            'expected_version': self.page.version, 'action': 'publish'})
        self.assertEqual(response.status_code, 302)
        self.page.refresh_from_db()
        self.assertEqual(self.page.published_revision.title, 'Neuer Titel')
        self.assertEqual(self.page.updated_by_id, self.other.pk)

    def test_nonstaff_role_and_superuser_flag_do_not_grant_access(self):
        get_user_model().objects.filter(pk=self.guest.pk).update(is_superuser=True, role='ADMIN')
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(reverse('knowledge:home')).status_code, 403)

    def test_service_checks_fresh_staff_and_active_status(self):
        for change in ({'is_staff': False}, {'is_active': False}, {'deleted_at': timezone.now()}):
            with self.subTest(change=change):
                get_user_model().objects.filter(pk=self.other.pk).update(is_staff=True, is_active=True, deleted_at=None)
                get_user_model().objects.filter(pk=self.other.pk).update(**change)
                with self.assertRaises(PermissionDenied):
                    save_page(actor=self.other, space_id=self.space.pk, title='Forbidden')

    def test_draft_does_not_change_published_document_or_search(self):
        old = self.page.published_revision_id
        page = self.edit(title='Unveröffentlichter Titel', content='<p>Geheime Entwurfsnotiz</p>')
        self.assertEqual(page.published_revision_id, old)
        self.assertTrue(page.has_draft)
        self.assertContains(self.client.get(page.get_absolute_url()), 'VLAN 20 konfigurieren.')
        self.assertNotContains(self.client.get(page.get_absolute_url()), '<p>Geheime Entwurfsnotiz</p>', html=True)
        self.assertContains(self.client.get(page.get_absolute_url() + '?draft=1'), 'Geheime Entwurfsnotiz')
        results = self.client.get(reverse('knowledge:home'), {'q': 'Entwurfsnotiz'})
        self.assertEqual(results.context['results'].paginator.count, 0)

    def test_publishing_draft_creates_new_revision_and_changes_reading_view(self):
        page = self.edit(content='<p>Neue freigegebene Anleitung</p>')
        published = publish_page(actor=self.other, page_id=page.pk, expected_version=page.version)
        self.assertFalse(published.has_draft)
        self.assertEqual(published.version, 3)
        self.assertEqual(published.revisions.count(), 3)
        self.assertContains(self.client.get(published.get_absolute_url()), 'Neue freigegebene Anleitung')
        self.assertEqual(published.published_revision.author_id, self.other.pk)

    def test_unpublished_page_is_readable_as_draft_by_staff(self):
        page = save_page(actor=self.staff, space_id=self.space.pk, title='Draft-only', content='<p>Vorbereitung</p>')
        response = self.client.get(page.get_absolute_url())
        self.assertContains(response, 'Vorbereitung')
        self.assertTrue(response.context['reading_draft'])

    def test_restore_creates_new_draft_and_preserves_publication_and_all_history(self):
        original = self.page.revisions.first()
        newer = self.edit(title='Neue Anleitung', content='<p>Neuer Inhalt</p>', publish=True)
        published_id = newer.published_revision_id
        restored = restore_revision(actor=self.other, page_id=newer.pk, revision_id=original.pk, expected_version=newer.version)
        self.assertEqual(restored.version, 3)
        self.assertEqual(restored.title, 'Netzwerk')
        self.assertEqual(restored.published_revision_id, published_id)
        self.assertEqual(restored.revisions.count(), 3)
        original.refresh_from_db()
        self.assertEqual(original.content, '<p>VLAN 20 konfigurieren.</p>')

    def test_stale_edits_publish_and_restore_do_not_overwrite_other_changes(self):
        version = self.page.version
        original = self.page.revisions.first()
        self.edit(content='<p>Änderung der anderen Orga</p>')
        actions = [lambda: self.edit(expected_version=version),
            lambda: publish_page(actor=self.staff, page_id=self.page.pk, expected_version=version),
            lambda: restore_revision(actor=self.staff, page_id=self.page.pk, revision_id=original.pk, expected_version=version)]
        for action in actions:
            with self.subTest(action=action), self.assertRaises(EditConflict):
                action()
        self.page.refresh_from_db()
        self.assertEqual(self.page.content, '<p>Änderung der anderen Orga</p>')
        self.assertEqual(self.page.revisions.count(), 2)

    def test_conflict_response_keeps_submitted_content_and_version(self):
        self.edit(content='<p>Concurrent</p>')
        response = self.client.post(reverse('knowledge:edit', args=[self.page.pk]), {
            'title': 'Meine Eingabe', 'content': '<p>Eigener Text</p>', 'order': 0,
            'expected_version': 1, 'action': 'draft'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.context['form']['content'].value(), '<p>Eigener Text</p>')
        self.assertEqual(response.context['form']['expected_version'].value(), '1')
        self.assertContains(response, 'zweiten Tab', status_code=409)

    def test_invalid_revision_note_rolls_back_entire_edit(self):
        with self.assertRaises(ValidationError):
            self.edit(title='Must roll back', note='x'*256)
        self.page.refresh_from_db()
        self.assertEqual(self.page.title, 'Netzwerk')
        self.assertEqual(self.page.version, 1)

    def test_revisions_cannot_be_modified_and_admin_cannot_bypass_editor(self):
        revision = self.page.revisions.first()
        revision.content = 'Overwritten'
        with self.assertRaises(ValidationError):
            revision.save()
        from .admin import RevisionAdmin, PageAdmin
        from django.contrib import admin
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = self.staff
        for model, admin_class in ((KnowledgeRevision, RevisionAdmin), (KnowledgePage, PageAdmin)):
            instance = admin_class(model, admin.site)
            self.assertFalse(instance.has_add_permission(request))
            self.assertFalse(instance.has_change_permission(request))
            self.assertFalse(instance.has_delete_permission(request))

    def test_cross_page_revision_restore_and_comparison_are_rejected(self):
        other = save_page(actor=self.staff, space_id=self.space.pk, title='Andere Seite')
        revision = other.revisions.first()
        for name in ('knowledge:revision', 'knowledge:restore'):
            response = (self.client.post if name.endswith('restore') else self.client.get)(
                reverse(name, args=[self.page.pk, revision.pk]), {'expected_version': self.page.version})
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(reverse('knowledge:revision', args=[self.page.pk, self.page.revisions.first().pk]),
            {'compare': revision.pk}).status_code, 404)

    def test_parent_must_belong_to_same_space_and_tree_cannot_cycle(self):
        other_space = KnowledgeSpace.objects.create(name='Einlass')
        foreign = save_page(actor=self.staff, space_id=other_space.pk, title='Fremde Seite')
        with self.assertRaises(ValidationError):
            self.edit(parent=foreign)
        child = save_page(actor=self.staff, space_id=self.space.pk, title='Unterseite', parent=self.page)
        with self.assertRaises(ValidationError):
            self.edit(parent=child)
        with self.assertRaises(ValidationError):
            self.edit(parent=self.page)

    def test_tree_has_twenty_level_limit_including_moved_subtrees(self):
        parent = self.page
        for number in range(1, 20):
            parent = save_page(actor=self.staff, space_id=self.space.pk, title=f'Level {number}', parent=parent)
        with self.assertRaises(ValidationError):
            save_page(actor=self.staff, space_id=self.space.pk, title='Level 21', parent=parent)
        separate = save_page(actor=self.staff, space_id=self.space.pk, title='Separate root')
        descendant = save_page(actor=self.staff, space_id=self.space.pk, title='Separate child', parent=separate)
        with self.assertRaises(ValidationError):
            save_page(actor=self.staff, space_id=self.space.pk, page_id=separate.pk,
                expected_version=separate.version, title=separate.title, parent=parent.parent)
        separate.refresh_from_db()
        self.assertIsNone(separate.parent_id)

    def test_sidebar_and_breadcrumbs_display_nested_pages(self):
        child = save_page(actor=self.staff, space_id=self.space.pk, title='Switch-Konfiguration', parent=self.page)
        response = self.client.get(child.get_absolute_url())
        self.assertEqual([item.pk for item in response.context['ancestors']], [self.page.pk])
        self.assertEqual([row['depth'] for row in response.context['tree']], [0, 1])
        self.assertContains(response, self.page.get_absolute_url())

    def test_space_creation_editing_and_optimistic_conflict(self):
        space = save_space(actor=self.other, name='Einlass', description='Abläufe')
        edited = save_space(actor=self.staff, space_id=space.pk, expected_version=1, name='Check-in')
        self.assertEqual(edited.version, 2)
        with self.assertRaises(EditConflict):
            save_space(actor=self.other, space_id=space.pk, expected_version=1, name='Stale')
        response = self.client.post(reverse('knowledge:space_create'), {
            'name': 'Turnierleitung', 'description': '', 'event': '', 'expected_version': 0})
        self.assertEqual(response.status_code, 302)

    def test_search_and_event_filters_use_accessible_current_documents(self):
        now = timezone.now()
        event = Event.objects.create(title='LAN Knowledge', start_date=now, end_date=now+timedelta(days=1))
        event_space = save_space(actor=self.staff, name='LAN Netz', event=event)
        page = save_page(actor=self.staff, space_id=event_space.pk, title='Switch', content='<p>VLAN 30</p>', publish=True)
        response = self.client.get(reverse('knowledge:home'), {'q': 'VLAN', 'scope': event.pk})
        self.assertEqual([item.pk for item in response.context['results']], [page.pk])
        response = self.client.get(reverse('knowledge:home'), {'q': 'VLAN', 'scope': 'global'})
        self.assertEqual([item.pk for item in response.context['results']], [self.page.pk])

    def test_search_and_history_have_pagination(self):
        for number in range(31):
            save_page(actor=self.staff, space_id=self.space.pk, title=f'Paginated {number}')
        response = self.client.get(reverse('knowledge:home'), {'q': 'Paginated'})
        self.assertEqual(len(response.context['results']), 30)
        self.assertTrue(response.context['results'].has_next())
        for number in range(26):
            self.edit(note=f'Change {number}')
        response = self.client.get(reverse('knowledge:history', args=[self.page.pk]))
        self.assertEqual(len(response.context['revisions']), 25)

    def test_sanitizer_removes_scripts_handlers_and_external_images_but_keeps_private_images(self):
        attachment = self.upload()
        content = f'<script>alert(1)</script><p onclick="evil()">Text &amp; mehr</p><a href="java&#115;cript:evil()">Bad</a><img src="https://external.example/track.png"><img src="{attachment.image_url}" onerror="evil()" alt="Plan"><table><tr><td colspan="2">Switch</td></tr></table>'
        page = self.edit(content=content, publish=True)
        self.assertNotIn('<script', page.content)
        self.assertNotIn('onclick', page.content)
        self.assertNotIn('onerror', page.content)
        self.assertNotIn('external.example', page.content)
        self.assertNotIn('javascript', page.content)
        self.assertIn(attachment.image_url, page.content)
        self.assertIn('colspan="2"', page.content)
        self.assertIn('Text & mehr', content_text(page.content))
        self.assertEqual(sanitize_content(page.content), page.content)

    def test_revision_diff_and_title_are_escaped(self):
        page = self.edit(title='<img src=x onerror=evil()>', content='<p>&lt;script&gt;evil&lt;/script&gt;</p>')
        revision = page.revisions.first()
        response = self.client.get(reverse('knowledge:revision', args=[page.pk, revision.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<img src=x')
        self.assertContains(response, '&lt;img src=x')
        self.assertNotContains(response, '<script>evil')

    def test_first_revision_comparison_defaults_to_empty_original(self):
        revision = self.page.revisions.first()
        response = self.client.get(reverse('knowledge:revision', args=[self.page.pk, revision.pk]))
        self.assertIsNone(response.context['previous'])
        self.assertContains(response, '<option value="" selected>')
        self.assertIn('--- Version 0', response.context['diff'])

    def test_attachment_is_stored_outside_media_and_can_only_be_downloaded_by_staff(self):
        attachment = self.upload()
        self.assertTrue(Path(attachment.file.path).is_relative_to(Path(self.private_root)))
        with self.assertRaises(ValueError):
            _ = attachment.file.url
        response = self.client.get(attachment.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Disposition'].startswith('attachment;'))
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 test')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('private', response['Cache-Control'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(attachment.get_absolute_url()).status_code, 403)

    def test_real_image_upload_and_inline_response(self):
        stream = BytesIO()
        Image.new('RGB', (12, 12), 'blue').save(stream, format='PNG')
        attachment = self.upload('plan.png', stream.getvalue())
        self.assertTrue(attachment.is_image)
        self.assertEqual(attachment.mime_type, 'image/png')
        response = self.client.get(attachment.image_url)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertTrue(response['Content-Disposition'].startswith('inline;'))
        self.assertEqual(b''.join(response.streaming_content), stream.getvalue())

    def test_dangerous_corrupt_oversized_and_mislabeled_uploads_are_rejected(self):
        stream = BytesIO()
        Image.new('RGB', (12, 12)).save(stream, format='PNG')
        for name, data in [('evil.html', b'<script>evil</script>'), ('evil.svg', b'<svg/>'),
            ('bad.png', b'not an image'), ('wrong.jpg', stream.getvalue()), ('big.pdf', b'x'*(10*1024*1024+1))]:
            with self.subTest(name=name):
                form = AttachmentForm(files={'file': SimpleUploadedFile(name, data)})
                self.assertFalse(form.is_valid())
        self.assertFalse(KnowledgeAttachment.objects.exists())

    def test_ajax_upload_keeps_private_url_and_returns_validation_errors(self):
        response = self.client.post(reverse('knowledge:upload', args=[self.page.pk]),
            {'file': SimpleUploadedFile('readme.md', b'Instructions')}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['location'].startswith('/knowledge/attachments/'))
        self.assertNotIn('/media/', response.json()['location'])
        response = self.client.post(reverse('knowledge:upload', args=[self.page.pk]),
            {'file': SimpleUploadedFile('evil.html', b'<script/>')}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_failed_attachment_database_save_cleans_up_private_file(self):
        form = AttachmentForm(files={'file': SimpleUploadedFile('failed.pdf', b'pdf')})
        self.assertTrue(form.is_valid())
        with patch.object(KnowledgeAttachment, 'save', side_effect=RuntimeError('Database failed')):
            with self.assertRaises(RuntimeError):
                upload_attachment(actor=self.staff, page_id=self.page.pk, upload=form.cleaned_data['file'], metadata=form.metadata)
        self.assertEqual(list(Path(self.private_root).rglob('*.pdf')), [])

    def test_files_keep_same_links_after_restoring_old_document_version(self):
        attachment = self.upload()
        page = self.edit(content=f'<p><a href="{attachment.get_absolute_url()}">Plan</a></p>', publish=True)
        revision = page.revisions.first()
        page = self.edit(content='<p>Andere Version</p>', publish=True)
        restore_revision(actor=self.staff, page_id=page.pk, revision_id=revision.pk, expected_version=page.version)
        response = self.client.get(attachment.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 test')

    def test_missing_attachment_is_404(self):
        attachment = self.upload()
        attachment.file.storage.delete(attachment.file.name)
        self.assertEqual(self.client.get(attachment.get_absolute_url()).status_code, 404)

    def test_private_root_cannot_be_inside_public_media(self):
        from django.conf import settings
        with override_settings(PRIVATE_MEDIA_ROOT=Path(settings.MEDIA_ROOT)/'secret'):
            self.assertEqual(private_storage_check(None)[0].id, 'knowledge.E001')

    def test_all_html_views_render_and_disable_browser_caching(self):
        revision = self.page.revisions.first()
        endpoints = [('knowledge:home', []), ('knowledge:space', [self.space.pk]),
            ('knowledge:space_create', []), ('knowledge:space_edit', [self.space.pk]),
            ('knowledge:create', [self.space.pk]), ('knowledge:page', [self.page.pk]),
            ('knowledge:edit', [self.page.pk]), ('knowledge:history', [self.page.pk]),
            ('knowledge:revision', [self.page.pk, revision.pk])]
        for name, args in endpoints:
            with self.subTest(endpoint=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertIn('no-store', response['Cache-Control'])
                self.assertIn('Cookie', response['Vary'])

    def test_writes_require_post_and_csrf(self):
        revision = self.page.revisions.first()
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.staff)
        for name, args in [('knowledge:publish', [self.page.pk]), ('knowledge:restore', [self.page.pk, revision.pk]), ('knowledge:upload', [self.page.pk])]:
            with self.subTest(endpoint=name):
                self.assertEqual(strict.post(reverse(name, args=args), {'expected_version': 1}).status_code, 403)
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 405)

    def test_navigation_seed_is_staff_only_and_not_visible_to_guests(self):
        call_command('seed_features', verbosity=0)
        item = NavigationItem.objects.get(url_name='knowledge:home')
        self.assertEqual(item.visibility, NavigationItem.Visibility.STAFF)
        response = self.client.get(reverse('knowledge:home'))
        self.assertIn(item.pk, [nav.pk for nav in response.context['nav_items']])
        self.client.force_login(self.guest)
        response = self.client.get(reverse('dashboard'))
        self.assertNotIn(item.pk, [nav.pk for nav in response.context['nav_items']])

    def test_frontend_invalid_actions_and_inputs_show_errors_without_writing(self):
        for data in ({'title': 'x', 'order': 0, 'expected_version': 1, 'action': 'delete'},
            {'title': 'x', 'order': 0, 'expected_version': 'invalid', 'action': 'draft'},
            {'title': 'x', 'order': -1, 'expected_version': 1, 'action': 'draft'}):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(reverse('knowledge:edit', args=[self.page.pk]), data).status_code, 400)
        self.page.refresh_from_db()
        self.assertEqual(self.page.version, 1)
