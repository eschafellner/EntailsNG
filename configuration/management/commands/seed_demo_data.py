from django.core.management.base import BaseCommand, CommandError

from configuration.demo import DemoDataError, seed_demo_data


class Command(BaseCommand):
    help = 'Richtet synthetische Demo-Daten auf frischer Datenbank ein (DEMO_MODE=True).'

    def handle(self, *args, **options):
        try:
            created = seed_demo_data()
        except DemoDataError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(self.style.SUCCESS(
            'Demo-Daten eingerichtet. Eigenen Administrator mit createsuperuser anlegen.' if created
            else 'Demo bereits vollständig eingerichtet; keine Daten geändert.'))
