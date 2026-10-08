from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, override_settings

from emails.models import OutgoingEmail
from .tests import ContactFixtures


class ContactConcurrencyTests(ContactFixtures, TransactionTestCase):
    def run_parallel(self, calls):
        barrier = Barrier(len(calls))

        def run(call):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return call()
            except ValidationError:
                return 'rejected'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            return list(pool.map(run, calls))

    def test_same_form_submitted_concurrently_creates_one_batch(self):
        request, token = self.contact_request()
        results = self.run_parallel([lambda: self.submit(request, token)] * 2)
        self.assertEqual([row.pk for row in results[0]], [row.pk for row in results[1]])
        self.assertEqual(OutgoingEmail.objects.count(), 2)

    def test_parallel_forms_for_same_sender_cannot_bypass_cooldown(self):
        requests = [self.contact_request() for _ in range(2)]
        results = self.run_parallel([lambda item=item: self.submit(*item) for item in requests])
        self.assertEqual(results.count('rejected'), 1)
        self.assertEqual(OutgoingEmail.objects.count(), 2)

    @override_settings(CONTACT_MAX_PER_IP_TEN_MINUTES=1)
    def test_parallel_senders_on_same_ip_cannot_bypass_ip_limit(self):
        requests = [self.contact_request() for _ in range(2)]
        results = self.run_parallel([
            lambda item=item, index=index: self.submit(*item, email=f'guest{index}@example.com')
            for index, item in enumerate(requests)
        ])
        self.assertEqual(results.count('rejected'), 1)
        self.assertEqual(OutgoingEmail.objects.count(), 2)
