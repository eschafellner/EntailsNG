# emails/defaults.py

DEFAULT_EMAIL_TEMPLATES = {
    'contact_request': {
        'name': 'Kontaktanfrage an das Orga-Team',
        'subject': '[Kontakt] {category}',
        'content': '''<h2>Neue Kontaktanfrage</h2>
<p><strong>Thema:</strong> {category}</p>
<p><strong>Antwortadresse des Gastes:</strong> {email}</p>
<p><strong>Eingang:</strong> {submitted_at}</p>
<pre style="white-space: pre-wrap; overflow-wrap: anywhere; font-family: Arial, sans-serif;">{message}</pre>
<p>Mit der Antwortfunktion deines E-Mail-Programms erreichst du den Gast direkt.</p>''',
        'is_active': True,
        'placeholder_info': '{category}: Betreffkategorie; {email}: Antwortadresse des Gastes; {message}: Nachricht; {submitted_at}: Eingangszeitpunkt (Europe/Vienna).',
    },
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

DEFAULT_EMAIL_TEMPLATES.update({
    'clan_payment_created': {
        'name': 'Clan-Sammelzahlung: Zahlungsauftrag',
        'subject': 'Clan-Zahlungsauftrag {reference} – {event_title}',
        'content': '''<p>Hallo {username},</p><p>für {clan_name} wurden {seat_count} Plätze verbindlich festgeschrieben. Bitte <strong>{amount} €</strong> mit dem Verwendungszweck <strong>{reference}</strong> überweisen.</p><p>Zahlungseingang spätestens: <strong>{payment_due_at}</strong>. Ohne bestätigte Zahlung werden die Plätze am <strong>{release_at}</strong> automatisch freigegeben. Alle Zeiten: Europe/Vienna.</p><p>Auftrag und enthaltene Plätze können durch Clanadmins nicht mehr geändert werden. Spätere Zahlungen müssen mit der Orga geklärt werden.</p><p><a href="{payment_url}">Überweisungsdaten und Auftrag öffnen</a></p>''',
        'is_active': True,
        'placeholder_info': '{username}, {clan_name}, {event_title}, {reference}, {amount}, {seat_count}, {payment_due_at}, {release_at}, {payment_url}',
    },
    'clan_payment_reminder': {
        'name': 'Clan-Sammelzahlung: Zahlungserinnerung',
        'subject': 'Zahlungsfrist für {reference}: {payment_due_at}',
        'content': '''<p>Hallo {username},</p><p>für den Clan-Zahlungsauftrag {reference} ({clan_name}, {event_title}) ist noch keine Zahlung bestätigt. Betrag: {amount} €.</p><p>Zahlungseingang spätestens: <strong>{payment_due_at}</strong>. Automatische Platzfreigabe ohne Bestätigung: <strong>{release_at}</strong>. Alle Zeiten: Europe/Vienna.</p><p>Falls ihr bereits überwiesen habt, kontaktiert bitte die Orga.</p><p><a href="{payment_url}">Auftrag öffnen</a></p>''',
        'is_active': True,
        'placeholder_info': '{username}, {clan_name}, {event_title}, {reference}, {amount}, {payment_due_at}, {release_at}, {payment_url}',
    },
    'clan_payment_confirmed': {
        'name': 'Clan-Sammelzahlung: Zahlung bestätigt',
        'subject': 'Clan-Zahlung {reference} bestätigt – {event_title}',
        'content': '''<p>Hallo {username},</p><p>die Orga hat {amount} € für {reference} bestätigt. Eure {seat_count} Plätze bei {event_title} sind jetzt bezahlt und bleiben unabhängig von der bisherigen Vormerkfrist geschützt.</p><p>Ihr könnt jetzt bestätigte Clanmitglieder zuweisen. Gäste mit bereits bezahlten Tickets können nicht zugewiesen werden.</p><p><a href="{payment_url}">Clanplätze verwalten</a></p>''',
        'is_active': True,
        'placeholder_info': '{username}, {event_title}, {reference}, {amount}, {seat_count}, {payment_url}',
    },
    'clan_payment_cancelled': {
        'name': 'Clan-Sammelzahlung: storniert',
        'subject': 'Clan-Zahlungsauftrag {reference} storniert – {event_title}',
        'content': '''<p>Hallo {username},</p><p>der Auftrag {reference} für {clan_name} bei {event_title} wurde storniert. Seine {seat_count} Plätze sind freigegeben.</p><p>Bitte nicht mehr auf diesen Auftrag überweisen. Bereits überwiesene, verspätete oder erst später erkannte Zahlungen müssen mit der Orga geklärt werden; Plätze werden nicht automatisch wiederhergestellt.</p><p><a href="{payment_url}">Auftrag öffnen</a></p>''',
        'is_active': True,
        'placeholder_info': '{username}, {clan_name}, {event_title}, {reference}, {seat_count}, {payment_url}',
    },
    'clan_payment_assigned': {
        'name': 'Clan-Sammelzahlung: Mitglied zugewiesen',
        'subject': 'Dein Clanplatz {seat_label} – {event_title}',
        'content': '''<p>Hallo {username},</p><p>dein Clan {clan_name} hat dir den bezahlten Platz <strong>{seat_label}</strong> bei {event_title} zugewiesen. Deine Veranstaltungsanmeldung ist bezahlt. Du brauchst keine eigene Überweisung für dieses Ticket.</p><p>Der Ticketanteil {amount} € ist durch die bestätigte Sammelzahlung {reference} gedeckt. Den Einlasscode findest du auf deinem Dashboard. Platzwechsel und Änderungen der Clan-Zahlungsdeckung verwalten eure Clanadmins.</p>''',
        'is_active': True,
        'placeholder_info': '{username}, {clan_name}, {event_title}, {seat_label}, {reference}, {amount}',
    },
    'clan_payment_removed': {
        'name': 'Clan-Sammelzahlung: Zuweisung aufgehoben',
        'subject': 'Clanplatz {seat_label} aufgehoben – {event_title}',
        'content': '''<p>Hallo {username},</p><p>deine Zuweisung auf den Clanplatz {seat_label} bei {event_title} wurde aufgehoben. Dein Ticket wird nicht mehr durch die Clan-Sammelzahlung gedeckt.</p><p>Der Status deiner Anmeldung lautet jetzt: <strong>{registration_status}</strong>. Prüfe bitte dein Dashboard und kläre deine weitere Teilnahme mit euren Clanadmins oder der Orga.</p>''',
        'is_active': True,
        'placeholder_info': '{username}, {event_title}, {seat_label}, {registration_status}',
    },
})

_REGISTRATION_EVENT_BOX = '''<div style="background: #1e293b; color: #ffffff; padding: 16px; border-radius: 8px; margin: 16px 0;">
  <p><strong>Veranstaltung:</strong> {event_title}</p>
  <p><strong>Beginn:</strong> {event_start}</p>
  <p><strong>Ende:</strong> {event_end}</p>
  <p><strong>Ort:</strong> {event_location}</p>
  <p><strong>Benutzername:</strong> {username}</p>
  <p><strong>Ticket:</strong> {ticket_type}</p>
  <p><strong>Preis:</strong> {price} €</p>
</div>'''

_REGISTRATION_PLACEHOLDERS = '''- {username}: Benutzername des Gastes
- {full_name}: Vor- und Nachname (oder Benutzername)
- {event_title}: Name der Veranstaltung
- {event_start} / {event_end}: Beginn und Ende (Europe/Vienna)
- {event_location}: Veranstaltungsort
- {ticket_type}: Gebuchte Ticketkategorie
- {price}: Ticketpreis zum Zeitpunkt der Anmeldung in Euro
- {payment_reference}: Verwendungszweck (Kurzcode + Name)
- {payment_deadline}: Zahlungsfrist der Ticketkategorie (TT.MM.JJJJ, leer ohne Frist)
- {dashboard_url}: Link zum Dashboard'''

DEFAULT_EMAIL_TEMPLATES.update({
    'event_registration_confirmation': {
        'name': 'Anmeldebestätigung (mit Zahlung)',
        'subject': 'Anmeldebestätigung für {event_title}',
        'content': '''<h2>Anmeldebestätigung</h2>
<p>Hallo <strong>{full_name}</strong>,</p>
<p>vielen Dank für deine Anmeldung zur Veranstaltung <strong>{event_title}</strong>!</p>
''' + _REGISTRATION_EVENT_BOX + '''
<h3>Zahlung</h3>
<p>{payment_deadline_hint}</p>
<p>Scanne den QR-Code mit deiner Banking-App oder überweise mit diesen Daten:</p>
<p style="text-align: center;"><img src="cid:payment_qr" alt="Zahlungs-QR-Code (GiroCode)" width="200" height="200" style="background: #ffffff; padding: 8px;"></p>
<div style="background: #f1f5f9; color: #0f172a; padding: 16px; border-radius: 8px; margin: 16px 0;">
  <p><strong>Kontoinhaber:</strong> {account_holder}</p>
  <p><strong>IBAN:</strong> {iban}</p>
  <p><strong>BIC:</strong> {bic}</p>
  <p><strong>Betrag:</strong> {price} €</p>
  <p><strong>Verwendungszweck:</strong> {payment_reference}</p>
</div>
<p>Nach Zahlungseingang erhältst du eine Bestätigung, und dein Einlass-QR-Code wird im <a href="{dashboard_url}">Dashboard</a> freigeschaltet.</p>
<p>Viele Grüße,<br>Dein EntailsNG Event Team</p>''',
        'is_active': True,
        'placeholder_info': '''Wird bei einer Anmeldung mit offenem Betrag versendet. Das QR-Bild wird über <img src="cid:payment_qr"> eingebunden.
''' + _REGISTRATION_PLACEHOLDERS + '''
- {payment_deadline_hint}: Satz zur Zahlungsfrist (Text über Systemtexte anpassbar)
- {account_holder}, {iban}, {bic}: Bankdaten aus der Allgemeinen Konfiguration''',
    },
    'event_registration_confirmation_free': {
        'name': 'Anmeldebestätigung (ohne Zahlungsdaten)',
        'subject': 'Anmeldebestätigung für {event_title}',
        'content': '''<h2>Anmeldebestätigung</h2>
<p>Hallo <strong>{full_name}</strong>,</p>
<p>vielen Dank für deine Anmeldung zur Veranstaltung <strong>{event_title}</strong>!</p>
''' + _REGISTRATION_EVENT_BOX + '''
<p>{payment_hint}</p>
<p>Alle Details findest du jederzeit im <a href="{dashboard_url}">Dashboard</a>.</p>
<p>Viele Grüße,<br>Dein EntailsNG Event Team</p>''',
        'is_active': True,
        'placeholder_info': '''Wird bei kostenlosen Tickets versendet oder wenn noch keine Bankdaten hinterlegt sind.
''' + _REGISTRATION_PLACEHOLDERS + '''
- {payment_hint}: Hinweis zur Zahlung (Text über Systemtexte anpassbar)''',
    },
    'registration_payment_expired': {
        'name': 'Anmeldung storniert (Zahlungsfrist abgelaufen)',
        'subject': 'Deine Anmeldung für {event_title} wurde storniert',
        'content': '''<h2>Anmeldung storniert</h2>
<p>Hallo <strong>{full_name}</strong>,</p>
<p>für deine Anmeldung zur Veranstaltung <strong>{event_title}</strong> ist bis zum Ende der Zahlungsfrist am <strong>{payment_deadline}</strong> kein Zahlungseingang verbucht worden. Die Anmeldung wurde deshalb automatisch storniert, ein eventuell gewählter Sitzplatz ist wieder freigegeben.</p>
<div style="background: #1e293b; color: #ffffff; padding: 16px; border-radius: 8px; margin: 16px 0;">
  <p><strong>Ticket:</strong> {ticket_type}</p>
  <p><strong>Preis:</strong> {price} €</p>
  <p><strong>Verwendungszweck:</strong> {payment_reference}</p>
</div>
<p>Bitte überweise nicht mehr auf diese Anmeldung. Falls du bereits bezahlt hast, melde dich bitte beim Orga-Team.</p>
<p>Viele Grüße,<br>Dein EntailsNG Event Team</p>''',
        'is_active': True,
        'placeholder_info': _REGISTRATION_PLACEHOLDERS,
    },
})
