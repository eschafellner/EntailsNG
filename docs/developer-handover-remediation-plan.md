# Lösungsvorschlag zu den priorisierten Maßnahmen

Stand: 15. Oktober 2026. Grundlage: `docs/developer-handover-audit-2026-10-15.md`, HEAD `97026fd` und die dort erfassten lokalen Änderungen. Dieses Dokument hält den ursprünglichen Lösungsvorschlag und seine Abnahmekriterien fest. Die Implementierung ist inzwischen begonnen; der jeweils nachgewiesene Stand steht in [remediation-progress.md](remediation-progress.md). Die folgenden Formulierungen als Vorschlag beschreiben den damaligen Plan, nicht den aktuellen Dateibestand. Ein Produktionsdeployment ist nicht Teil der Umsetzung.

Die eindeutigen Dokumentationskorrekturen sind bereits als uncommittierter Diff vorhanden: richtiges Setup ohne Demo-Fixture, eigener Superuser, Env-Matrix, Worker, CI, Tunnel-Origin, Teamcode-Rotation und offene Probleme. Die folgenden Arbeitspakete schließen die verbleibenden technischen und organisatorischen Lücken.

## Priorität und Reihenfolge

| Paket | Priorität | Ergebnis | Abhängigkeit |
| --- | --- | --- | --- |
| P1 | Hoch | Verlässlicher Demo-Datensatz und gemeinsamer Initialisierungspfad | Keine |
| P2 | Hoch | Korrekte Deploymentvorgaben und prüfbare Updateanleitung | Keine; parallel zu P1 bearbeitbar |
| P3 | Mittel | Automatisierter Setup-, Container- und Redis-Nachweis | Baut auf P1/P2 auf |
| P4 | Mittel | Dokumentierte Behandlung von USERS-03 mit überprüfbarem Rechtebestand | Keine; bestehende Zurückstellung bleibt gültig |
| P5 | Niedrig | Kurze Übergabe mit getrennten historischen Nachweisen | Nach technischen Änderungen aktualisieren |
| P6 | Niedrig | Messbare Leistungs-/Darstellungsziele und gepflegter Backlog | Baseline erforderlich |

Keine belastbare Aufwandsschätzung ist aus dem Audit ableitbar. Vor allem Demo-Datenbeziehungen und ein echter Containerlauf können weitere Fehler zeigen. Die Pakete sollten getrennte Commits bzw. PRs mit jeweils eigener Abnahme erhalten.

## P1 – Demoimport durch einen zentralen Datengenerator ersetzen

**Problem und Beleg:** Nach `migrate` werden E-Mail-Vorlagen bereits in `emails/apps.py:10` angelegt. Der Snapshot verwendet für dieselben Vorlagen feste IDs (`initial_data.json:9015`); dadurch scheitert `loaddata`. `entrypoint.sh:73`, `install.sh:109` und `configuration/management/commands/reset_demo_data.py:20` besitzen eigene Importwege. Die Shellskripte löschen vor dem Import außerdem globale Texte/Navigation außerhalb der Importtransaktion. Ein Verschieben vor die expliziten Seeds behebt das automatische `post_migrate`-Seeding nicht.

**Empfehlung:** Ein kleiner synthetischer Datensatz wird über einen gemeinsamen Service erzeugt. Der vorhandene Snapshot wird nach Umstellung aller Aufrufer aus dem unterstützten Setup entfernt. Eine bloße Reparatur seiner drei E-Mail-Template-IDs würde weitere Beziehungen, alte Datumswerte und Accounts weiterhin ungeprüft übernehmen.

Vorgeschlagene Umsetzung:

