from django.core.management.base import BaseCommand
from emails.models import EmailTemplate, GeneralEmailSettings


class Command(BaseCommand):
    help = "Erstellt die Standard E-Mail Einstellungen und das Zahlungsbestätigungs-Template"

    def handle(self, *args, **options):
        # 1. Allgemeine Einstellungen initialisieren
        settings = GeneralEmailSettings.load()
        self.stdout.write(self.style.SUCCESS(f"Allgemeine E-Mail Einstellungen bereit: {settings}"))

        # 2. Template "Zahlungsbestätigung" anlegen oder aktualisieren
        payment_template, created = EmailTemplate.objects.get_or_create(
            key='payment_confirmation',
            defaults={
                'name': 'Zahlungsbestätigung',
                'subject': 'Zahlungseingang bestätigt für {event_title}',
                'content': '''<h2>Zahlungsbestätigung</h2>
<p>Hallo <strong>{full_name}</strong>,</p>
<p>vielen Dank! Deine Zahlung für die Veranstaltung <strong>{event_title}</strong> wurde erfolgreich verbucht.</p>
<div style="background: #1e293b; color: #ffffff; padding: 16px; border-radius: 8px; margin: 16px 0;">
  <p><strong>Veranstaltung:</strong> {event_title}</p>
  <p><strong>Ticket:</strong> {ticket_type}</p>
  <p><strong>Verwendungszweck / Referenz:</strong> {payment_reference}</p>
  <p><strong>Sitzplatz:</strong> {seat_label}</p>
  <p><strong>Bezahlter Betrag:</strong> {amount} €</p>
</div>
<p>Dein Sitzplatz ist nun fest für dich reserviert. Wir freuen uns auf dich auf der LAN-Party!</p>
<p>Viele Grüße,<br>Dein EntailsNG Event Team</p>''',
                'is_active': True,
                'placeholder_info': '''Verfügbare Platzhalter für diese Vorlage:
- {username}: Benutzername des Teilnehmers
- {full_name}: Vor- und Nachname (oder Benutzername)
- {event_title}: Name der Veranstaltung
- {amount}: Bezahlter Betrag in Euro
- {payment_reference}: Zahlungs-Referenzcode
- {seat_label}: Zugewiesene Sitzplatznummer
- {ticket_type}: Name der gewählten Ticket-Kategorie''',
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS("E-Mail-Template 'Zahlungsbestätigung' wurde erfolgreich erstellt."))
        else:
            self.stdout.write(self.style.SUCCESS("E-Mail-Template 'Zahlungsbestätigung' existiert bereits."))
