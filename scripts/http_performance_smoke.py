#!/usr/bin/env python3
"""HTTP workloads through Nginx/Gunicorn, only on an explicitly selected disposable DB."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
import platform
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def percentile(values, percent):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percent))], 2)


def sample_lock_waits(stop, samples):
    """Zählt eigene PostgreSQL-Sessions, die gerade auf eine Sperre warten."""
    from django.db import connection
    try:
        while not stop.is_set():
            with connection.cursor() as cursor:
                cursor.execute('''
                    SELECT count(*) FROM pg_stat_activity
                    WHERE datname = current_database() AND usename = current_user
                      AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()
                ''')
                samples.append(cursor.fetchone()[0])
            stop.wait(.005)
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--sizes', default='50,250,1000')
    parser.add_argument('--concurrency', default='1,12,32')
    parser.add_argument('--samples', type=int, default=32)
    options = parser.parse_args()
    target = urllib.parse.urlsplit(options.base_url)
    if (os.environ.get('ENTAILS_PERF_TEST') != '1'
            or not os.environ.get('DB_NAME', '').startswith('entails_smoke_')
            or target.scheme not in ('http', 'https') or target.username or target.password
            or target.hostname not in ('nginx', 'localhost', '127.0.0.1')
            or not 2 <= options.samples <= 100):
        parser.error('Nur auf ausdrücklicher Wegwerf-DB entails_smoke_* und lokalem Testproxy erlaubt.')
    sizes = [int(x) for x in options.sizes.split(',')]
    concurrencies = [int(x) for x in options.concurrency.split(',')]
    if not all(1 <= x <= 1000 for x in sizes) or not all(1 <= x <= 64 for x in concurrencies):
        parser.error('Größen 1..1000 und Parallelität 1..64 verwenden.')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.db import connection
    from django.test import Client
    from django.utils import timezone
    from backups.database import software_fingerprint
    from events.models import Event, TicketType, EventRegistration
    from seating.models import SeatingPlan, SeatingCell

    if connection.vendor != 'postgresql':
        raise RuntimeError('PostgreSQL required')
    User = get_user_model()
    marker = secrets.token_hex(6)
    staff = User.objects.create_user(f'http_staff_{marker}', f'http_staff_{marker}@example.invalid',
                                    None, is_staff=True)

    def cookies(user):
        client = Client()
        client.force_login(user)
        return client.cookies[settings.SESSION_COOKIE_NAME].value

    staff_session = cookies(staff)

    def request(path, session, payload, *, form=False):
        csrf = secrets.token_hex(16)
        body = urllib.parse.urlencode(payload).encode() if form else json.dumps(payload).encode()
        headers = {'Host': 'localhost', 'X-Forwarded-Proto': 'https', 'Origin': 'https://localhost',
                   'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json',
                   'Cookie': f'{settings.SESSION_COOKIE_NAME}={session}; {settings.CSRF_COOKIE_NAME}={csrf}'}
        started = time.perf_counter()
        try:
            opener = urllib.request.build_opener(NoRedirect)
            req = urllib.request.Request(options.base_url.rstrip('/') + path, body, headers)
            try:
                response = opener.open(req, timeout=30)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                return (time.perf_counter() - started) * 1000, response.code
        except (OSError, TimeoutError):
            return (time.perf_counter() - started) * 1000, 0

    def measure(work, workers):
        waits, stop = [], threading.Event()
        sampler = threading.Thread(target=sample_lock_waits, args=(stop, waits))
        sampler.start()
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                rows = list(pool.map(lambda action: action(), work))
        finally:
            stop.set()
            sampler.join(timeout=15)
        latencies = [row[0] for row in rows]
        return {'p50_ms': percentile(latencies, .50), 'p95_ms': percentile(latencies, .95),
                'p99_ms': percentile(latencies, .99), 'max_lock_waiters': max(waits, default=0),
                'statuses': {str(status): sum(row[1] == status for row in rows) for _, status in rows}}

    results = []
    for size in sizes:
        for workers in concurrencies:
            now = timezone.now()
            event = Event.objects.create(title=f'HTTP smoke {marker} {size}/{workers}',
                start_date=now + timedelta(days=7), end_date=now + timedelta(days=9),
                status=Event.Status.REGISTRATION_OPEN, is_active=True, max_guests=size + options.samples + 1,
                allow_unpaid_seat_overwrite=False)
            ticket = TicketType.objects.create(event=event, name='Free smoke', price=0)
            prefix = f'http_{marker}_{size}_{workers}'
            # Event registration requires a real name.
            baseline = User.objects.bulk_create([User(username=f'{prefix}_base_{i}',
                email=f'{prefix}_base_{i}@example.invalid', password='!',
                first_name='Smoke', last_name=f'Base {i}') for i in range(size)])
            EventRegistration.objects.bulk_create([EventRegistration(user=u, event=event, ticket_type=ticket,
                booking_price=0) for u in baseline])
            guests = User.objects.bulk_create([User(username=f'{prefix}_new_{i}',
                email=f'{prefix}_new_{i}@example.invalid', password='!',
                first_name='Smoke', last_name=f'Guest {i}') for i in range(options.samples)])
            sessions = [cookies(user) for user in guests]
            # Warm templates and caches without an extra registration.
            urllib.request.build_opener().open(urllib.request.Request(
                options.base_url.rstrip('/') + '/login/', headers={'Host': 'localhost', 'X-Forwarded-Proto': 'https'}), timeout=15).close()
            registration = measure([lambda session=session: request(f'/register/{event.pk}/', session,
                {'ticket_type_id': ticket.pk}, form=True) for session in sessions], workers)
            actual = list(EventRegistration.objects.filter(event=event, user__in=guests).order_by('pk'))
            registration['errors'] = options.samples - len(actual) + sum(
                count for status, count in registration['statuses'].items() if status != '302')
            EventRegistration.objects.filter(pk__in=[r.pk for r in actual]).update(payment_status='PAID', paid_amount=0)
            plan = SeatingPlan.objects.create(event=event, name='Contention', columns=1, rows=1)
            seat = SeatingCell.objects.create(plan=plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT)
            seating = measure([lambda session=session: request(f'/seating/api/reserve/{event.pk}/',
                session, {'x': 1, 'y': 1}) for session in sessions], workers)
            seating['errors'] = sum(count for status, count in seating['statuses'].items() if status not in ('200', '400'))
            seating['expected_conflicts'] = options.samples - 1
            seat.refresh_from_db()
            seating['one_winner'] = seating['statuses'].get('200') == 1 and seat.registration_id is not None
            checkin = measure([lambda reg=reg: request('/api/check-in/toggle/', staff_session,
                {'registration_id': reg.pk}) for reg in actual], workers) if actual else {'errors': options.samples}
            if actual:
                checkin['errors'] = options.samples - EventRegistration.objects.filter(
                    pk__in=[r.pk for r in actual], is_checked_in=True).count()
                checkin['errors'] += sum(count for status, count in checkin['statuses'].items() if status != '200')
            results.append({'registered_guests_before': size, 'parallel_requests': workers,
                            'samples_per_scenario': options.samples, 'registration': registration,
                            'seat_contention': seating, 'checkin': checkin})
    report = {'transport': 'HTTP through Nginx/Gunicorn', 'source_fingerprint': software_fingerprint(),
              'python': sys.version.split()[0], 'django': django.get_version(),
              'postgresql': connection.pg_version, 'web_workers': os.environ.get('WEB_CONCURRENCY', 'unknown'),
              'machine': platform.machine(), 'logical_cpus_visible': os.cpu_count(),
              'thresholds': 'baseline only; no product latency SLA approved', 'results': results}
    print(json.dumps(report, indent=2))
    if any(row['registration']['errors'] or row['seat_contention']['errors']
           or not row['seat_contention']['one_winner'] or row['checkin']['errors'] for row in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