1. Neue zentrale Implementierung `configuration/demo.py` und Managementkommando `seed_demo_data`. CLI, Installer und Dockerinitialisierung verwenden ausschließlich diesen Weg. Der Service liest keine produktiven Exporte ein.
2. Minimalen Umfang festlegen: ein Event mit relativ zum Erstellungszeitpunkt künftigen Terminen, aktive Tickets, ein kleiner Sitzplan, synthetische Gäste und Anmeldungen, ein Clan, Spiele/Teams und ein Turnierentwurf. Nur lokale Assets; Adressen unter `example.invalid`. Als Standard kostenlose Tickets, damit keine Bankdaten erforderlich sind. Weitere Turniermodi bleiben Aufgabe der vorhandenen Fachtests.
3. Systemtexte, Navigation und E-Mail-Vorlagen über bestehende Seedkommandos ergänzen. Keine festen Primärschlüssel für diese Daten; Auflösung über `key` bzw. `url_name`. Vorhandene Anpassungen erhalten, kein implizites `--reset`. Mailkonfiguration nicht auf reale Zustellung umstellen; keine Mailjobs durch Demodaten erzeugen.
4. Alle Datenbankänderungen in einer Transaktion. Vorgeschlagen ist ein kleiner Datensatz `DemoDataset` mit eindeutigem Namen, Formatversion und Erstellungszeitpunkt in `configuration/models.py` samt Migration. Dieser dokumentiert die abgeschlossene Initialisierung. Der Service serialisiert parallele Aufrufe zusätzlich mit einer transaktionsgebundenen PostgreSQL-Sperre; Marker und Fachdaten werden gemeinsam committed. Das nutzt den bereits verbindlichen PostgreSQL-Stack.
5. Frische Datenbank bedeutet hier: keine fachlichen Gäste/Event-/Clan-/Team-/Buchungsdaten; Migrationsdaten, System-Seeds und ein selbst angelegter Administrator sind erlaubt. Bei bestehenden Fachdaten ohne gültigen Demo-Marker vor dem ersten Schreibzugriff abbrechen. Ein fehlender Superuser ist **kein** hinreichender Nachweis einer leeren Installation. Bei vorhandenem Marker derselben Version wiederholter Aufruf ohne Änderungen; bei Versionsabweichung oder widersprüchlichem Zustand verständlicher Abbruch statt Reparatur auf Verdacht.
6. Demo-Gastkonten mit `set_unusable_password()` anlegen. Adminzugang weiter über `createsuperuser`; falls ein Gastlogin benötigt wird, für das gewünschte synthetische Konto individuell `changepassword` ausführen. Keine Standardpasswörter oder importierten Rechte-Gruppen.
7. `DEMO_MODE` bleibt explizit und standardmäßig aus; ein manuell aufgerufenes Kommando benötigt ebenfalls eine ausdrücklich aktivierte Demo-Umgebung. Eine Demo darf durchaus mit `DEBUG=False` demonstriert werden; deshalb DEBUG nicht als alleinigen Schutz verwenden. Der Produktionsinstallationspfad ruft den Generator nie automatisch auf.
8. `entrypoint.sh` und `install.sh`: Lösch-/`loaddata`-/globale Sequenzreset-Blöcke entfernen; Generator einmal aufrufen und Fehler mit Exitstatus weitergeben. Erforderliche System-Seeds nicht weiter mit `|| true` als erfolgreich behandeln; die Initialisierung soll bei deren Fehler abbrechen und einen klaren Fehler loggen.
9. `reset_demo_data` und die Adminaktion nicht länger als „Werkseinstellungen“ bezeichnen: Es handelt sich zunächst um „Demo-Daten einrichten“, mit denselben Schutzregeln und ohne automatische Löschung. Den alten CLI-Namen vorübergehend als Alias mit Hinweis erhalten. Ein tatsächlich destruktiver Reset bestehender Demos ist ein separater Funktionsumfang und gehört nicht in diese Fehlerbehebung.

**Abnahme:** Migration + Seeds + Demoerstellung auf leerem PostgreSQL erfolgreich; erneuter und paralleler Aufruf erzeugen genau einen vollständigen Datensatz; ein absichtlich ausgelöster Fehler hinterlässt weder Teilobjekte noch einen Marker. Auf einer belegten Datenbank werden keine Fachdaten, Navigation oder Texte verändert. Ein Aufruf ohne Demoaktivierung bricht vor Änderungen ab. Kein Standardadmin, kein nutzbares Gastpasswort und keine Mailaufträge entstehen. Nach dem Lauf kann ein neu angelegter Administrator alle Demoseiten öffnen; Eventbereitschaft meldet fehlende Mailkonfiguration verständlich. Installer, Container und CLI nutzen denselben Service. Neue Regressionstests gehören in `configuration/test_demo_data.py`; die vorhandenen Reset-Tests werden an die präzisierte Semantik angepasst.

## P2 – Deploymentvorgaben und Updates absichern

**Problem und Beleg:** `.env.example:29` erlaubt nur die Beispieldomain, während der Healthcheck aus `docker-compose.yml:58` den Host `127.0.0.1:8000` verwendet. Der Audit reproduzierte HTTP 400 ohne Loopbackeintrag. Der Tunnel benötigt bereits im aktuellen Code den internen Eingang auf Port 8080 (`nginx/templates/default.conf.template:80`). Migration 0017 ist bereits vorhanden und rotiert Codes unwiderruflich; sie darf nicht erneut erfunden oder umgeschrieben werden.

Vorgeschlagene Umsetzung:

