from django.core.management.base import BaseCommand

from configuration.context_processors import DEFAULT_TEXTS
from configuration.models import SystemTranslation


class Command(BaseCommand):
    help = 'Legt fehlende Übersetzungsschlüssel in der Datenbank an.'

    def handle(self, *args, **options):
        created_count = 0
        for key, text in DEFAULT_TEXTS.items():
            _, created = SystemTranslation.objects.get_or_create(
                key=key, defaults={'text': text}
            )
            if created:
                created_count += 1
                self.stdout.write(f'Angelegt: {key}')

        self.stdout.write(
            self.style.SUCCESS(f'{created_count} Schlüssel angelegt.')
        )
