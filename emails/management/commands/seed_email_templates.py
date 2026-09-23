from django.core.management.base import BaseCommand
from emails.defaults import DEFAULT_EMAIL_TEMPLATES
from emails.models import EmailTemplate, GeneralEmailSettings


class Command(BaseCommand):
    help = "Erstellt die Standard E-Mail Einstellungen und alle Standard E-Mail-Templates"

    def handle(self, *args, **options):
        # 1. Allgemeine Einstellungen initialisieren
        settings = GeneralEmailSettings.load()
        self.stdout.write(self.style.SUCCESS(f"Allgemeine E-Mail Einstellungen bereit: {settings}"))

        # 2. Alle Standard-Templates anlegen oder aktualisieren
        created_count = 0
        for key, tpl_data in DEFAULT_EMAIL_TEMPLATES.items():
            _, created = EmailTemplate.objects.get_or_create(
                key=key,
                defaults=tpl_data,
            )
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f"Alle Standard E-Mail-Templates sind auf dem neuesten Stand ({created_count} neu angelegt)."))

