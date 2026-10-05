# Teamgrößenregel pro Turnier

Stand: 5. Oktober 2026.

Im Django-Admin unter **Turniere → gewünschtes Turnier → Regel zur Teamgröße**
kann die Turnierleitung zwischen drei Regeln wählen:

| Regel | Anmeldung | Turnierstart |
| --- | --- | --- |
| Vollständiges Team erforderlich | Nur vollständiger Kader | Nur vollständiger Kader |
| Team darf bis zum Start aufgefüllt werden | Unvollständiger Kader erlaubt | Nur vollständiger Kader |
| Unvollständige Teams zugelassen | Unvollständiger Kader erlaubt | Unvollständiger Kader erlaubt |

**Standard:** Vollständiges Team erforderlich. Die Migration setzt diese Regel
auch für vorhandene Turniere. Pro Turnier lässt sich die Regel vor der
Generierung ändern; anschließend sind Feld und Modellprüfung gesperrt.
Ein reguläres Zurücksetzen des Spielplans macht das Feld wieder bearbeitbar.
Ein Turnier-Neustart übernimmt die Regel in den neuen, bearbeitbaren Entwurf.

## Kader und Anmeldung

- Maßgeblich sind bestätigte Teammitglieder (`TeamMember.Status.ACCEPTED`).
  Offene Bewerbungen und Einladungen zählen nicht mit.
- Jede Regel verlangt mindestens ein bestätigtes Mitglied und erlaubt höchstens
  die beim Spiel konfigurierte Teamgröße. Für Einzelspieler bleibt es bei 1/1.
- Eine Anmeldung mit unvollständigem Kader belegt einen regulären Turnierplatz.
  Es entsteht keine zusätzliche Warteliste oder gesonderte Kapazität.
- Die bisherigen Regeln für Kapitän, Check-in, Spiel, Veranstaltung und
  archivierte Teams bleiben bestehen. Die bisherige Check-in-Ausnahme für die
  Turnierleitung ändert sich nicht.
- Teams können vor dem Start über die vorhandenen Funktionen Mitglieder
  aufnehmen. Ist dasselbe Team bereits in einem anderen laufenden/generierten
  Turnier gebunden, bleiben dessen bestehende Kadersperren maßgeblich.

## Anzeige und Startprüfung

Die Turnierdetailseite erklärt die gewählte Regel. Die Anmeldebereitschaft
berücksichtigt diese Regel und den Check-in der bestätigten Mitglieder.
Die Teilnehmerliste zeigt den aktuellen Kaderstand, etwa **4/5 bestätigte Spieler**.
Für angemeldete unvollständige Teams bleibt der Auffüllhinweis auch nach
Anmeldeschluss sichtbar. Bei dauerhaft erlaubtem unvollständigem Kader wird
stattdessen die Zulassung erklärt.

Die Turnierleitung sieht vor der Generierung eine Übersicht aller Kader, deren
Größe von der Spielvorgabe abweicht. Beim tatsächlichen Start prüft der Service
den aktuellen Kader erneut. Bei Problemen werden alle betroffenen Teamnamen
und Kaderstände ausgegeben; Matches werden nicht teilweise angelegt.
Eine strengere Regel entfernt vorhandene Anmeldungen nicht automatisch.
Teams müssen ihren Kader ergänzen oder vor dem Start abgemeldet werden.

Die Startprüfung gilt für alle sechs Turniermodi einschließlich Schweizer
Vorschau und Veröffentlichung. Andere Startprüfungen bleiben erhalten: aktive
Accounts, bestätigter Kapitän, passende Veranstaltung/Spiel, Archivstatus und
keine Spieler in mehreren Teams desselben Turniers. Interne Importaufrufe ohne
`actor` behalten ihren bisherigen Servicevertrag; öffentliche und administrative
Startaktionen übergeben den ausführenden Account und prüfen den Kader.

Regeländerungen und Generierung sperren dieselbe Turnierzeile. Eine Änderung,
die nach einem parallelen Start speichern möchte, wird erneut gegen den
generierten Datenbankstand geprüft. Schweizer Vorschautokens werden nach einer
Änderung der Teamgrößenregel ungültig.

## Installation

```sh
python manage.py migrate
python manage.py seed_translations
python manage.py collectstatic --noinput
```

Anschließend die Webprozesse neu starten. Neue Migration:
`tournaments.0013_tournament_roster_rule`. Die gemeinsame Turnier-CSS behebt
außerdem die schmale Metadatenspalte des Turnierkopfs auf Smartphones. Keine
neuen JavaScript-Dateien oder Abhängigkeiten erforderlich. Die lokale SQLite-App-Datenbank wurde migriert;
ein Deployment wurde nicht ausgeführt.

## Prüfung

```sh
DB_ENGINE=sqlite python manage.py test tournaments --noinput
```

325 Tests: 303 erfolgreich, 22 PostgreSQL-Parallelfälle auf SQLite übersprungen.
19 neue Funktionstests prüfen Regelmatrix, Kapazität, leere/zu große Kader,
bestätigte Mitglieder, Check-in, alle sechs Startmodi, atomare Ablehnung,
Regelsperre, Neustart, Schweizer Vorschautokens und die Frontendhinweise.
Zwei neue PostgreSQL-Fälle in `test_audit_concurrency` prüfen Regeländerung
gegen parallelen Start in beiden Reihenfolgen. Sie sind in der bestehenden
PostgreSQL-CI enthalten und wurden lokal nicht gegen PostgreSQL ausgeführt.

Im Browser wurden Spieler- und Orgaansicht mit einem 4/5-Kader, die gesperrte
Anmeldung unter der Standardregel sowie die freigegebene Anmeldung unter der
offenen Regel geprüft. Desktop und Smartphone (390 px) zeigen Regel und
Kaderhinweis; die mobile Metadatenspalte nutzt die volle Breite. Django-Systemcheck,
Migrationscheck für `tournaments` und Prüfung auf Whitespacefehler erfolgreich.
