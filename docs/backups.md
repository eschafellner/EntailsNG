# Vollständige Backups im Backend

> Seit 5. Oktober 2026 verwendet das Projekt ausschließlich PostgreSQL, auch lokal und für Tests. Testbefehle benötigen eine konfigurierte PostgreSQL-Verbindung; erwähnte SQLite-Ergebnisse sind historische Prüfstände vor der Umstellung. Die vollständige PostgreSQL-Suite einschließlich Parallelität und Backups läuft gemeinsam in CI.

Die Administration bietet unter `/admin/backups/` manuelle Sicherungen,
Downloads, Uploads mit Vorprüfung und vollständige Wiederherstellung. Ein Link
steht auf der Admin-Startseite. Nur aktive Superuser mit Mitarbeiterstatus haben
Zugriff. Es gibt keine automatische Zeitplanung und keine externe Cloud-Anbindung.

## Umfang und Schlüssel

Eine `.entailsbackup`-Datei enthält die native Datenbanksicherung, öffentliche
Medien und private Anhänge der Wissensbasis. Auch Benutzer, Ticketcodes,
Zahlungen, Turnierergebnisse, Konfiguration und Übersetzungen sind enthalten.
Das Archiv wird mit AES-256-GCM authentifiziert verschlüsselt und blockweise
verarbeitet; es wird nicht vollständig in den Arbeitsspeicher geladen.

Nicht enthalten sind `.env`, Quellcode, TLS-Zertifikate, Datenbankrollen,
Redis-Daten und generierte Static-Dateien. Eine Anwendungssicherung ersetzt
daher keine Sicherung der Deployment-Konfiguration.

In `.env` einen eigenen Schlüssel setzen:

