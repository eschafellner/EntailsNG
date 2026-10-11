## Verifikationszusammenfassung

Bestätigt: **1** · Teilweise abgesichert: **0** · False Positive: **0** · Nicht entscheidbar: **0**.

Verifiziert am 2026-10-09. Originalbefund unverändert erhalten. Prüfung des Recovery-Kontrollflusses ausschließlich mit gemocktem Storage/Adapter; keine Datenbank, Sicherung oder Wiederherstellung verändert.

Zusammenfassung: 1 Finding — Kritisch: 0, Hoch: 0, Mittel: 1, Niedrig: 0, Info: 0.

Prüfumfang: Views/URLs, Formulare, verschlüsseltes Archivformat, private Dateispeicherung, PostgreSQL-Adapter, Job-/Restore-Services, Wartungsmiddleware, Dateisperren, Systemchecks, CLI-Befehle, Templates/JavaScript und Backup-Dokumentation/Proxyintegration. Die App besitzt keine eigenen Models, Admin-Modelklassen oder Migrationen. Aktive Superuser und CSRF werden für Verwaltungsaktionen verlangt; Restore verlangt zusätzlich Passwort und Bestätigung. Die absichtlich ohne Anmeldung erreichbare Fortschrittsanzeige benötigt einen zufälligen 256-Bit-Capability-Token und enthält nur Statusdaten. Archive werden vor ZIP-Auswertung vollständig authentifiziert; Pfade, Symlinks, Dateianzahl, Größen, Hashes, Migrationen und Softwarestand werden geprüft. Keine tatsächliche Sicherung oder Wiederherstellung ausgeführt.

### [BACKUPS-01] Fehler beim Aufräumen blockiert die Recovery einer bereits bestätigten Wiederherstellung
- Schweregrad: Mittel
- Kategorie: Bug
- Fundstelle: backups/services.py:312, :327, :364; backups/database.py:212; backups/management/commands/process_backup_jobs.py:26
- Beschreibung: Beim normalen Restore wird ein Fehler beim abschließenden Löschen der alten Datenbank abgefangen, da die neue Datenbank bereits bestätigt ist. Der entsprechende `phase == 'committed'`-Pfad in `recover_interrupted` ruft `finish` dagegen ohne Ausnahmebehandlung auf. Erst danach entfernt er den Wartungsmarker und markiert den Auftrag als abgeschlossen. Ein Cleanup-Fehler beendet die Recovery bzw. den Worker, bevor diese Schritte erfolgen.
- Auswirkung / Angriffsszenario: Ein Worker bricht nach dem persistenten `committed`-Journal und vor dem Entfernen des Wartungsmarkers ab. Beim nächsten Start ist der wiederhergestellte Stand bereits geprüft, aber ein Fehler beim Verbinden zur Verwaltungsdatenbank oder beim `DROP DATABASE` der alten Kopie lässt den Wartungsmarker bestehen. Die Website bleibt dann auf HTTP 503, bis ein weiterer erfolgreicher Recovery-Lauf oder ein operativer Eingriff erfolgt. Auch bei bereits entferntem Marker wird die Backup-Verarbeitung durch den nicht abgeschlossenen Auftrag blockiert. Voraussetzung sind ein Prozessabbruch in diesem Zeitfenster und ein anschließender Cleanup-Fehler; es handelt sich nicht um einen normalen Restore-Fehler vor dem Commit.
- Betroffener Code:
  ```python
  elif job['kind'] == 'restore' and journal.get('phase') == 'committed':
      database.adapter().finish(journal['stage'])
      (storage.root() / 'maintenance.json').unlink(missing_ok=True)
      update_job(job, state='completed')
  ```
- Empfehlung: Den bestätigten Datenstand bei Recovery unabhängig von der Entsorgung der alten Datenbank behandeln. Nach erneuter Prüfung des Live-Stands den Auftrag abschließen und Wartung freigeben; einen fehlgeschlagenen Cleanup gesondert protokollieren und später wiederholen. Die alte Datenbankkopie bis zur erfolgreichen Bereinigung erhalten.
- Konfidenz: Mittel. Der Kontrollfluss wurde im Original-Helper isoliert mit gemocktem Storage/Adapter nachvollzogen: eine `finish`-Ausnahme propagiert und Abschluss/Aufräumen werden nicht erreicht. Kein echter Prozessabbruch oder PostgreSQL-Restore wurde durchgeführt.

