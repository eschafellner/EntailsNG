# Globale Orga-Sperren

Stand: 7. Oktober 2026. Sperren gelten für das gesamte System und laufen nicht
automatisch ab. Eine berechtigte Orga muss sie ausdrücklich aufheben.

## Bedienung und Rechte

Im Django-Admin unter **Benutzer** den Account öffnen und **Benutzer sperren /
Sperre aufheben** wählen. Die Seite zeigt die Auswirkungen, verlangt eine interne
Begründung und eine ausdrückliche Bestätigung. Bereits gesperrte Accounts zeigen
die aktive Sperre und deren Historie. Die Benutzerliste lässt sich nach
**Durch Orga gesperrt** filtern.

Erforderlich sind Mitarbeiterstatus, Änderungsrechte für Benutzer und die neue
Berechtigung **Benutzer global sperren und Sperren aufheben**
(`users.manage_user_bans`). Superuser haben sie automatisch. Mitarbeiter und
administrative Accounts können nur von Superusern gesperrt werden. Selbstsperren
sind ausgeschlossen. Sperre und Aufhebung werden mit Bearbeiter, Zeitpunkt und
Begründung protokolliert. Die bisherigen Login-Fehlversuchssperren bleiben separat;
deren Entsperraktion hebt eine Orga-Sperre nicht auf.

Unter **Orga-Sperren** stehen eine ausschließlich lesbare Historie und die Aktion
**Bekannte E-Mail-Adresse sperren** bereit. Damit können bekannte weitere Adressen
oder Adressen bereits gelöschter Accounts ausdrücklich gesperrt werden. Existiert
für die Adresse ein Account, wird dieser ebenfalls gesperrt. Eine solche manuelle
Entscheidung darf keine bloße Vermutung über eine fremde Adresse sein.

Mehrere unabhängig angelegte Adresssperren müssen einzeln aufgehoben werden.
Sperrbegründungen sind ausschließlich für berechtigte Orgas sichtbar. In Freitexten
keine unnötigen Angaben zu betroffenen Dritten speichern.

## Auswirkungen

- Login und vorhandene Sitzungen werden ungültig. Die Sitzungsrevision wird auch
  bei der Aufhebung erhöht; alte Sitzungen können danach nicht wieder benutzt werden.
- Aktivierungs- und E-Mail-Änderungscodes werden entwertet. Passwort-Reset-Links
  werden ungültig und bleiben es nach der Aufhebung. Das vorhandene Passwort wird
  durch die Sperre nicht geändert.
- Neue Event-/Turnieranmeldungen und persönliche Sitzplatzreservierungen werden
  blockiert. Gesperrte Spieler können nicht in neue Turnierkader übernommen werden.
- Check-in über QR-Code, Kurzcode, Scanner, Admin-Aktion, Check-in-Services
  und manuelle Adminbearbeitung wird gesperrt. Vorhandene QR-Ticket-Tokens werden
  erneuert. Bei laufenden oder zukünftigen Events wird der aktuelle Check-in
  zurückgesetzt; historische Check-in-Daten beendeter Events bleiben erhalten.
- Buchungen, Zahlungsstände, Sitzplatzzuweisungen, Team-/Clanmitgliedschaften und
  Turnierergebnisse bleiben erhalten. Stornierungen, Rückzahlungen, Kadernachfolge
  oder Disqualifikationen muss die Orga separat entscheiden. Die Sperre ändert
  weder erzielte Ergebnisse noch die Historie des Turniers.

Nach einer Aufhebung wird nur ein zuvor aktiver und bestätigter Account wieder
aktiviert. Zuvor unbestätigte/deaktivierte Accounts bleiben inaktiv. Für diese kann
der vorhandene Aktivierungsablauf neu genutzt werden. Alte QR-Codes bleiben
ungültig; die Orga kann ein Ticket mit dem neuen Token ausgeben. Der bestehende
Kurzcode ist wieder nutzbar, wenn der Check-in regulär zulässig ist.

## Registrierung und gelöschte Accounts

Die Registrierung gibt bei einem Treffer ausschließlich diese Meldung aus:

> Die Registrierung konnte nicht abgeschlossen werden. Bitte wende dich an die Organisatoren.

Es wird kein Account angelegt und keine Aktivierungsmail eingereiht. Die Prüfung
liegt vor der Eindeutigkeitsprüfung von Benutzername/E-Mail und wird beim Anlegen
unter einer PostgreSQL-Transaktionssperre erneut durchgeführt. Dadurch kann auch
ein bereits zuvor validiertes Formular die Sperre nicht umgehen.

`User.is_banned` ist ein eigenständiger Zustand. `is_active=False` dient zusätzlich
der Integration mit vorhandenen Zugangs- und Kaderprüfungen. Alte Profil- oder
Adminobjekte können die Sperre oder deren Sitzungsrevision nicht überschreiben.
Die normale Benutzerbearbeitung kann den Account nicht reaktivieren. Gesperrte
Accounts können im Benutzer-Admin nicht direkt gelöscht werden.

