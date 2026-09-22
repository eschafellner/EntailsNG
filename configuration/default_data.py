"""
Zentrale Vorgabewerte und Standardinhalte für das EntailsNG System.
Trennt umfangreiche Text- und SVG-Konstanten von den eigentlichen Datenbankmodellen.
"""

SYSTEM_ICONS = {
    'dashboard': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>'
        '<polyline points="9 22 9 12 15 12 15 22"></polyline></svg>'
    ),
    'tournaments': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"></path>'
        '<path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"></path>'
        '<path d="M4 22h16"></path><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"></path>'
        '<path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"></path>'
        '<path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"></path></svg>'
    ),
    'teams': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path>'
        '<circle cx="9" cy="7" r="4"></circle><path d="M22 21v-2a4 4 0 0 0-3-3.87"></path>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>'
    ),
    'seating': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>'
        '<line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>'
    ),
    'guests': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>'
        '<circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>'
    ),
    'info': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle>'
        '<line x1="12" y1="16" x2="12" y2="12"></line>'
        '<line x1="12" y1="8" x2="12.01" y2="8"></line></svg>'
    ),
    'news': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"></path>'
        '<path d="M18 14h-8"></path><path d="M15 18h-5"></path><path d="M10 6h8v4h-8V6Z"></path></svg>'
    ),
    'clans': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>'
    ),
    'rules': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"></path>'
        '<path d="M6 6h10"></path><path d="M6 10h10"></path></svg>'
    ),
    'support': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle>'
        '<path d="m4.93 4.93 4.24 4.24"></path><path d="m14.83 14.83 4.24 4.24"></path>'
        '<path d="m14.83 9.17 4.24-4.24"></path><path d="m4.93 19.07 4.24-4.24"></path></svg>'
    ),
    'shop': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><circle cx="8" cy="21" r="1"></circle><circle cx="19" cy="21" r="1"></circle>'
        '<path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"></path></svg>'
    ),
    'settings': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path>'
        '<circle cx="12" cy="12" r="3"></circle></svg>'
    ),
    'sponsors': (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"></path></svg>'
    ),
}

