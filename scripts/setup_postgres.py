#!/usr/bin/env python3
"""Initialize PostgreSQL schema and system seeds; optionally create synthetic demo data."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true')
    options = parser.parse_args()
    os.chdir(Path(__file__).resolve().parent.parent)
    for command in ('migrate', 'seed_translations', 'seed_features', 'seed_email_templates'):
        subprocess.run([sys.executable, 'manage.py', command], check=True)
    if options.demo:
        subprocess.run([sys.executable, 'manage.py', 'seed_demo_data'],
                       env={**os.environ, 'DEMO_MODE': 'True'}, check=True)
    print('Setup abgeschlossen. Administrator mit python manage.py createsuperuser anlegen.')


if __name__ == '__main__':
    main()
