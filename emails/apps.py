from django.apps import AppConfig
from django.db.models.signals import post_migrate


def seed_default_email_templates(sender, **kwargs):
    try:
        from emails.models import EmailTemplate, GeneralEmailSettings
        GeneralEmailSettings.load()
        EmailTemplate.objects.get_or_create(
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
    except Exception:
        pass


class EmailsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'emails'
    verbose_name = 'E-Mail Konfiguration'

    def ready(self):
        post_migrate.connect(seed_default_email_templates, sender=self)

