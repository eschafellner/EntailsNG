# Clan-Sitzplatzvormerkungen

Stand: 4. Oktober 2026.

Clan-Admins können im Clanprofil **Sitzplätze für Clan vormerken** öffnen,
freie Plätze per Klick auswählen und die Auswahl gemeinsam bestätigen.
Der Sitzplan zeigt Kontingent, bereits übernommene Plätze, Auswahl und verbleibende
Plätze. Eigene offene Vormerkungen lassen sich abwählen. Änderungen verlängern
die Frist nicht. Bei einer veralteten Auswahl muss der Plan aktualisiert werden;
Änderungen anderer Admins oder zwischenzeitliche Buchungen werden nicht überschrieben.

Offene Plätze tragen das Clanlogo und den Tooltip **Vorgemerkt für Clan …**.
Clans ohne Logo erhalten ihr Kürzel. Informationen sind auch per Antippen erreichbar.
Bestätigte aktive Mitglieder mit gültiger Eventanmeldung können solche Plätze
buchen. Anschließend gelten die bestehenden Zahlungsregeln. Ein zahlender Gast
eines anderen Clans kann auch einen unbezahlten Clanplatz während der Schutzfrist
nicht überschreiben. Bereits bezahlte Buchungen bleiben generell geschützt.

## Einstellungen

Unter **Konfiguration → Clan Sitzplatz Vormerkung**:

- **Aktiv**: bei Einführung deaktiviert. Deaktivieren gibt offene Vormerkungen
  sofort frei und entfernt den Clanschutz von persönlichen Buchungen;
  die Buchungen selbst bleiben erhalten.
- **Anzahl vormerkbarer Sitzplätze**: global wartbarer Standard **8**.
- **Veranstaltungszeitraum**: bis Eventende. Terminänderungen werden berücksichtigt.
  Abschluss, Absage oder Deaktivierung beenden die Vormerkung ebenfalls.
- **Zeitraum ab erster Vormerkung des Clans**: Anzahl Tage ab der ersten
  bestätigten, nicht leeren Auswahl dieses Clans für diese Veranstaltung.
  Clan B startet bei späterer Auswahl eine eigene, spätere Frist als Clan A.
- **Fixer Zeitpunkt**: Datum und Uhrzeit in `Europe/Vienna`.

Tages- und fixe Fristen enden spätestens mit der Veranstaltung. Der Laufzeitmodus
und die Frist werden beim ersten Bestätigen gespeichert; Änderungen der globalen
Laufzeit verändern vorhandene Tages-/Fixfristen nicht. Ein abgelaufener
Vormerkungszeitraum kann im selben Event nicht erneut gestartet werden.

Im Backend unter **Clan-Verwaltung → Clans** überschreibt
**Sitzplatzkontingent (optional)** den Standard: leer übernimmt den Standard,
eine Zahl erhöht/reduziert ihn, **0** sperrt den Clan und gibt offene Plätze sofort
frei. Clan-Admins können diesen Wert im Frontend nicht ändern.

Offene Vormerkungen und übernommene Plätze zählen gemeinsam zum Kontingent.
Persönliche Buchungen verbrauchen ihr Kontingent weiterhin, auch nach Platzwechsel
oder Stornierung. Ein freigegebener persönlicher Clanplatz wird während der
ursprünglichen Schutzfrist wieder als Clan-Vormerkung sichtbar. Eine zusätzliche
Vormerkung erstattet kein bereits verbrauchtes Kontingent.

Bei einer Reduzierung unter den aktuellen Bestand wählt die Orga die
freizugebenden offenen Plätze im Formular aus und bestätigt die Freigabe
mit einer Checkbox. Ohne ausreichende Auswahl oder Bestätigung wird nicht
gespeichert. Wenn persönliche Buchungen allein das neue Limit überschreiten,
müssen alle noch offenen Plätze freigegeben werden; persönliche Buchungen
bleiben erhalten. Änderungen des globalen Standards berücksichtigen individuelle
Clanüberschreibungen. Deaktivierung und Wert 0 verlangen ebenfalls eine
Bestätigung, sobald offene Vormerkungen betroffen sind.

