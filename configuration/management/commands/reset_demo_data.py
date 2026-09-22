from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from configuration.cache import (
    invalidate_general_configuration_cache,
    invalidate_navigation_cache,
    invalidate_site_customization_cache,
    invalidate_system_translations_cache,
)


class Command(BaseCommand):
    help = 'Spielt die vordefinierten Demo-Daten aus initial_data.json transaktional ein und aktualisiert System-Einstellungen.'

    def handle(self, *args, **options):
        self.stdout.write('Starte Einspielen der Demo-Daten...')

        try:
            with transaction.atomic():
                call_command('loaddata', 'initial_data.json')
                self.stdout.write(self.style.SUCCESS('✓ Demo-Daten aus initial_data.json erfolgreich geladen.'))

                call_command('seed_translations')
                call_command('seed_features', reset=True)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Fehler beim Laden der Demo-Daten: {e}'))
            raise CommandError(f'Demo-Reset fehlgeschlagen: {e}') from e

        # Caches gezielt invalidieren
        invalidate_general_configuration_cache()
        invalidate_site_customization_cache()
        invalidate_navigation_cache()
        invalidate_system_translations_cache()

        self.stdout.write(self.style.SUCCESS('🎉 Demo-Daten und System-Einstellungen wurden erfolgreich geladen.'))

