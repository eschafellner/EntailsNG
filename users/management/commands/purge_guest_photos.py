import logging
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from backups.errors import BackupError
from backups.locking import access_guard
from users.services import GuestPhotoService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Löscht Gastfotos nach Ablauf der Frist sowie verwaiste Fotodateien und Datensätze.'

    def add_arguments(self, parser):
        parser.add_argument('--daemon', action='store_true')
        parser.add_argument('--interval', type=int, default=3600)
        parser.add_argument('--dry-run', action='store_true', help='Nur zählen, nichts löschen.')

    def handle(self, *args, **options):
        if options['interval'] < 1:
            raise CommandError('Das Intervall muss mindestens eine Sekunde betragen.')
        while True:
            try:
                with access_guard():
                    result = GuestPhotoService.purge(dry_run=options['dry_run'])
                if not options['daemon'] or any(result.values()):
                    message = (
                        f"Gastfotos {'gefunden' if options['dry_run'] else 'gelöscht'}: "
                        f"{result['expired']} abgelaufen, {result['missing_files']} ohne Datei, "
                        f"{result['orphan_files']} Dateien ohne Datensatz."
                    )
                    if options['daemon']:
                        logger.info(message)
                    else:
                        self.stdout.write(self.style.SUCCESS(message))
            except BackupError:
                if not options['daemon']:
                    raise
            except Exception:
                if not options['daemon']:
                    raise
                logger.exception('Bereinigung der Gastfotos fehlgeschlagen; nächster Durchlauf folgt.')
            finally:
                connections.close_all()
            if not options['daemon']:
                return
            try:
                time.sleep(options['interval'])
            except KeyboardInterrupt:
                return