#### Verifikation
- **Urteil: BESTÄTIGT.**
- **Begründung:** Die Schutzbehandlung des normalen Restore (`backups/services.py:327`) gilt nur innerhalb von `restore_job()`. Nach einem Prozessabbruch führt der Worker stattdessen `recover_interrupted()` aus. Dessen `committed`-Zweig ruft `finish()` vor dem Entfernen des Wartungsmarkers und vor dem Job-Abschluss auf und besitzt keinen `try/except`. Ein Verbindungs-/SQL-Fehler unterbricht den gesamten Aufruf. Die allgemeine Fehlerbehandlung von `process_next()` schützt diesen Fall nicht, weil die Recovery vor Eintritt in diese Funktion stattfindet.
- **Pfad / vorgelagerte Schutzmechanismen:** `config/urls.py:17` → `backups/urls.py:9` mit `admin_view` → explizite Aktiv-/Staff-/Superuser-Prüfung `backups/views.py:19` → CSRF-geschützte Restore-View `backups/views.py:87` → gültiges Passwort und Bestätigung `backups/forms.py:25`, `backups/forms.py:34` / Template `templates/admin/backups/restore.html:12` → `enqueue()` mit exklusiver Control-Sperre und Prüfung auf bestehende aktive Jobs (`backups/services.py:32`, `backups/services.py:35`) → Worker → Restore mit persistiertem Commit-Journal (`backups/services.py:312`, `backups/storage.py:73`). Diese Maßnahmen verhindern unbefugte Restore-Aufträge und Parallelität; sie behandeln keinen späteren Cleanup-Fehler. Die App besitzt hier keine Models/Serializer; Jobs und Journal liegen im privaten JSON-Storage.
- **Beleg für die Lücke und Gegenprüfung:** `backups/services.py:364` / `backups/services.py:365` erreichen bei einer Ausnahme weder `maintenance.json.unlink()` (`backups/services.py:366`) noch `update_job(...completed)` (`backups/services.py:367`). `backups/database.py:214` öffnet die Verwaltungsverbindung und `backups/database.py:216` führt den Drop ohne Fehlerbehandlung aus. Die Existenzprüfung schützt nur die Wiederholung bei bereits gelöschter alter Datenbank, nicht bei Verbindungs-/Drop-Fehlern. Der Daemon ruft Recovery bereits unter `worker.lock` in `backups/management/commands/process_backup_jobs.py:23` auf; sein äußerer Handler (`backups/management/commands/process_backup_jobs.py:30`) übersetzt nur `BackupError` in einen Abbruch und räumt den Marker nicht auf. Auch der alternative CLI-Recovery-Pfad (`backups/management/commands/backup_system.py:26`, `backups/management/commands/backup_system.py:47`) gibt Wartung nicht trotz Cleanup-Fehler frei.
- **Auswirkung / Begrenzung:** `config/settings.py:98` aktiviert die Wartungsmiddleware vor Sessions/Auth; `backups/locking.py:84` prüft allein die Existenz des Markers, ohne TTL. `backups/middleware.py:25` / `backups/middleware.py:86` liefern dann HTTP 503. Capability-geschützte Fortschrittsseiten und Health-Abfragen bleiben ausgenommen (`backups/middleware.py:23`, `backups/middleware.py:26`, `backups/middleware.py:82`); deshalb betrifft die Ausfallbeschreibung den regulären Websitebetrieb. Der Container-Neustart (`docker-compose.yml:107`) versucht Recovery erneut und kann einen vorübergehenden Fehler nach dessen Ende beheben; bei fortbestehendem Cleanup-Fehler bleibt die Blockade bestehen. Ein überlebender aktiver Job blockiert neue Aufträge auch ohne Marker (`backups/services.py:35`).
- **Isolierter Nachweis:** Die unveränderte Funktion wurde aus ihrem AST geladen und für einen `running`-Restore mit `committed`-Journal ausgeführt. Gemocktes `finish()` mit Ausnahme: Marker-Unlink **0**, Job-Update **0**, Work-Cleanup **0**, Ausnahme propagiert. Kontrolllauf ohne Ausnahme: jeweils **1** Aufruf. Kein realer PostgreSQL-Restore/Prozessabbruch wurde durchgeführt.
- **Schweregrad:** **Mittel**, wie gemeldet; benötigt den beschriebenen Abbruch nach Commit und einen anschließenden Cleanup-Fehler.


## Zusätzliche Beobachtungen

Keine weiteren eigenständigen Probleme während der Verifikation dieses Findings festgestellt.


## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| BACKUPS-01 | bestätigt | Recovery prüft nach committed Live-Datenbank, Migrationsstand und Dateireferenzen erneut und gibt erst danach die Wartung frei. Datenbank-Cleanup ist getrennt, Fehler werden protokolliert und mit Stage sowie 5-Minuten-Backoff im Job persistiert. Worker-Neustarts und Daemon wiederholen Cleanup; alte Kopie bleibt bis zum Erfolg erhalten. |

**Prüfungen:** Alle 49 bisherigen/neu isolierten Backup-Tests plus eine zusätzliche native PostgreSQL-Regression erfolgreich (50 insgesamt). Die native Regression spielt auf temporären Datenbankkopien ein echtes Backup ein, simuliert committed-Recovery mit Cleanup-Fehler und prüft spätere erfolgreiche Entsorgung; Produktionsdaten wurden nicht verändert.
