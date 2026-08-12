from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.cache import cache


class Command(BaseCommand):
    help = 'Setzt das System auf die vordefinierten Demo-Daten aus initial_data.json zurück.'

    def handle(self, *args, **options):
        self.stdout.write('Starte Zurücksetzen der Demo-Daten...')
        cache.clear()

        try:
            call_command('loaddata', 'initial_data.json')
            self.stdout.write(self.style.SUCCESS('✓ Demo-Daten aus initial_data.json erfolgreich geladen.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Fehler beim Laden von initial_data.json: {e}'))

        call_command('seed_translations')
        call_command('seed_features')

        self.stdout.write(self.style.SUCCESS('🎉 Demo-Daten und System-Einstellungen wurden erfolgreich zurückgesetzt.'))
