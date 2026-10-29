from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from configuration.models import SystemErrorLog


class Command(BaseCommand):
    help = (
        'Löscht Einträge des System-Fehlerprotokolls, deren letztes Auftreten länger als die '
        'Aufbewahrungsfrist (SYSTEM_ERROR_LOG_RETENTION_DAYS) zurückliegt.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=None,
                            help='Aufbewahrungsfrist in Tagen (Standard: SYSTEM_ERROR_LOG_RETENTION_DAYS).')
        parser.add_argument('--dry-run', action='store_true', help='Nur zählen, nichts löschen.')

    def handle(self, *args, **options):
        days = settings.SYSTEM_ERROR_LOG_RETENTION_DAYS if options['days'] is None else options['days']
        if days < 1:
            raise CommandError('Die Aufbewahrungsfrist muss mindestens einen Tag betragen.')
        count = SystemErrorLog.purge_expired(days=days, dry_run=options['dry_run'])
        verb = 'gefunden' if options['dry_run'] else 'gelöscht'
        self.stdout.write(self.style.SUCCESS(f'Fehlerprotokolle älter als {days} Tage {verb}: {count}'))