Eine erneute Aktivierung stellt zuvor freigegebene Vormerkungen nicht wieder her.
Eine neue Auswahl ist nur innerhalb der ursprünglichen Frist und des Kontingents möglich.

## Automatischer Ablauf und E-Mails

Ein separater Worker verarbeitet Fristen unabhängig von Seitenaufrufen:

```bash
python manage.py process_clan_seat_holds --daemon --interval 60
```

Einmalige Verarbeitung, etwa zur Diagnose:

```bash
python manage.py process_clan_seat_holds
```

Der Compose-Dienst **clan_seat_worker** startet regulär mit dem Stack und nutzt
das bestehende `backup_data`-Volume zur Koordination mit Backup-Wartungsfenstern.
Er schließt Datenbankverbindungen zwischen Durchläufen und versucht nach
vorübergehenden Fehlern im nächsten Durchlauf erneut zu verarbeiten.

Sperren gelten ab dem Ablaufzeitpunkt bereits in der Buchungsprüfung und der
Sitzplan-API als aufgehoben. Die persistente Bereinigung und E-Mail-Auslösung
folgen im Worker mit standardmäßig höchstens etwa einer Minute Verzögerung,
sofern der Worker läuft und die Datenbank erreichbar ist.

Es gibt zwei im Backend bearbeitbare E-Mail-Templates:

- `clan_seat_reminder`: einmalige Erinnerung sieben Tage vor Ablauf, nur bei
  offenen Plätzen. Bei einer anfänglichen Frist von höchstens sieben Tagen
  sofort nach der ersten Bestätigung. Verpasste Erinnerungen werden bei einem
  späteren Workerstart nur vor Ablauf nachgeholt.
- `clan_seat_expired`: einmalige Nachricht über die freigegebenen offenen Plätze.
  Gibt es keine offenen Plätze, wird keine Nachricht ausgelöst. Bereits
  persönlich gebuchte Plätze werden nicht freigegeben. Auch Eventabschluss,
  Absage oder Deaktivierung beenden die Vormerkung und lösen bei offenen Plätzen
  diese Nachricht aus. Administrative Kontingentfreigaben lösen keine Ablaufmail aus.

Jeder aktuelle bestätigte aktive Clan-Admin erhält eine eigene Nachricht,
keine gemeinsame Empfängerliste. Empfänger und offene Plätze werden zur
Auslösung ermittelt. Outbox-Einträge und Auslösungsstatus werden in derselben
Datenbanktransaktion gespeichert. Versand, Pausen und Wiederholungen übernimmt
der bestehende E-Mail-Worker. Deaktivierte Vorlagen unterdrücken die jeweilige Mail.
Erinnerungen haben ein Ablaufdatum, damit nach dem Fristende keine alte Erinnerung
mehr versendet wird.

Die Platzhalter umfassen Adminname, Clanname, Veranstaltung, Ablaufzeitpunkt,
Anzahl und Bezeichnungen offener Plätze sowie den Sitzplan-Link.
**PUBLIC_BASE_URL** muss für vollständige Links auf die öffentliche Adresse zeigen.
Ohne Angabe wird für lokale Entwicklung `http://localhost:8000` verwendet.

## Datenmodell und Konsistenz

`ClanSeatConfiguration` ist ein Singleton. `Clan.seat_limit_override` bleibt
nullable, um Vererbung von einer expliziten Sperre mit 0 zu unterscheiden.
`ClanSeatAllocation` hält einen Zeitraum je Clan/Event.
`ClanSeatHold` hält Platzzuordnung und offene/übernommene/freigegebene Herkunft.
Datenbank-Constraints sichern einen Zeitraum pro Clan/Event und höchstens eine
aktive Clan-Zuordnung pro Sitzplatz. Persönliche Buchungen bleiben in
`SeatingCell.registration`; Clan-Vormerkungen erzeugen keine Eventanmeldungen.

