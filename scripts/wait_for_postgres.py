"""Check the configured PostgreSQL database before installing or starting locally."""
import argparse
import os
from pathlib import Path
import sys
import time

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from django.conf import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    config = settings.DATABASES['default']
    deadline = time.monotonic() + max(0, args.timeout)
    while True:
        try:
            with psycopg.connect(
                dbname=config['NAME'], user=config['USER'], password=config['PASSWORD'],
                host=config['HOST'], port=config['PORT'], connect_timeout=2,
            ):
                print('PostgreSQL ist erreichbar.')
                return 0
        except psycopg.OperationalError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print('PostgreSQL ist nicht erreichbar. Bitte DB_NAME, DB_USER, DB_PASSWORD, '
                      'DB_HOST und DB_PORT prüfen und PostgreSQL starten.', file=sys.stderr)
                return 1
            time.sleep(min(1, remaining))


if __name__ == '__main__':
    sys.exit(main())