DEFAULT_DATENSCHUTZ_CONTENT = """<h3>Datenschutzerklärung</h3>
<p>Wir nehmen den Schutz Ihrer persönlichen Daten sehr ernst. Nachfolgend informieren wir Sie über die Verarbeitung personenbezogener Daten bei der Nutzung unserer Plattform im Rahmen der Organisation und Durchführung von Veranstaltungen (LAN-Partys).</p>

<h4>1. Verantwortlicher</h4>
<p>Verantwortlich für die Datenverarbeitung auf dieser Website ist der jeweilige Veranstalter / Betreiber der Plattform (siehe Angaben im <a href="/impressum/">Impressum</a>).</p>

<h4>2. Bereitstellung der Website und Server-Logfiles</h4>
<p>Beim Aufruf unserer Website erfasst unser Webserver automatisch technische Informationen, die Ihr Browser an uns übermittelt (z.&nbsp;B. IP-Adresse, Datum und Uhrzeit des Zugriffs, aufgerufene Seite, Browsertyp und Betriebssystem). Die Erfassung dieser Daten erfolgt zur Gewährleistung eines reibungslosen Verbindungsaufbaus, der Systemsicherheit sowie zu administrativen Zwecken auf Grundlage von Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse an der IT-Sicherheit und Fehleranalyse).</p>

<h4>3. Einsatz von Cookies &amp; lokalem Speicher</h4>
<p>Unsere Website verwendet ausschließlich <strong>technisch zwingend erforderliche Cookies</strong> (Erstanbieter-Cookies). Es werden <strong>keine</strong> Tracking-, Analyse- oder Marketing-Cookies (wie Google Analytics, Meta Pixel etc.) eingesetzt.</p>
<ul>
  <li><strong><code>sessionid</code>:</strong> Speichert die Sitzungskennung angemeldeter Benutzer, um die Authentifizierung über aufeinanderfolgende Seitenaufrufe hinweg aufrechtzuerhalten. Gültigkeit: Für die Dauer der Sitzung bzw. bis zum Logout.</li>
  <li><strong><code>csrftoken</code>:</strong> Ein kryptografisches Sicherheits-Token, das Angriffe durch Cross-Site Request Forgery (CSRF) bei Formularübermittlungen und Datenänderungen (z.&nbsp;B. Platzreservierung, Teambeitritt) verhindert. Gültigkeit: 1 Jahr bzw. bis zum Sitzungsende.</li>
</ul>
<p>Die Speicherung dieser Cookies erfolgt auf Grundlage von § 25 Abs. 2 Nr. 2 TDDDG bzw. Art. 5 Abs. 3 ePrivacy-Richtlinie i.&nbsp;V.&nbsp;m. Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse an einem sicheren und funktionierenden Betrieb der Plattform). Ein gesonderter Cookie-Banner / Consent-Banner ist für diese essenziellen Cookies gesetzlich nicht erforderlich.</p>
<p>Zudem nutzt das System den clientseitigen Speicher Ihres Browsers (<code>sessionStorage</code>), um temporäre UI-Zustände (z.&nbsp;B. den aktiven Reiter in der Turnieransicht) während Ihres Besuchs zu speichern. Diese Daten verbleiben rein lokal auf Ihrem Endgerät und werden zu keinem Zeitpunkt an Dritte übermittelt.</p>

<h4>4. Benutzerkonto, Registrierung und Stammdaten</h4>
<p>Wenn Sie sich auf unserer Plattform registrieren, verarbeiten wir die von Ihnen eingegebenen Daten (Benutzername, E-Mail-Adresse und Passwort) zur Erstellung und Verwaltung Ihres Benutzerkontos sowie zur Authentifizierung (Art. 6 Abs. 1 lit. b DSGVO zur Vertragserfüllung bzw. Durchführung vorvertraglicher Maßnahmen). Passwörter werden ausschließlich als sichere, kryptografische Hashes gespeichert.</p>

<h4>5. Event-Teilnahme, Ticketbuchung und Zahlungsstatus</h4>
<p>Für die Teilnahme an einer Veranstaltung verarbeiten wir Ihre Event-Anmeldung, gewählte Ticket-Kategorien, Zahlungsstatus (z.&nbsp;B. Bezahlt / Ausstehend), den Zeitpunkt der Zahlungsprüfung sowie ggf. getätigte Sitzplatzreservierungen. Diese Datenverarbeitung dient der ordnungsgemäßen Abwicklung der Veranstaltung (Art. 6 Abs. 1 lit. b DSGVO).</p>

<h4>6. Öffentliche Anzeige auf der Plattform (Gästeliste, Sitzplan &amp; Turniere)</h4>
<p>Im Rahmen des interaktiven LAN-Party-Erlebnisses sind bestimmte Profildaten für andere Teilnehmer sichtbar:</p>
<ul>
  <li>Auf der <strong>Gästeliste</strong> und im <strong>Sitzplan</strong> werden Ihr Benutzername (Gamer-Tag), optionaler Clan und Ihr reservierter Sitzplatz öffentlich angezeigt.</li>
  <li>In <strong>Turnieren</strong> werden Ihr Teamname sowie die beteiligten Teammitglieder zur Turnierorganisation und Anzeige von Paarungen und Ergebnissen dargestellt.</li>
</ul>
<p>Rechtsgrundlage hierfür ist die Erfüllung des Teilnahmevertrags (Art. 6 Abs. 1 lit. b DSGVO) sowie unser berechtigtes Interesse an einer transparenten und gemeinschaftlichen Durchführung der Veranstaltung (Art. 6 Abs. 1 lit. f DSGVO).</p>

<h4>7. E-Mail-Benachrichtigungen</h4>
<p>Wir versenden ausschließlich systemrelevante Transaktions-E-Mails (z.&nbsp;B. Verifizierungs-Codes zur E-Mail-Bestätigung, Links zum Zurücksetzen des Passworts oder Anmeldebestätigungen). Es erfolgt kein Versand von Werbe-Newslettern ohne gesonderte Einwilligung.</p>

<h4>8. Ihre Rechte als betroffene Person</h4>
<p>Sie haben nach der DSGVO jederzeit das Recht auf Auskunft (Art. 15 DSGVO), Berichtigung (Art. 16 DSGVO), Löschung (Art. 17 DSGVO), Einschränkung der Verarbeitung (Art. 18 DSGVO), Datenübertragbarkeit (Art. 20 DSGVO) sowie Widerspruch (Art. 21 DSGVO). Zudem steht Ihnen ein Beschwerderecht bei der zuständigen Datenschutz-Aufsichtsbehörde zu.</p>"""
