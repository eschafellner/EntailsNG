"""Real row-lock verification, run by the PostgreSQL CI job."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature

from .models import KnowledgeSpace
from .services import save_page, publish_page, EditConflict


@skipUnlessDBFeature('has_select_for_update')
class KnowledgeConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.first = get_user_model().objects.create_user('knowledge-lock-first', is_staff=True)
        self.second = get_user_model().objects.create_user('knowledge-lock-second', is_staff=True)
        self.space = KnowledgeSpace.objects.create(name='Concurrent knowledge')
        self.page = save_page(actor=self.first, space_id=self.space.pk, title='Original', content='<p>Original</p>', publish=True)

    @staticmethod
    def connection_for(action):
        close_old_connections()
        try:
            return action()
        finally:
            connections.close_all()

    def compete(self, first_action, second_action):
        paused, proceed, entered = Event(), Event(), Event()
        def first():
            with transaction.atomic():
                value = first_action()
                paused.set()
                if not proceed.wait(10):
                    raise RuntimeError('Knowledge concurrency timed out')
                return value
        def second():
            entered.set()
            return second_action()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_result = pool.submit(self.connection_for, first)
            self.assertTrue(paused.wait(10))
            second_result = pool.submit(self.connection_for, second)
            self.assertTrue(entered.wait(10))
            try:
                with self.assertRaises(TimeoutError):
                    second_result.result(timeout=.2)
            finally:
                proceed.set()
            first_result.result(timeout=10)
            return second_result.result(timeout=10)

    def edit(self, actor, **kwargs):
        return save_page(actor=actor, space_id=self.space.pk, page_id=self.page.pk,
            expected_version=1, title='Updated', **kwargs)

    def test_parallel_edits_do_not_overwrite_first_committed_revision(self):
        with self.assertRaises(EditConflict):
            self.compete(lambda: self.edit(self.first, content='<p>First writer</p>'),
                lambda: self.edit(self.second, content='<p>Second writer</p>'))
        self.page.refresh_from_db()
        self.assertEqual(self.page.content, '<p>First writer</p>')
        self.assertEqual(self.page.revisions.count(), 2)
        self.assertEqual(self.page.published_revision.content, '<p>Original</p>')

    def test_publish_rejects_version_changed_by_waited_on_editor(self):
        with self.assertRaises(EditConflict):
            self.compete(lambda: self.edit(self.first, content='<p>Unpublished</p>'),
                lambda: publish_page(actor=self.second, page_id=self.page.pk, expected_version=1))
        self.page.refresh_from_db()
        self.assertEqual(self.page.published_revision.content, '<p>Original</p>')
        self.assertEqual(self.page.version, 2)

    def test_parallel_reparenting_cannot_create_cycle(self):
        other = save_page(actor=self.first, space_id=self.space.pk, title='Other root')
        with self.assertRaises(ValidationError):
            self.compete(lambda: self.edit(self.first, parent=other),
                lambda: save_page(actor=self.second, space_id=self.space.pk, page_id=other.pk,
                    expected_version=1, title=other.title, parent=self.page))
        self.page.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.page.parent_id, other.pk)
        self.assertIsNone(other.parent_id)