Die kurzen Schreibtransaktionen der Sitzplan-APIs, der Vormerkungen,
der Kontingentformulare und des Editors sperren zunächst die Konfigurationszeile.
Danach folgen bei personenbezogenen Buchungen Benutzer und Event vor
Anmeldung/Zelle; Vormerkungen sperren Benutzer → Event → Clan → Plan → Zellen.
Diese gemeinsame Konfigurationssperre serialisiert Sitzplanschreibaktionen
zugunsten einer eindeutigen Kontingentprüfung. Der Worker verwendet dieselbe Sperre;
bei vielen Clans sind Wartezeiten unter Last zu beobachten, bevor dieses
Sperrkonzept feiner aufgeteilt wird. Die vorhandene Kontolöschung und Clanrollen-
verwaltung erwerben die Konfigurationssperre nicht nach ihren Benutzersperren.

Ein Hash des aktuellen Vormerkungs-, Buchungs- und Konfigurationsstands schützt
Frontend-Auswahlen vor dem Überschreiben zwischenzeitlicher Änderungen.
Buchungsberechtigung und Kontingent werden weiterhin serverseitig geprüft.
Sitzplan-Editor, Verkleinerung, Eventwechsel, administrative Typänderung und
Löschung geschützter Zellen verlangen vorherige Freigabe. Klone übernehmen
keine Clan-Vormerkungen. Clanlöschung entfernt Vormerkungen und lässt persönliche
Buchungen bestehen. Kapazitätsanzeigen zählen weiterhin persönliche Buchungen;
Clan-Vormerkungen sind keine verkauften Tickets.

Direkte ORM-/Datenbankänderungen sind Betreiberwerkzeuge. Insbesondere positive
Kontingentreduzierungen müssen über die Backendformulare erfolgen, damit die
Auswahl und Bestätigung der freizugebenden Plätze eingehalten werden.

## Einführung

```bash
python manage.py migrate --noinput
python manage.py seed_translations
python manage.py seed_email_templates
python manage.py collectstatic --noinput
```

Erforderliche Migrationen: `configuration.0021_clan_seat_configuration`,
`clans.0006_clan_seat_limit_override` und
`seating.0009_clanseatallocation_clanseathold_and_more`.

In `.env` `PUBLIC_BASE_URL` setzen, den neuen Worker starten und anschließend
die Funktion im Backend aktivieren. Docker:

```bash
docker compose up -d --build
```

Lokaler Betrieb benötigt neben dem Webserver sowohl den Clan-Worker als auch
`python manage.py process_email_queue --daemon` für den Versand.

## Prüfung

42 neue Funktionstests und acht PostgreSQL-Paralleltests decken Kontingente,
getrennte Clanfristen, alle Laufzeitmodi, Übernahme/Freigabe/Stornierung,
E-Mail-Auslösung, veraltete Auswahlen, Backendfreigaben, CSRF, Sitzplanänderungen
und Gastdatenschutz ab. Der PostgreSQL-Lauf einschließlich vorhandener
Clanrollen- und Kontolöschungstests umfasst **88 erfolgreiche Tests**.
Der abschließende SQLite-Gesamtlauf umfasst **941 Tests: 898 erfolgreich, 43 PostgreSQL-Fälle übersprungen**, keine Fehler.
Die lokale Instanz verwendet PostgreSQL **18.6**; die neuen Tests sind außerdem
in den bestehenden PostgreSQL-16-CI-Job aufgenommen. CI und Docker-Imagebau
wurden lokal nicht ausgeführt. JavaScript-Syntaxprüfung sowie die vorhandenen
Scanner- und Turnier-JavaScriptprüfungen sind erfolgreich. Drei neue JavaScriptprüfungen
prüfen sichere Textdarstellung, die Übernahme durch Clanmitglieder und Kontingent/Mehrfachbestätigung.

Die API-Abfragen bleiben unabhängig von der Anzahl der Rasterzellen:
anonym drei Abfragen bei deaktivierter Funktion und vier bei aktiven Vormerkungen.
Desktop- und 390-Pixel-Browserprüfung bestätigen Auswahl, Speicherung, Logos,
Kontingentanzeige und gezielte Backendfreigabe. Die schmale Ansicht hat keinen
horizontalen Seitenüberlauf. Screenshots liegen unter `docs/screenshots/clan-seat-*`.
Die Browserprüfung nutzt eine getrennte Vorschau-Datenbank und Testkonten.

Der bekannte globale Migrationscheck zu drei Theme-Farbdefaults bleibt bestehen;
die zugehörigen Felder wurden mit dieser Erweiterung nicht geändert.
