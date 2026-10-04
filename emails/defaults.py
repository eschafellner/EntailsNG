# emails/defaults.py

DEFAULT_EMAIL_TEMPLATES = {
    'payment_confirmation': {
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
    'email_verification': {
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
    'password_reset': {
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
    'email_change_verification': {
        'name': 'E-Mail-Änderung Verifizierung',
        'subject': 'Bestätigungscode zur E-Mail-Änderung: {code}',
        'content': '''<h2>E-Mail-Adresse ändern</h2>
<p>Hallo <strong>{full_name}</strong>,</p>
<p>du hast die Änderung deiner E-Mail-Adresse für deinen EntailsNG-Account auf diese Adresse beantragt. Bitte verwende den folgenden 6-stelligen Bestätigungscode, um die Änderung zu bestätigen:</p>
<div style="background: #111827; border: 2px solid #0284c7; color: #38bdf8; padding: 20px; border-radius: 12px; font-size: 32px; font-weight: bold; font-family: monospace; letter-spacing: 8px; text-align: center; margin: 20px 0;">
  {code}
</div>
<p>Dieser Code ist <strong>{valid_minutes} Minuten</strong> lang gültig.</p>
<p>Falls du diese Änderung nicht beantragt hast, kannst du diese E-Mail ignorieren. Deine bisherige E-Mail-Adresse bleibt unverändert erhalten.</p>
<p>Viele Grüße,<br>Dein EntailsNG Team</p>''',
        'is_active': True,
        'placeholder_info': '''Verfügbare Platzhalter für diese Vorlage:
- {username}: Benutzername des Teilnehmers
- {full_name}: Vor- und Nachname (oder Benutzername)
- {code}: 6-stelliger numerischer Verifizierungscode
- {valid_minutes}: Gültigkeitsdauer in Minuten (z. B. 15)''',
    },
    'seat_overwritten': {
        'name': 'Sitzplatz-Vormerkung überschrieben',
        'subject': 'Dein vorgemerkter Sitzplatz {seat_label} für {event_title} wurde vergeben',
        'content': '''<h2>Sitzplatz-Vormerkung vergeben</h2>
<p>Hallo <strong>{full_name}</strong>,</p>
<p>dein vorgemerkter Sitzplatz <strong>{seat_label}</strong> für die Veranstaltung <strong>{event_title}</strong> wurde von einem zahlenden Gast übernommen.</p>
<div style="background: #1e293b; color: #ffffff; padding: 16px; border-radius: 8px; margin: 16px 0;">
  <p><strong>Veranstaltung:</strong> {event_title}</p>
  <p><strong>Bisheriger Platz:</strong> {seat_label}</p>
  <p><strong>Status:</strong> Bitte wähle im Sitzplan einen neuen Sitzplatz aus.</p>
</div>
<p>Sobald du dein Ticket bezahlst, ist dein Sitzplatz fest für dich gesichert und kann nicht mehr überschrieben werden.</p>
<div style="text-align: center; margin: 24px 0;">
  <a href="{seating_url}" style="background: #0284c7; color: #ffffff; padding: 12px 24px; border-radius: 8px; font-weight: bold; text-decoration: none; display: inline-block;">
    🪑 Neuen Sitzplatz wählen
  </a>
</div>
<p>Viele Grüße,<br>Dein EntailsNG Event Team</p>''',
        'is_active': True,
        'placeholder_info': '''Verfügbare Platzhalter für diese Vorlage:
- {username}: Benutzername des Teilnehmers
- {full_name}: Vor- und Nachname (oder Benutzername)
- {event_title}: Name der Veranstaltung
- {seat_label}: Bezeichnung des bisherigen Sitzplatzes
- {seating_url}: Link zum Sitzplan''',
    },
}

DEFAULT_EMAIL_TEMPLATES.update({
    'clan_seat_reminder': {
        'name': 'Clan-Sitzplatzvormerkung: Erinnerung',
        'subject': 'Sitzplatzvormerkung für {clan_name} läuft am {expires_at} ab',
        'content': '''<h2>Erinnerung an eure Sitzplatzvormerkung</h2>
<p>Hallo {username},</p>
<p>für euren Clan <strong>{clan_name}</strong> sind bei <strong>{event_title}</strong> noch <strong>{open_count}</strong> Plätze offen: {seat_labels}.</p>
<p>Die Vormerkung gilt bis <strong>{expires_at} (Europe/Vienna)</strong>. Danach werden die noch offenen Plätze automatisch freigegeben. Bereits persönlich gebuchte Plätze bleiben erhalten.</p>
<p>Bitte erinnert eure Mitglieder daran, ihre Plätze rechtzeitig zu reservieren.</p>
<p><a href="{seating_url}">Sitzplan und Clan-Vormerkungen öffnen</a></p>''',
        'is_active': True,
        'placeholder_info': '{username}: Clan-Admin; {clan_name}: Clan; {event_title}: Veranstaltung; {expires_at}: Ablauf in Europe/Vienna; {open_count}: offene Plätze; {seat_labels}: Platzbezeichnungen; {seating_url}: vollständiger Link zum Sitzplan.',
    },
    'clan_seat_expired': {
        'name': 'Clan-Sitzplatzvormerkung: abgelaufen',
        'subject': 'Sitzplatzvormerkung für {clan_name} beendet – {event_title}',
        'content': '''<h2>Eure Sitzplatzvormerkung wurde beendet</h2>
<p>Hallo {username},</p>
<p>die Vormerkung für <strong>{clan_name}</strong> bei <strong>{event_title}</strong> wurde beendet. Der hinterlegte Ablaufzeitpunkt war {expires_at} (Europe/Vienna).</p>
<p>Es wurden <strong>{open_count}</strong> noch offene Plätze freigegeben: {seat_labels}.</p>
<p>Bereits persönlich gebuchte Plätze bleiben erhalten. Eure Mitglieder können weiterhin regulär verfügbare Plätze wählen, sofern die Veranstaltung Buchungen zulässt.</p>
<p><a href="{seating_url}">Sitzplan öffnen</a></p>''',
        'is_active': True,
        'placeholder_info': '{username}: Clan-Admin; {clan_name}: Clan; {event_title}: Veranstaltung; {expires_at}: hinterlegter Ablaufzeitpunkt; {open_count}: freigegebene Plätze; {seat_labels}: Platzbezeichnungen; {seating_url}: vollständiger Link zum Sitzplan.',
    },
})
