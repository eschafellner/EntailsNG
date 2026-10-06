# Automatische Solo-Team-Reaktivierung

> Seit 5. Oktober 2026 verwendet das Projekt ausschließlich PostgreSQL, auch lokal und für Tests. Testbefehle benötigen eine konfigurierte PostgreSQL-Verbindung; erwähnte SQLite-Ergebnisse sind historische Prüfstände vor der Umstellung. Die vollständige PostgreSQL-Suite einschließlich Parallelität und Backups läuft gemeinsam in CI.

Bei der normalen Anmeldung zu einem Einzelspieler-Turnier wird das Team des
Spielers für das betreffende Spiel automatisch ausgewählt. Eine zusätzliche
Aktion im Teammanager ist dafür nicht erforderlich.

## Auswahl und Reaktivierung

1. Ein bereits aktives Einzelspieler-Team desselben Accounts und Spiels für die
   Zielveranstaltung wird wiederverwendet. Auch ein bestehendes reguläres Team
   für ein Spiel mit Teamgröße 1 zählt dazu. Ein Team ohne Veranstaltungszuordnung
   erhält die Zielveranstaltung.
2. Gibt es kein aktives Team, wird ein archiviertes **Solo-Team** desselben
   Kapitäns und Spiels reaktiviert. Ein Archiv der Zielveranstaltung hat Vorrang;
   sonst wird das zuletzt geänderte Solo-Team gewählt. Weitere Archive werden
   weder zusammengeführt noch verändert.
3. Ohne geeignetes Team wird ein neues Solo-Team angelegt.

Bei der Reaktivierung bleiben Team-ID, Name, Slug und Einladungscode bestehen.
Die aktuelle Veranstaltungszuordnung wird geändert und der Archivstatus entfernt.
Die bestätigte Kapitänsmitgliedschaft wird bei Bedarf wiederhergestellt.

## Historie und Account-Trennung

Die alten Turnieranmeldungen behalten ihre ursprünglichen Turniere, Seeds,
Punktestände und Aufgaben. Matches, Sieger und Schweizer Rundeneinträge bleiben
unverändert. Für das neue Turnier entsteht eine eigene Anmeldung ohne Übernahme
alter Ergebnisse oder Aufgaben. Die ursprüngliche Veranstaltung ist weiterhin
über das jeweilige Turnier zugeordnet; `Team.event` bezeichnet den aktuellen Einsatz.

Die Auswahl erfolgt über die Benutzer-ID. Ein neu registrierter Account mit dem
alten Benutzernamen oder derselben E-Mail-Adresse erhält ein eigenes Team und
keinen Zugriff auf den Restdatensatz des gelöschten Accounts.

Der erneute Abschluss einer früheren Veranstaltung archiviert keine Teams,
die inzwischen einer anderen Veranstaltung zugeordnet sind. Alte Teams ohne
Veranstaltungszuordnung werden weiterhin anhand ihrer Turnierhistorie archiviert.

## Konflikte und Transaktionen

Eine Reaktivierung wird gesperrt, wenn das gewählte Team noch an einem laufenden
oder bereits generierten Turnier teilnimmt. Auch eine ungestartete, nicht
abgeschlossene oder abgesagte Anmeldung in einer anderen Veranstaltung muss
zuerst geklärt werden.

Mehrere aktive Teams, eine aktive Mitgliedschaft in einem anderen Team, ein
aktives Team einer anderen Veranstaltung oder zusätzliche bestätigte Mitglieder
im Solo-Team führen zu einer verständlichen Fehlermeldung mit Hinweis auf die
Orga. Bestehende Daten werden dabei nicht automatisch gelöscht.

Check-in, Anmeldefenster, Veranstaltungsstatus und Teilnehmerlimit gelten weiter.
Reaktivierung, Mitgliedschaft und neue Turnieranmeldung erfolgen in einer
Transaktion. Scheitert die Anmeldung, bleiben Archiv und Mitgliedschaften im
vorherigen Zustand.

Die Dienste sperren zuerst den Spieler, dann alle beteiligten Veranstaltungen
nach ID, danach das Zielturnier und die Teams. So werden parallele Anmeldungen
und der Start alter Turniere mit der Reaktivierung abgestimmt. Der öffentliche
Solo-Helfer verwendet dieselben Benutzer- und Veranstaltungssperren.

## Regressionstests

`tournaments.test_solo_reactivation` prüft den Frontend-POST, Teamidentität,
komplette Schweizer Ergebnisse und Tabellen, historische Aufgaben, mehrere
Anmeldungen, wiederhergestellte Mitgliedschaften, Archivauswahl, Konflikte,
Rollback, Account-Trennung und erneuten Eventabschluss.

`tournaments.test_audit_concurrency` enthält zusätzlich PostgreSQL-Tests für zwei
parallele Solo-Anmeldungen und eine Reaktivierung während einer Statusänderung
des alten Turniers. Diese Tests sind im PostgreSQL-16-CI-Job enthalten. Lokal auf
SQLite werden sie übersprungen; echte Zeilensperren sind dort nicht überprüfbar.

Keine zusätzliche Datenbankmigration ist notwendig.

Verifikation am 1. Oktober 2026: Die Integrationsprüfung für Turniere,
Account-Löschung, Events und Medien umfasst 354 Tests: 337 bestanden,
17 PostgreSQL-Fälle auf SQLite übersprungen, keine Fehler. Darin waren die ersten
18 Solo-Reaktivierungsfälle enthalten. Anschließend wurden alle 22 Solo-Fälle
einschließlich vier ergänzter Randfälle erfolgreich geprüft. `manage.py check`,
`makemigrations tournaments --check --dry-run` und `git diff --check` waren
erfolgreich. Die bereits dokumentierte globale Abweichung der Theme-Farbdefaults
bleibt außerhalb dieser Erweiterung bestehen.
