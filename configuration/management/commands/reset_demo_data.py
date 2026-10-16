from configuration.management.commands.seed_demo_data import Command as SeedDemoCommand


class Command(SeedDemoCommand):
    help = 'Veralteter Alias für seed_demo_data; löscht keine vorhandenen Daten.'

    def handle(self, *args, **options):
        self.stderr.write('reset_demo_data ist veraltet; bitte seed_demo_data verwenden. Es erfolgt kein Reset.')
        return super().handle(*args, **options)
