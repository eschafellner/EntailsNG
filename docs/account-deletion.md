# Selbstlöschung von Gast-Accounts

Stand: 30. September 2026.

## Verhalten im Profil

Unter `/profile/` steht der Bereich „Account löschen“ zur Verfügung. Eine native
`details`-Bestätigung funktioniert auch ohne JavaScript. Der Gast muss die Folgen
bestätigen und sein aktuelles Passwort eingeben. Die endgültige Aktion ist ein
authentifizierter, CSRF-geschützter POST auf `/profile/delete/`.

Die Selbstlöschung ist gesperrt, solange eine Anmeldung den Status `PAID` hat.
Dies gilt ausdrücklich auch für vergangene Veranstaltungen und kostenlose Tickets,
die als bezahlt markiert wurden. Die Orga muss die Abwicklung zuerst klären und die
betroffene Anmeldung stornieren. Eine automatische Rückzahlung oder eine gesonderte
Freigabe durch einen Löschantrag ist nicht Teil dieses Ablaufs.

Zusätzlich sperren Turniere mit Status `IN_PROGRESS` oder einem bereits generierten
Turnierbaum, wenn der Gast Kapitän oder bestätigtes Teammitglied ist. Beendete und
abgesagte Turniere sind ausgenommen; reine Beitrittsanfragen sperren nicht.
Mitarbeiterkonten und administrative Rollen werden an die Administration verwiesen.

## Restdatensatz und erneute Registrierung

`User.deleted_at` kennzeichnet die irreversible Löschung. Benutzername und E-Mail
werden durch eindeutige zufällige Werte ersetzt; Namen, Geburtstag, letzter Login
und Sperrinformationen werden geleert. Das Passwort wird unbrauchbar gemacht,
`is_active` wird deaktiviert, Gruppen und Einzelberechtigungen werden entfernt.
Der Account kann weder im Admin noch über Aktivierungscodes reaktiviert werden.
`User.display_name` zeigt in Teamansichten und Medienexporten „Gelöschter Benutzer“.

Die alte User-ID bleibt für die Buchungs- und Turnierhistorie bestehen. Eine neue
Registrierung mit dem bisherigen Namen und der bisherigen E-Mail erstellt einen
neuen User und benötigt wie bisher die E-Mail-Verifizierung. Es werden keine
Anmeldungen, Tickets oder Mitgliedschaften anhand von Name/E-Mail übernommen.
Ticketendpunkte prüfen weiterhin den Besitzer über die User-ID. Alte Sitzungen,
Aktivierungscodes und Passwort-Reset-Tokens geben keinen Zugriff auf den Restdatensatz.

## Abhängige Daten

- Alle übrigen Eventanmeldungen werden storniert. Zahlungsbeträge bleiben als
  Historie erhalten; Check-in-Tokens werden erneuert und Sitzplätze freigegeben.
- Clanmitgliedschaften und Anfragen werden entfernt. Der nächste verbleibende
  bestätigte Teilnehmer übernimmt bei Bedarf die Administration. Leere Clans
  werden aufgelöst; deren Logo wird nach dem Commit aus dem Speicher entfernt.
- Teamkapitäne werden durch das älteste verbleibende bestätigte Mitglied ersetzt.
  Ungenerierte Turnieranmeldungen werden bei anschließend unvollständigem Kader
  entfernt. Leere Teams ohne Turnierhistorie werden gelöscht. Teams mit beendeten
  oder abgesagten Turnieren bleiben erhalten; ein leeres historisches Team wird
  archiviert. Historische Mitgliedschaften dürfen den Restdatensatz referenzieren.
- Bei historischen Solo-Teams werden Name, Tag und der aus dem alten Namen
  abgeleitete URL-Slug bereinigt. Turnieranmeldungen und Ergebnisse bleiben erhalten.
- Eigene Verifizierungscodes werden gelöscht. Outbox-Kopien an die bisherige
  Adresse und zuordenbare E-Mail-Änderungscodes werden geleert und als abgelaufen
  markiert. Eigene Datenbank-Fehlerlogs werden entfernt.
