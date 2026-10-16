import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from configuration.runtime import check_runtime


class Command(BaseCommand):
    help = 'Prüft Datenbank, Migrationen, Cache, Backup-Tools und optional einen Healthcheck-Host.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--health-host')
        parser.add_argument('--require-redis', action='store_true')
        parser.add_argument('--json', action='store_true', dest='as_json')

    def handle(self, *args, **options):
        checks = check_runtime(health_host=options['health_host'],
                               require_redis=options['require_redis'] or not settings.DEBUG)
        if options['as_json']:
            self.stdout.write(json.dumps(checks, ensure_ascii=False))
        else:
            for name, result in checks.items():
                self.stdout.write(f"{'OK' if result['ok'] else 'FEHLER'} {name}: {result['detail']}")
        if not all(result['ok'] for result in checks.values()):
            raise CommandError('Laufzeitprüfung fehlgeschlagen; keine Anwendungskonfiguration geändert.')
