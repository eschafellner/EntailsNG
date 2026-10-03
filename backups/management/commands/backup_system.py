from django.core.management.base import BaseCommand, CommandError
from backups import services, storage
from backups.errors import BackupError
from backups.locking import FileLock


class Command(BaseCommand):
    help = 'CLI für vollständige Backups und Wiederherstellung bei nicht erreichbarem Backend.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('action', choices=('create', 'prepare', 'restore', 'list', 'recover'))
        parser.add_argument('--id')
        parser.add_argument('--description', default='')
        parser.add_argument('--confirm-replace', action='store_true')
        parser.add_argument('--file')

    def handle(self, *args, **options):
        try:
            storage.initialize()
            if options['action'] == 'list':
                for record in storage.list_records():
                    self.stdout.write(f"{record['id']} {record['created_at']} {record['state']} {record.get('description', '')}")
                return
            with FileLock('worker.lock'):
                services.recover_interrupted()
                if options['action'] == 'recover':
                    if any(job['state'] == 'recovery_required' for job in storage.list_records('jobs')):
                        raise CommandError('Rücksetzung fehlgeschlagen; Wartungsmodus bleibt aktiv.')
                    return
                if options['action'] == 'restore' and not options['confirm_replace']:
                    raise CommandError('Wiederherstellung benötigt --confirm-replace.')
                if options['file']:
                    if options['action'] != 'prepare':
                        raise CommandError('--file wird nur mit prepare unterstützt.')
                    from django.core.files import File
                    with open(options['file'], 'rb') as stream:
                        job = services.upload_backup(File(stream), actor='CLI')
                else:
                    job = services.enqueue(options['action'], actor='CLI', record_id=options['id'],
                                           description=options['description'])
                services.process_next()
                result = storage.load('jobs', job['id'])
                if result['state'] != 'completed':
                    raise CommandError(result.get('error', result['state']))
                self.stdout.write(result.get('result_id', result['id']))
        except BackupError as exc:
            raise CommandError(str(exc)) from None
