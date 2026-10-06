"""Reproduzierbarer Lasttest auf einer ausdrücklich freigegebenen Wegwerf-Datenbank.

Aufruf: ENTAILS_PERF_TEST=1 DB_NAME=entails_perf_db \
    .venv/bin/python scripts/performance_smoke.py --label baseline

Erzeugt je Größe eine neue Veranstaltung mit Testkonten. Diese Datenbank darf
keine echten Veranstaltungsdaten enthalten. Die Messwerte sind lokale
Vergleichswerte, keine Zusage für einen Produktionsserver.
"""

import argparse
import json
import os
import statistics
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import close_old_connections, connection  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from events.models import Event, TicketType  # noqa: E402
from events.services import RegistrationService  # noqa: E402


def percentile(values, percent):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percent))], 2)


def timed_registration(user, event_id, ticket_id):
    close_old_connections()
    start = time.perf_counter()
    try:
        RegistrationService.register_user(user, event_id, ticket_id)
        return (time.perf_counter() - start) * 1000, None
    except Exception as exc:
        return (time.perf_counter() - start) * 1000, repr(exc)
    finally:
        close_old_connections()


def sample_lock_waits(stop, samples):
    """Zählt eigene PostgreSQL-Sessions, die gerade auf eine Sperre warten."""
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
    parser.add_argument('--label', default='baseline')
    parser.add_argument('--sizes', default='50,250,1000')
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--sample-locks', action='store_true')
    args = parser.parse_args()
    db_name = settings.DATABASES['default']['NAME']
    if (os.environ.get('ENTAILS_PERF_TEST') != '1'
            or connection.vendor != 'postgresql'
            or 'perf' not in str(db_name).lower()):
        parser.error('Nur mit ENTAILS_PERF_TEST=1 auf einer PostgreSQL-Perf-Datenbank erlaubt.')

    User = get_user_model()
    marker = uuid.uuid4().hex[:10]
    staff = User.objects.create_user(username=f'perf_staff_{marker}', password=None, is_staff=True)
    client = Client(SERVER_NAME='localhost')
    client.force_login(staff)
    results = []
    for size in [int(item) for item in args.sizes.split(',')]:
        start_date = timezone.now() + timedelta(days=7)
        event = Event.objects.create(
            title=f'Perf LAN {marker} {size}', slug=f'perf-lan-{marker}-{size}',
            is_active=True, status=Event.Status.REGISTRATION_OPEN,
            start_date=start_date, end_date=start_date + timedelta(days=2),
            max_guests=size + 1,
        )
        ticket = TicketType.objects.create(event=event, name='Standard', price=0)
        users = User.objects.bulk_create([
            User(username=f'perf_{marker}_{size}_{i}', email=f'perf_{marker}_{size}_{i}@example.invalid', password='!')
            for i in range(size)
        ])
        lock_samples = []
        stop_sampling = threading.Event()
        sampler = None
        if args.sample_locks:
            sampler = threading.Thread(target=sample_lock_waits, args=(stop_sampling, lock_samples))
            sampler.start()
        start = time.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                measurements = list(pool.map(
                    lambda user: timed_registration(user, event.pk, ticket.pk), users
                ))
        finally:
            stop_sampling.set()
            if sampler:
                sampler.join()
        wall_seconds = round(time.perf_counter() - start, 2)
        latencies = [value for value, error in measurements if error is None]
        errors = [error for value, error in measurements if error is not None]

        # Warmup: Template-Laden und einmalige Caches nicht in die Seitenzeit nehmen.
        url = reverse('checkin_scanner')
        client.get(url)
        scanner_samples = []
        response_bytes = 0
        for _ in range(3):
            start = time.perf_counter()
            response = client.get(url)
            scanner_samples.append((time.perf_counter() - start) * 1000)
            response_bytes = len(response.content)
            if response.status_code != 200:
                raise RuntimeError(f'Scanner antwortete mit {response.status_code}')
        result = {
            'size': size, 'workers': args.workers,
            'registration_wall_s': wall_seconds,
            'registration_p50_ms': percentile(latencies, .5) if latencies else None,
            'registration_p95_ms': percentile(latencies, .95) if latencies else None,
            'registration_max_ms': round(max(latencies), 2) if latencies else None,
            'registration_errors': len(errors), 'first_error': errors[0] if errors else None,
            'max_lock_waiters': max(lock_samples, default=None),
            'lock_wait_samples': sum(waiters > 0 for waiters in lock_samples),
            'lock_samples': len(lock_samples),
            'scanner_median_ms': round(statistics.median(scanner_samples), 2),
            'scanner_bytes': response_bytes,
        }
        print(json.dumps(result), flush=True)
        results.append(result)
    print(json.dumps({'label': args.label, 'database': db_name, 'results': results}, indent=2))


if __name__ == '__main__':
    main()