- `.env.example` um `127.0.0.1` in `ALLOWED_HOSTS` ergänzen und den Grund direkt daneben erklären. Bestehende Installationen benötigen dieselbe gezielte Anpassung. Nicht automatisch beliebige Hosts oder Proxyheader freigeben.
- Neue Anleitung `docs/updating.md` mit getrennten Wegen für Tunnel und VPS. Reihenfolge: Arbeitsstand und verwendete Profile aufnehmen, versionsgebundene Sicherung prüfen, Änderungen und Migrationen lesen, bei Tunnel Origin auf HTTP `nginx:8080` setzen, zusammengehörige App-/Workerimages aktualisieren, bei geänderten Mounts Nginx/Certbot neu erstellen, danach Dienste und Zugriff prüfen. Während nicht kompatibler Änderungen schreibende Zugriffe/Worker kontrolliert pausieren.
- Im Updatehinweis erklären, dass die **erste** Anwendung von 0017 bestehende Code-Einladungen ungültig macht; spätere `migrate`-Aufrufe dürfen sie nicht erneut rotieren. Eine Rückkehr zu altem Code ist nach dieser Datenmigration kein gewöhnliches `migrate` rückwärts. Der bestehende Backupmechanismus verlangt denselben Code-/Migrationsstand; Wiederherstellung daher nur mit der dazugehörigen Version und einem zuvor geprüften Verfahren. Zugangsschlüssel und Daten-Volumes nicht in Updatekommandos löschen.
- Neues read-only Kommando `check_runtime` vorschlagen: prüft aktuelle DB-Erreichbarkeit, fehlende Migrationen, DB- und native Backup-Tool-Hauptversion bei aktiviertem Backup, Cachebackend/Erreichbarkeit sowie eine ausdrücklich übergebene Healthcheck-Hostangabe. Ausgaben enthalten Status und Variablennamen, keine Schlüssel, Passwörter oder Verbindungs-URLs mit Zugangsdaten. Es führt weder Seeds noch Migrationen aus. Die Prüfung des tatsächlich ausgewählten Django-Cachebackends verhindert einen versehentlichen LocMem-Nachweis.
- Healthcheck und externe Erreichbarkeit getrennt abnehmen. Ein erfolgreicher interner Request beweist weder Tunnel-Origin noch Zertifikat. Cloudflare-Dashboard und echte ACME-Erneuerung benötigen einen eigenen Betriebsnachweis; diese Informationen sind nicht aus dem Repository ableitbar.

**Abnahme:** Produktionskonfiguration mit Beispiel-Hostliste plus Loopback liefert intern 200; fehlender Loopbackeintrag wird im Check verständlich beanstandet. DB-/Cacheausfall führt zu einem fehlgeschlagenen Laufzeitcheck. Öffentliche Proxy-Eingänge vertrauen weiterhin keinen gefälschten Clientheadern, Tunnelport 8080 bleibt unveröffentlicht. 0017 auf Testteams angewendet ändert die Codes; erneutes `migrate` lässt sie unverändert. Bei VPS-Konfigurationsänderungen bleiben die vorhandenen Bootstrap-Regressionen aus `config/test_review_project.py:23` grün. Echte Tunnel-/Zertifikatsprüfungen erfolgen erst in einer autorisierten Zielumgebung.

## P3 – Setup und Betrieb in CI reproduzierbar prüfen

**Ausgangspunkt:** Die bestehende CI prüft Django und JavaScript, baut aber kein Image und verwendet während Django-Tests bewusst LocMemCache (`.github/workflows/ci.yml`, `config/settings.py:175`). Die umfassende Suite bleibt erhalten; zusätzliche Checks konzentrieren sich auf bisher fehlende Integrationsnachweise.

Vorgeschlagene Erweiterung in drei Stufen:

| Stufe | Ablauf | Abnahme |
| --- | --- | --- |
| Frischer Setupweg | Separate leere PG16-Datenbank: migrate, drei Seeds, synthetische Demoerstellung, Wiederholung, individueller Testadmin, Seiten-/Healthprüfung, Migrationsabgleich. Secrets nur zur Laufzeit erzeugen. | Keine manuellen Datenkorrekturen, keine Vorlagenkonflikte, keine Änderung beim Wiederholungslauf. Logs und Laufzeitversionen als bereinigtes CI-Artefakt. |
| Tatsächlicher Redis | Eigenen Prozess außerhalb von `manage.py test` mit Produktionssettings starten; Cachebackend prüfen, eindeutigen Testschlüssel setzen, aus zweitem Prozess lesen, TTL und gezielte Löschung prüfen. | RedisCache ist wirklich aktiv; Werte prozessübergreifend sichtbar; bei nicht erreichbarem Redis scheitert die Betriebsprüfung. Nur den eigenen Testschlüssel löschen, kein `cache.clear()` gegen fremde Bestände. |
| Container | Eigener Job auf einem frischen CI-Runner: temporäre `.env`, tatsächliches Compose-/Imagebuild, db/redis/web/Worker/nginx, Healthzustand und ausgewählte HTTP-Pfade prüfen. Tunnel/Certbot nur konfigurationsseitig prüfen. | Gebautes Image startet mit frischen Volumes; statische Assets und Dienste sind erreichbar; Worker bleiben laufend; Fehlerlogs verfügbar, keine Secrets im Artefakt. Abschließendes Aufräumen nur der CI-Ressourcen. |