- Laufende DB-Sitzungen werden entfernt. Andere Session-Stores verlieren durch
  Passwortänderung und die zusätzliche Authentifizierungsprüfung ihren Zugriff.

Die Funktion entfernt persönliche Profildaten und zuordenbare Kopien in der
Anwendungsdatenbank. Sie ist kein allgemeines Löschwerkzeug für personenbezogene
Freitexte, bereits versendete E-Mails, heruntergeladene PDFs, Serverlogs oder Backups.
Die Behandlung dieser Kopien muss im Betrieb separat geregelt werden. Ein bereits
an den Mailserver übergebener Versand kann nicht zurückgerufen werden.

## Transaktionen und Installation

`UserService.delete_account()` prüft das Passwort und die Sperrgründe erneut unter
Zeilensperren. Datenänderungen werden vollständig zurückgerollt, wenn ein Schritt
scheitert. Passwortfehlversuche werden unabhängig davon gespeichert und nutzen die
vorhandene Sperre nach fünf Fehlversuchen. Zahlungen, Eventanmeldungen und
Turnieranmeldungen prüfen den aktuellen User und koordinieren ihre Sperren mit der
Löschung. `User.save()` verhindert auch bei veralteten Profilobjekten, dass persönliche
Daten nach einer Löschung zurückgeschrieben werden.

Sperrreihenfolge: User, Events, Turniere, Teams, Eventanmeldungen. User-Zeilen werden
mit `FOR NO KEY UPDATE` gesperrt, damit Kapitänsübergaben nicht durch reine
Fremdschlüsselprüfungen an anderen User-Zeilen blockieren. Check-in sperrt bei seinen
Joins nur die Eventanmeldung und nicht zusätzlich die User-Zeile.

Nach dem Update:

```bash
python manage.py migrate
python manage.py seed_translations
```

Die Migration `users.0010_user_deleted_at` ergänzt ausschließlich das Löschdatum.
Bestehende Accounts bleiben aktiv wie bisher.

## Prüfung

```bash
DB_ENGINE=sqlite python manage.py test users.test_account_deletion --noinput
# Mit einer konfigurierten PostgreSQL-Testinstanz:
DB_ENGINE=postgresql python manage.py test users.test_account_deletion --noinput
```

26 Funktionstests bestehen lokal unter SQLite. Fünf zusätzliche Parallelitätstests
mit getrennten Verbindungen prüfen Zahlung vor/nach Löschung, parallele Anmeldung
und veraltete Profiländerungen sowie gleichzeitige Löschungen bei Kapitänsübergabe.
Sie werden unter SQLite übersprungen; ein separater
PostgreSQL-16-Job in `.github/workflows/ci.yml` führt sie aus. Dieser CI-Lauf wurde
lokal nicht ausgeführt, da keine PostgreSQL-Instanz verfügbar ist.

Der abschließende Lauf von `users`, `events` und `tournaments` besteht mit 291
ausgeführten Tests und fünf PostgreSQL-bedingten Überspringungen (296 insgesamt).
Die LAN-Simulation leert ihren Cache vor jedem Lauf, damit Verifizierungslimits
vorangegangener Tests das Ergebnis nicht abhängig von der Testreihenfolge verändern.

Der lokale Gesamtlauf ergab 565 erfolgreiche Tests und einen Fehler im bestehenden
Medien-Test `test_uploaded_background_is_saved_and_used_for_export`: Windows kann
eine noch geöffnete temporäre PNG-Datei nicht entfernen (`WinError 32`). Derselbe
Fehler wurde im unveränderten Git-Ausgangsstand separat reproduziert.

`manage.py check` und der Migrationsabgleich für `users` bestehen. Der globale
Migrationsabgleich meldet bereits im Ausgangsstand abweichende Farbdefaults im
Modul `configuration`; diese werden durch die Kontolöschung nicht verändert.

Die Profilansicht und die Inline-Bestätigung wurden außerdem mit einer getrennten
lokalen Testdatenbank im Browser geprüft, einschließlich 390-Pixel-Mobilansicht
ohne horizontalen Überlauf.