Die Registrierungssperrliste speichert ausschließlich HMAC-SHA256-Fingerabdrücke
normalisierter Adressen und die Kennung des zugehörigen Schlüssels, keine weitere
Klartextkopie der Adresse. Normalisierung ist dieselbe wie bei Benutzeraccounts:
Leerzeichen außen entfernen und Kleinschreibung. Providerabhängige Regeln zu
Plus-Adressen oder Punkten werden nicht pauschal angewandt.

Automatisch wird die aktuell bestätigte Adresse aufgenommen. Aktive bestehende
oder ausdrücklich durch einen Admin aktivierte Accounts gelten als bestätigt.
Unbestätigte Accounts und offene, unbestätigte E-Mail-Änderungen führen nicht zu
automatischen dauerhaften Adresssperren. Solange ein unbestätigter gesperrter
Account existiert, erhält auch dessen Adresse die neutrale Registrierungsablehnung.
Eine bekannte Adresse kann die Orga ausdrücklich zur Sperrliste hinzufügen.

Accountlöschung und Sperrliste sind getrennt. Die Sperre bleibt bei einer
Selbstlöschung mit anonymisiertem Restdatensatz erhalten; auch eine spätere
Löschung des User-Datensatzes entfernt sie nicht. Es gibt keine automatische
Entsperrung durch Löschung oder Wiederregistrierung. Bereits vor Einführung der
Funktion gelöschte Adressen werden nicht rekonstruiert.

Die Fingerabdrücke sind pseudonymisierte sensible Daten. Aufbewahrung,
regelmäßige Überprüfung und Bereinigung der internen Begründungen sind durch die
Orga festzulegen. Eine neue, unbekannte E-Mail-Adresse identifiziert nicht dieselbe
Person. Ein Hausverbot muss daher zusätzlich durch die Orga beim Einlass
durchgesetzt werden; IP-Adressen und Geburtsdaten werden nicht automatisch gesperrt.

## Installation und Schlüssel

1. Einen eigenen zufälligen Schlüssel mit mindestens 32 Zeichen erzeugen, zum
   Beispiel mit `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
2. Diesen als `USER_BAN_HMAC_KEY` in der Deployment-Konfiguration dauerhaft setzen.
   Getrennt von `SECRET_KEY` verwalten und sicher mit den Betriebsgeheimnissen
   sichern. Nicht in Git einchecken, nicht über den Admin bearbeiten und während
   aktiver Adresssperren nicht ändern. Backups der Datenbank enthalten den Schlüssel
   nicht automatisch; bei Wiederherstellung muss derselbe Schlüssel bereitstehen.
3. Migration und Übersetzungen einspielen, Webprozesse neu starten:

```sh
python manage.py migrate
python manage.py seed_translations
```

Erforderlich ist `users.0011_user_email_verified_user_is_banned_and_more`.
Bestehende aktive Accounts werden als E-Mail-bestätigt übernommen. Bestehende
Sitzungen und Reset-Links unverändert ungesperrter Accounts bleiben gültig.

Ohne konfigurierten Schlüssel können keine Orga-Sperren angelegt werden. Bei
vorhandenen aktiven Adresssperren führt ein fehlender oder veränderter Schlüssel
zu einer neutralen Ablehnung neuer Registrierungen und Codebestätigungen statt
zu einer unbemerkten Umgehung. Bestehende gesperrte Accounts bleiben gesperrt.
Die ursprüngliche Schlüsselkonfiguration muss dann wiederhergestellt werden.
Ein regulärer Schlüsselwechsel für bestehende Fingerabdrücke ist nicht enthalten.

## Tests

Am 7. Oktober 2026 bestanden **1.089 Tests** der vollständigen PostgreSQL-Suite.
Der abschließende gezielte Lauf bestand **29 Tests**, einschließlich zweier
zusätzlicher Regressionen für die manuelle Adresssperre/Aufhebung im Backend
und veraltete Zugriffe eines zwischenzeitlich gesperrten Organisators.
Systemprüfung und Migrationsabgleich waren erfolgreich. Sperren, neutrale
Registrierungsablehnung und manuelle Aufhebung wurden zusätzlich im Browser
gegen eine isolierte Testdatenbank geprüft.

Neue Regressionen liegen in `users.test_moderation` und
`users.test_moderation_concurrency`. Sie prüfen Rechte, CSRF, Gründe, Historie,
veraltete Formulare, Löschung und Wiederregistrierung, Schlüsselverlust/-wechsel,
Sitzungen mit signierten Cookies, Passwort-Reset, Bestätigungscodes,
E-Mail-Änderungen, bezahlte Tickets und tatsächliche PostgreSQL-Parallelität.

```sh
python manage.py test users.test_moderation users.test_moderation_concurrency --noinput
python manage.py test --noinput
python manage.py makemigrations --check --dry-run
```