Die festen `container_name`-Werte und Hostports in Compose erlauben keine beliebige Isolation nur durch einen anderen Projektnamen. Deshalb den Containerjob auf einem eigenen kurzlebigen Runner ohne parallel laufende Entails-Dienste ausführen; einen lokalen Smoke-Aufruf bis zu einer gesonderten Isolierung nicht als sicher für bestehende Installationen anbieten. Der Job darf nie eine vorhandene Anwendungs-`.env` übernehmen.

Vorgeschlagene Dateien: `scripts/setup_smoke.py`, `.github/workflows/ci.yml` und Regressionstests für `check_runtime`. Wiederholte Seedaufrufe werden anhand unveränderter Datensätze geprüft, nicht nur anhand eines erfolgreichen Exitstatus. Nach Umsetzung der kleinen Pakete die vollständige Suite einmal als gemeinsame Regression ausführen.

**Reproduzierbarkeit anschließend:** Die unterstützte Primärumgebung bleibt zunächst Python 3.12/PostgreSQL 16. qrcode erhält einen nach dem Containerlauf bestätigten exakten Pin; `latest`-Images werden durch im selben Testlauf geprüfte Versionen/Digests ersetzt. Keine Versionsnummer auf Verdacht wählen. Weitere Python-Versionen erst dann ausdrücklich unterstützen, wenn eine entsprechende CI-Matrix beschlossen und grün ist.

## P4 – USERS-03 sichtbar und betrieblich prüfbar halten

**Bestehende Entscheidung:** Die Einschränkung delegierter Benutzerverwaltung wurde ausdrücklich zurückgestellt (`review/users-findings.md:106`). Dieser Lösungsvorschlag hebt diese Entscheidung nicht auf und sieht zunächst keine Änderung an `users/admin.py`, Gruppen oder Permissions vor.

Empfohlen ist ein ausschließlich lesender Berechtigungsbericht für die Zielinstallation: aktive Staffkonten mit effektivem `users.change_user`, einschließlich direkter und über Gruppen vergebener Rechte, getrennt von ohnehin privilegierten Superuserkonten. Ergebnis privat als Betriebsnachweis ablegen; keine echten Benutzerlisten ins Repository aufnehmen. Das Recht ist bei der aktuellen Implementierung als weitreichende Administrationsbefugnis zu behandeln, nicht als bloße Profilpflege.

**Abnahme:** Ein Eintrag im Sicherheitsbacklog nennt Finding, konkrete Bedingung, verantwortliche Rolle, Entscheidung „zurückgestellt“ und erneuten Prüfzeitpunkt bzw. Anlass „Vergabe von Benutzerverwaltungsrechten an weitere Mitarbeitende“. Der Bericht verändert keine Rechte. Die tatsächlich berechtigten Konten werden erst durch diesen Zielsystembericht nachgewiesen; der Audit kennt sie bislang nicht.

Falls delegierte Profilpflege später ausdrücklich gewünscht wird, ist das ein separates Arbeitspaket: serverseitiger Schutz von Rechtefeldern, Gruppen/Permissions, privilegierten Zielkonten und Passwortänderungen, mit Tests für direkt manipulierte POSTs. Nur ausgeblendete oder readonly gesetzte Formularfelder wären keine ausreichende Gesamtlösung.

## P5 – Übergabe als kurzen Einstieg pflegen

Die langen datierten Prüfberichte aus dem Kopf der Übergabe in `docs/verification-history.md` verschieben. Datum, damaligen Umfang und Einschränkungen beibehalten; historische Ergebnisse nicht auf neue Zahlen umetikettieren. Die Übergabe behält Zweck, Architektur, reproduzierbares Setup, Konfiguration, Tests, Betrieb, Entscheidungen und offene Punkte sowie Links auf Fachberichte.

