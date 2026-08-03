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
    except Exception:
        pass


class EmailsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'emails'
    verbose_name = 'E-Mail Konfiguration'

    def ready(self):
        post_migrate.connect(seed_default_email_templates, sender=self)

