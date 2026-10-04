import logging
import time

from django.core.management.base import BaseCommand
from django.db import connections
from backups.errors import BackupError
from backups.locking import access_guard
from seating.clan_services import process_clan_holds

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Gibt abgelaufene Clan-Vormerkungen frei und löst Erinnerungs- und Ablaufmails aus.'

    def add_arguments(self, parser):
        parser.add_argument('--daemon', action='store_true')
        parser.add_argument('--interval', type=int, default=60)

    def handle(self, *args, **options):
        if options['interval'] < 1:
            from django.core.management.base import CommandError
            raise CommandError('Das Intervall muss mindestens eine Sekunde betragen.')
        while True:
            try:
                with access_guard():
                    process_clan_holds()
            except BackupError:
                if not options['daemon']:
                    raise
            except Exception:
                if not options['daemon']:
                    raise
                logger.exception('Verarbeitung der Clan-Vormerkungen fehlgeschlagen; nächster Durchlauf folgt.')
            finally:
                connections.close_all()
            if not options['daemon']:
                self.stdout.write(self.style.SUCCESS('Clan-Vormerkungen verarbeitet.'))
                return
            try:
                time.sleep(options['interval'])
            except KeyboardInterrupt:
                return