Für jeden neuen Prüfnachweis Commit/Dirty-Status, Runtimeversionen, konkreten Befehl, Ergebnis und Grenzen angeben. Die Zusammenfassung im Handover verweist auf den Nachweis, statt historische Testzahlen zu sammeln. Zuständigkeit nach Rollen festlegen: Entwicklung für Setup/CI, Betrieb für Deploymentnachweise, Produktverantwortung für Funktionsprioritäten. Konkrete Personen sind bislang nicht festgelegt.

**Abnahme:** Alle bisherigen historischen Inhalte sind auffindbar; lokale Links funktionieren. Eine Person ohne Projektkenntnis kann anhand der Übergabe auf einer frischen Testumgebung installieren, den Admin öffnen und die dokumentierten Prüfungen ausführen. Schwierigkeiten dieses Durchlaufs werden als konkrete Dokumentations- oder Codefehler erfasst.

## P6 – Aussagen messbar machen und Backlog trennen

**Leistung:** „50 bis 1.000+ Teilnehmer“ zunächst ausdrücklich als Zielgröße registrierter Gäste kennzeichnen, ohne daraus gleichzeitige Zugriffe abzuleiten. Das vorhandene Skript `scripts/performance_smoke.py:74` deckt Größen 50/250/1000 ab, verwendet aber Djangos Testclient. Es eignet sich als Vergleich der Anwendungslogik; für eine Aussage über das Gesamtsystem zusätzlich denselben Ablauf per HTTP gegen Gunicorn/Nginx ausführen. Hardware, Workerzahl, Datenvolumen und Parallelität dokumentieren. Vorschlag für Szenarien: Anmeldung, Sitzplatzkonkurrenz und Check-in mit 1/12/32 parallelen Vorgängen. p50/p95/p99, Fehler und Sperrwartezeiten messen. Akzeptierte Grenzwerte werden nach der ersten reproduzierbaren Baseline beschlossen; bisher liegen dafür keine verbindlichen Produktziele vor.

**Darstellung und Barrierefreiheit:** Prüfumfang vorab definieren: Registrierung/Login, Dashboard, Sitzplan, Turnier und Kontakt; alle neun Themes bei 1440/390/320 Pixeln, Tastaturbedienung, sichtbarer Fokus, Formularfehler und Kontrast. Automatische Prüfungen durch manuelle Tastatur-/Screenreader-Stichproben ergänzen. Einzelne grüne Checks nicht als umfassende WCAG-Zertifizierung ausgeben. Findings und Nachweise separat speichern.

**Backlog:** Technische Fehler von Funktionsideen trennen. Für jede Idee Problem, Nutzende, Abnahmekriterien, fachliche Priorität, Abhängigkeiten und verantwortliche Rolle ergänzen. Beim Check-in klarstellen: bestehende Scannerzahlen sind geliefert; Dashboardwidget und Stoßzeitauswertung sind zusätzliche Funktionen. Keine automatische Umsetzung von WebSockets, PDF-Exporten oder Clanmeisterschaft aus diesem Audit ableiten.

**Abnahme:** Jede Leistungs-/Qualitätsaussage verweist entweder auf einen passenden aktuellen Nachweis oder ist ausdrücklich als Ziel bzw. ungeprüfte Eigenschaft bezeichnet. Funktionsideen besitzen einen überprüfbaren Status; unbekannte Produktprioritäten und Verantwortliche sind als offen markiert.

## Empfohlene Umsetzungsschnitte

1. **Demo-Daten und Initialisierung:** P1 mit gezielten PostgreSQL-Regressionen; bestehende Import-/Resetdokumentation gleichzeitig anpassen.
2. **Deploymentkorrektur:** P2 einschließlich Beispiel-Hostliste, read-only Laufzeitcheck und Updateanleitung. Keine Ausführung gegen Produktion als Bestandteil der Codeänderung voraussetzen.
3. **Integrationsnachweis:** P3 auf Wegwerfumgebungen; danach gemeinsamer vollständiger Regressionstest und geprüfte Dependency-/Imagepins.
4. **Rechteentscheidung dokumentieren:** P4 ohne Rechteänderung; Zielsystemnachweis als gesonderte Betriebsaufgabe.
5. **Dauerhafte Dokumentation und Messgrundlage:** P5/P6, nachdem die neuen Setupbefehle tatsächlich existieren und geprüft sind.

Dieser Vorschlag ist abnahmefähig, sobald die genannten Ergebnisse pro Paket nachgewiesen sind. Dokumentationsänderungen allein schließen den Demoimport-, Container- oder Produktionsnachweis nicht ab.
