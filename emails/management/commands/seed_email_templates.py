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

        # 3. Template "Double Opt-In Verifizierung"
        EmailTemplate.objects.get_or_create(
            key='email_verification',
            defaults={
                'name': 'Double Opt-In E-Mail Verifizierung',
                'subject': 'Dein Bestätigungscode für EntailsNG: {code}',
                'content': '''<h2>Willkommen bei EntailsNG!</h2>
<p>Hallo <strong>{full_name}</strong>,</p>
<p>vielen Dank für deine Registrierung! Um deinen Account zu aktivieren, verwende bitte den folgenden 6-stelligen Bestätigungscode:</p>
<div style="background: #111827; border: 2px solid #0284c7; color: #38bdf8; padding: 20px; border-radius: 12px; font-size: 32px; font-weight: bold; font-family: monospace; letter-spacing: 8px; text-align: center; margin: 20px 0;">
  {code}
</div>
<p>Dieser Code ist <strong>{valid_minutes} Minuten</strong> lang gültig.</p>
<p>Falls du dieses Konto nicht erstellt hast, kannst du diese E-Mail einfach ignorieren.</p>
<p>Viele Grüße,<br>Dein EntailsNG Team</p>''',
                'is_active': True,
                'placeholder_info': '''Verfügbare Platzhalter für diese Vorlage:
- {username}: Benutzername des Teilnehmers
- {full_name}: Vor- und Nachname (oder Benutzername)
- {code}: 6-stelliger numerischer Verifizierungscode (z. B. 849201)
- {valid_minutes}: Gültigkeitsdauer in Minuten (z. B. 15)''',
            },
        )

        # 4. Template "Passwort zurücksetzen"
        EmailTemplate.objects.get_or_create(
            key='password_reset',
            defaults={
                'name': 'Passwort zurücksetzen',
                'subject': 'Passwort zurücksetzen für EntailsNG',
                'content': '''<h2>Passwort zurücksetzen</h2>
<p>Hallo <strong>{full_name}</strong>,</p>
<p>du hast das Zurücksetzen deines Passworts für deinen EntailsNG Account angefordert.</p>
<p>Klicke auf den folgenden Button, um ein neues Passwort festzulegen:</p>
<div style="text-align: center; margin: 24px 0;">
  <a href="{reset_link}" style="background: #0284c7; color: #ffffff; padding: 12px 24px; border-radius: 8px; font-weight: bold; text-decoration: none; display: inline-block;">
    🔑 Neues Passwort festlegen
  </a>
</div>
<p style="font-size: 12px; color: #9ca3af;">Oder kopiere diesen Link in deinen Browser:<br><a href="{reset_link}" style="color: #38bdf8;">{reset_link}</a></p>
<p>Falls du kein neues Passwort angefordert hast, kannst du diese E-Mail ignorieren. Dein Passwort bleibt unverändert.</p>
<p>Viele Grüße,<br>Dein EntailsNG Team</p>''',
                'is_active': True,
                'placeholder_info': '''Verfügbare Platzhalter für diese Vorlage:
- {username}: Benutzername des Teilnehmers
- {full_name}: Vor- und Nachname (oder Benutzername)
- {reset_link}: Vollständiger Link zum Festlegen des neuen Passworts''',
            },
        )
        self.stdout.write(self.style.SUCCESS("Alle Standard E-Mail-Templates sind auf dem neuesten Stand."))
