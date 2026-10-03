import time

from django.core.management.base import BaseCommand, CommandError
from backups import services, storage
from backups.errors import BackupError
from backups.locking import FileLock


class Command(BaseCommand):
    help = 'Verarbeitet Backup-Aufträge und setzt unterbrochene Wiederherstellungen zurück.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--daemon', action='store_true')
        parser.add_argument('--interval', type=float, default=2)

    def handle(self, *args, **options):
        if options['interval'] <= 0:
            raise CommandError('--interval muss positiv sein.')
        try:
            storage.encryption_key()
            with FileLock('worker.lock'):
                services.recover_interrupted()
                self.stdout.write('Backup-Worker bereit.')
                while True:
                    services.process_next()
                    if not options['daemon']:
                        return
                    time.sleep(options['interval'])
        except BackupError as exc:
            raise CommandError(str(exc)) from None
        except KeyboardInterrupt:
            self.stdout.write('Backup-Worker beendet. Unterbrochene Aufträge werden beim nächsten Start geprüft.')