```bash
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Die Ausgabe als `BACKUP_ENCRYPTION_KEY` eintragen. Den Schlüssel zusätzlich
außerhalb des Servers aufbewahren. Es gibt keinen automatischen Fallback auf
`SECRET_KEY`. Ohne Schlüssel bleiben die Backup-Funktionen deaktiviert; eine
entsprechende Meldung erscheint im Backend. Der Schlüssel wird niemals in das
Archiv geschrieben. Für die Wiederherstellung auf einem neuen Server müssen
derselbe Backup-Schlüssel und der bisherige `FIELD_ENCRYPTION_KEY` vorhanden
sein. Wenn SMTP-Zugangsdaten mit dem alten `SECRET_KEY` statt einem separaten
Feldschlüssel verschlüsselt wurden, muss auch dieser Schlüssel verfügbar sein.

## Docker starten

```bash
docker compose --profile backups up -d --build
docker compose exec web python manage.py seed_translations
docker compose logs -f backup_worker
```

Der optionale Worker verwendet dasselbe Anwendungsimage. Er besitzt keinen
Docker-Socket, führt keine Migrationen oder Seeds aus und hat standardmäßig
eine CPU sowie 512 MB RAM als Containergrenzen. Native PostgreSQL-16-Programme
sind im Image enthalten; Datenbankserver und Client müssen dieselbe Hauptversion
verwenden. Die konfigurierte Datenbankrolle braucht für die Prüfdatenbank und
den kontrollierten Datenbankwechsel `CREATEDB` sowie Eigentümerrechte an der
Anwendungsdatenbank. Die bisherige Compose-Rolle aus `POSTGRES_USER` erfüllt
dies; auf externen Servern die Rechte vorab prüfen.

Das Volume `backup_data` wird von Web-, Mail- und Backup-Worker geteilt. Es wird
von Nginx nicht ausgeliefert. Öffentliche und private Medien bleiben in ihren
jeweiligen Volumes. Kein dauerhafter Backup-Zustand liegt in der Datenbank,
die wiederhergestellt wird.

Nginx erlaubt auf `/admin/backups/` Uploads bis 1024 MB. Andere Upload-Routen
behalten ihre bisherigen Grenzen. Vorgeschaltete Proxies können niedrigere
Grenzen haben; große Sicherungen lassen sich dann über die CLI vorbereiten.
Der zusätzliche Worker startet nur mit dem Compose-Profil `backups`.

## Lokaler Betrieb mit PostgreSQL

Den Worker in einem separaten Terminal derselben Umgebung starten:

```bash
python manage.py process_backup_jobs --daemon
```

Lokal müssen `pg_dump` und `pg_restore` in derselben Hauptversion wie der
PostgreSQL-Server installiert sein. Optional `BACKUP_PG_BIN_DIR` auf das
`bin`-Verzeichnis der passenden PostgreSQL-Installation setzen, insbesondere
unter Windows. Die Datenbankrolle benötigt `CREATEDB` und Eigentümerrechte
an der Anwendungsdatenbank für Vorprüfung und Wiederherstellung.
Ein noch nicht gestarteter Worker wird im Backend angezeigt;
Webanfragen führen keine langen Sicherungsprozesse selbst aus.

Für konsistente Sicherungen müssen alle Anwendungsinstanzen denselben
Backup-Speicher verwenden. Die Dateisperren sind für lokale Dateisysteme und
Docker-Volumes vorgesehen, nicht für verteilte Hosts oder ungeprüfte NFS-Speicher.
Andere manuelle Schreibprozesse, Datenbankzugriffe und Deployment-Befehle müssen
während einer Sicherung oder Wiederherstellung gestoppt sein. Die integrierte
Sperre koordiniert Webanfragen und die vorhandene E-Mail-Verarbeitung.

## Bedienung und Wiederherstellung

1. **Backup erstellen:** Beschreibung und Wartungsfenster bestätigen. Laufende
   Webanfragen und Mail-Vorgänge dürfen abschließen. Danach werden Datenbank und
   beide Medienbereiche aufgenommen. Während der anschließenden Verpackung ist
   die Anwendung wieder verfügbar.
2. **Herunterladen:** Fertige Sicherungen werden nach Berechtigungsprüfung als
   einzelne verschlüsselte Datei gestreamt. Mindestens eine Kopie außerhalb des
   Servers aufbewahren.
3. **Vorbereiten:** Vorhandene Sicherung wählen oder Datei hochladen. Der Worker
   prüft Authentizität, Grenzen, Prüfsummen, Dateireferenzen, Zugangsdaten und einen
   aktiven Superuser. PostgreSQL wird in eine eigene Prüfdatenbank eingespielt.
4. **Bestätigen:** Die Vorprüfung zeigt Umfang und Sicherungsstand. Das aktuelle
   Administratorpasswort und eine ausdrückliche Bestätigung sind erforderlich.
5. **Übernehmen:** Der Worker erstellt zuerst eine vollständige Sicherung des
   aktuellen Zustands. Anschließend werden Datenbank und Dateien im Wartungsmodus
   ersetzt und geprüft. Bei Fehlern wird der vorherige Zustand zurückgesetzt.

Ein vollständiges Restore ersetzt den aktuellen Datenbestand einschließlich
späterer Änderungen. Auch inzwischen gelöschte Benutzer können durch einen alten
Sicherungsstand wieder vorhanden sein. Die Aufbewahrung entsprechend begrenzen.

Die erste Version akzeptiert nur denselben Datenbanktyp, dieselbe Datenbank-
Hauptversion, denselben tatsächlich angewendeten Migrationsstand und dieselbe
Prüfsumme des produktiven Python-/Template-/CSS-/JavaScript-Codes und der
Requirements. Damit werden auch lokale, nicht eingecheckte Codeänderungen
berücksichtigt. Für alte Sicherungen zunächst den passenden Softwarestand
bereitstellen und erst nach erfolgreicher Wiederherstellung aktualisieren.

Nach erfolgreicher Übernahme werden Sessions und Verifizierungscodes gelöscht,
Caches invalidiert und bestehende Datenbankverbindungen erneuert. Die erneute
Anmeldung verwendet ein Administratorkonto aus der Sicherung.

Der Mailversand bleibt durch eine zusätzliche Dateisperre und deaktivierte
E-Mail-Einstellungen pausiert. Vor der Freigabe die Outbox prüfen: Ein altes
Backup kann Nachrichten enthalten, die inzwischen schon versendet wurden.
Anschließend die zusätzliche Sperre auf der Backup-Seite aufheben und den
Versand in den allgemeinen E-Mail-Einstellungen aktivieren.

Die Sicherung vor einer Wiederherstellung wird nicht automatisch gelöscht.
Nach abgeschlossener Prüfung kann sie ausdrücklich über das Backend gelöscht
werden. Während eines laufenden Auftrags ist das Löschen gesperrt.

## Unterbrechung und CLI

Das Wiederherstellungsjournal und der Wartungsmarker liegen außerhalb der
Anwendungsdatenbank. Bei einem Prozessabbruch bleibt ein begonnener Datenwechsel
gesperrt. Der nächste Worker-Start setzt einen unvollständigen Wechsel auf den
vorherigen Zustand zurück; bereits bestätigte Übernahmen werden abgeschlossen.
Ein fehlgeschlagener Rollback hält die Wartungssperre und alle Arbeitskopien.
Die Statusseite funktioniert während des Datenbankwechsels ohne Datenbankzugriff.

```bash
# Ohne laufenden Backup-Worker einen Auftrag direkt ausführen:
python manage.py backup_system create --description "Vor dem Update"
python manage.py backup_system list
python manage.py backup_system prepare --id BACKUP_ID
python manage.py backup_system prepare --file /sicherer/pfad/sicherung.entailsbackup
python manage.py backup_system restore --id BACKUP_ID --confirm-replace
python manage.py backup_system recover
```

`prepare --file` gibt die neue Backup-ID aus. `restore` erfordert immer eine
erfolgreiche Vorprüfung. CLI und dauerhafter Worker sind gegenseitig gesperrt;
für direkte CLI-Aufträge den Worker zuerst stoppen. Unter Docker die Befehle
mit `docker compose exec web` ausführen.

Bei Fehlern Speicherplatz, Dateirechte, PostgreSQL-Verbindungen und Redis prüfen,
dann `backup_system recover` oder den Worker erneut starten. Wartungsmarker,
Journal und Arbeitskopien niemals manuell löschen, solange die Rücksetzung
nicht abgeschlossen ist. Während einer offenen Rücksetzung überspringt der
Container-Entrypoint Migrationen und Seeds.

Für einen neuen Server zuerst denselben Softwarestand, die separat gesicherte
Umgebungskonfiguration und eine initialisierte Anwendungsdatenbank mit
Administrator bereitstellen. Danach die heruntergeladene Sicherung vorbereiten
und einspielen. Die CLI hilft bei einem nicht erreichbaren Backend; sie ersetzt
keine funktionierende Datenbankverbindung und keinen verfügbaren Speicher.

## Ressourcen und Prüfung

`BACKUP_KEEP_COUNT=7` begrenzt reguläre lokale Sicherungen. Hochgeladene Sicherungen
und die Sicherung vor einer Wiederherstellung werden ausdrücklich gelöscht.
`BACKUP_MAX_UPLOAD_BYTES` (1 GiB), `BACKUP_MAX_UNPACKED_BYTES` (10 GiB),
`BACKUP_MAX_FILES` (50.000), `BACKUP_MIN_FREE_BYTES` (256 MiB),
`BACKUP_DRAIN_TIMEOUT` (60 s) und `BACKUP_OPERATION_TIMEOUT` (1.800 s für native
PostgreSQL-Programme) sind konfigurierbar. Bei Änderungen der Upload-Grenze auch
Nginx und vorgeschaltete Proxies anpassen.

Speicherprüfungen berücksichtigen temporäre Kopien; trotzdem ausreichend Reserve
für Sicherheitskopie, Archiv, entpackte Medien und Prüfdatenbank einplanen. Es
läuft höchstens ein Auftrag gleichzeitig. Komprimierung ist moderat, Dateiverarbeitung
erfolgt in 1-MiB-Blöcken. Auch Datenbankserver und Festplatte tragen während eines
Auftrags Last; Containergrenzen begrenzen ausschließlich den Backup-Worker.

```bash
python manage.py test backups emails configuration --noinput
python manage.py test backups --noinput
```

Die Tests verwenden getrennte temporäre Verzeichnisse beziehungsweise eigens
erstellte PostgreSQL-Testdatenbanken. Sie prüfen Berechtigungen, CSRF,
Authentifizierung der Archive, Pfade, Größenlimits, Parallelität, beide Medien-
bereiche, native Wiederherstellung, Mailpause, Session-/Code-Invalidierung und
Rücksetzung einschließlich Prozessunterbrechung. Die vollständige CI-Suite läuft
mit PostgreSQL 16 und echten `pg_dump`-/`pg_restore`-Programmen.

Prüfstand vom 3. Oktober 2026: Die vollständige SQLite-Projektsuite umfasst
822 Tests, davon 799 erfolgreich und 23 übersprungen (PostgreSQL-spezifische
Fälle beziehungsweise POSIX-Dateirechte unter Windows). Alle 47 Backup-Tests
wurden zusätzlich mit einer separaten PostgreSQL-16.15-Instanz und nativen
Programmen ausgeführt: 45 erfolgreich, ein POSIX-Rechtetest und der ausschließlich
für SQLite bestimmte Test offener Dateiverbindungen übersprungen.
Die bestehenden 12 JavaScript-Tests und die Syntaxprüfung von `backups.js`
waren ebenfalls erfolgreich. Der Docker-Imagebau und der CI-Lauf wurden lokal
nicht ausgeführt.

Die Bedienprüfung in einer getrennten lokalen SQLite-Umgebung hat Erstellung,
Download, erneuten Upload, Vorprüfung, vollständige Wiederherstellung, erneute
Anmeldung, Mailpause und bestätigtes Löschen geprüft. Ein dabei gefundener
Windows-Konflikt mit offenen SQLite-Dateiverbindungen ist korrigiert und war durch
einen zusätzlichen Test einschließlich Rücksetzung abgedeckt. Dieser ausschließlich
für SQLite bestimmte Test wurde bei der PostgreSQL-Umstellung entfernt.
Eine [Bildschirmaufnahme nach der Wiederherstellung](screenshots/backup-admin.jpg)
zeigt die Backup-Seite und die aktive Mailpause.
