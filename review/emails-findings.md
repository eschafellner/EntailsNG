Verifikationszusammenfassung (9. Oktober 2026): **1 BESTÄTIGT / 1 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Stufe 2: Queue-Worker-/Thread-/Admin-Eingänge, Leases, Recovery, Status-Save-Methoden, SMTP-Timeout, Formatierung, Outbox-Spalte und Sitzplatz-Commit-Callback geprüft. Kein SMTP-Versand und kein produktiver Queue-/PostgreSQL-Schreibversuch.

Zusammenfassung: 2 Findings — Kritisch: 0, Hoch: 0, Mittel: 2, Niedrig: 0, Info: 0.

Geprüft: Models und Queue-Zustandswechsel, Versand-/Rendering-Services, SMTP-Backend, Verschlüsselung, Diagnose/DNS, Admin/Formulare, Context Processor, Post-Migrate-Seeding, Management Commands, Migrationen und Templates. HTML-Platzhalter werden in einem Durchlauf escapet; SMTP-Header durchlaufen Django-Mailvalidierung. Admin-Diagnose und Testversand prüfen das konkrete Konfigurationsrecht. Der SMTP-Konfigurationszugriff ist eine bewusst privilegierte Transportverwaltung, kein öffentlich erreichbarer SSRF-Endpunkt.

### [EMAILS-01] Veralteter Worker kann einen bereits abgeschlossenen Versand zurücksetzen
- Schweregrad: Mittel
- Kategorie: Bug
- Fundstelle: emails/services.py:203, emails/services.py:218, emails/services.py:244, emails/services.py:265; emails/models.py:487, emails/models.py:503, emails/models.py:517
- Beschreibung: Die Queue vergibt zeitlich begrenzte Leases. Der Worker prüft seine Kennung vor dem SMTP-Aufruf, erneuert die Lease aber nicht. `mark_sent` verwendet einen bedingten SQL-Update mit Worker-Kennung; `mark_failed_attempt`, `mark_paused` und `mark_expired` speichern hingegen ohne Besitz-/Statusprüfung. Ein inzwischen abgelöster Worker kann deshalb neuere Zustände überschreiben.
- Auswirkung / Angriffsszenario: Worker A hängt länger als die Lease im SMTP-Aufruf (z. B. bei erhöhtem `smtp_timeout` oder einer kurz vor Lease-Ende gestarteten Nachricht). Worker B stellt den Eintrag wieder her und versendet ihn erfolgreich. Danach kehrt A mit einem Fehler zurück und speichert PENDING/FAILED über den SENT-Zustand. Bei PENDING wird die bereits versendete Nachricht erneut verarbeitet; Auswahl prüft nicht `sent_at IS NULL`. Dies ist ein Race-Szenario aus dem Code, kein mit einer produktiven Queue ausgeführter Lasttest.
- Betroffener Code:
  ```python
  except Exception as exc:
      outgoing.mark_failed_attempt(str(exc))
  # mark_failed_attempt:
  self.status = self.Status.PENDING
  self.save(update_fields=['attempts', 'last_error', 'status', ...])
  ```
- Empfehlung: Sämtliche Worker-Zustandswechsel mit `pk`, PROCESSING, aktueller Worker-Kennung und gegebenenfalls `sent_at__isnull=True` bedingen. Lease direkt vor dem Versand erneuern; Batch-/SMTP-Zeitlimits aufeinander abstimmen. Administrative Retry-Aktionen ebenfalls atomar an den noch gültigen Ausgangszustand binden.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Die Queue wird vom Compose-Daemon, nach Commit gestarteten Threads und Adminaktionen verwendet. Batch-Leases werden einmalig vergeben; vor SMTP wird Besitz geprüft, danach bei Fehler/Pause/Expiry nicht erneut. `mark_sent` bedingt sein Update korrekt auf PROCESSING und Workerkennung, die anderen Methoden speichern über pk-only Model.save. Ein altes Workerobjekt kann damit einen von Worker B bestätigten SENT-Datensatz auf PENDING/FAILED zurücksetzen; sent_at bleibt dabei sogar bestehen. Die Auswahl neuer Versandaufträge filtert nur PENDING und nicht sent_at. Keine exklusive Einzelworker-Sperre schützt diesen Ablauf; der Backup-Zugriffslock ist ein gemeinsamer Leserlock.
- **Belege / Gegenmaßnahmen:** `docker-compose.yml:64`, `emails/management/commands/process_email_queue.py:48`, `emails/admin.py:307`, `emails/services.py:117`, `:143`, `:189`, `:203`, `:218`, `:244`, `:265`, `emails/models.py:445`, `:467`, `:476`, `:487`, `:503`, `backups/locking.py:102`, `:112`. skip_locked und bedingtes mark_sent sichern Claim/Erfolg, aber nicht einen späten Fehlerrücklauf. Der Default-Timeout ist 10 s gegenüber 300 s Lease (`emails/models.py:112`, `config/settings.py:292`); der konfigurierbare SMTP-Timeout hat hier keine MaxValueValidator-Grenze und die Batch-Lease kann kurz vor Sendestart auslaufen. Daher besteht das Original-Raceszenario trotz günstiger Defaults. Reale SMTP-/Scheduler-Laufzeiten wurden nicht simuliert.

### [EMAILS-02] Gültige Platzhalterwerte überschreiten die Betreff-Spaltenlänge
- Schweregrad: Mittel
- Kategorie: Bug
- Fundstelle: emails/services.py:70, emails/services.py:91; emails/models.py:345; emails/defaults.py:102; seating/models.py:364, seating/models.py:373
- Beschreibung: Die Betreffzeile wird nach Platzhalterersetzung ohne Längenprüfung in `OutgoingEmail.subject` (255 Zeichen) geschrieben. Bereits die Standardvorlage `seat_overwritten` kann mit zulässigen Modellwerten länger werden: 200 Zeichen Veranstaltungstitel und 20 Zeichen Platzbezeichnung ergeben 268 Zeichen. Die ORM-Erstellung ruft keine Model-Validierung auf; PostgreSQL lehnt diesen Wert ab.
- Auswirkung / Angriffsszenario: Ein zahlender Gast übernimmt bei einer Veranstaltung mit langem Titel einen vorgemerkten Platz. Nach dem Commit versucht der Callback, die Benachrichtigung einzureihen, und löst einen Datenbankfehler aus. Die Sitzänderung ist bereits gespeichert, der Nutzer erhält dennoch eine Fehlerantwort und die Benachrichtigung fehlt. Auch individuell konfigurierte Betreffvorlagen können nach Ersetzung dasselbe Problem auslösen. Die Länge der Standardvorlage wurde isoliert nachgerechnet; keine Datenbank wurde beschrieben.
- Betroffener Code:
  ```python
  subject = safe_format(template.subject, context_data, escape_html=False)
  outgoing = OutgoingEmail.objects.create(..., subject=subject, ...)
  # subject = models.CharField(max_length=255)
  ```
- Empfehlung: Den fertig gerenderten Betreff vor dem Queue-Insert kontrolliert auf die vereinbarte Länge begrenzen oder eine ausreichend große Textspalte verwenden. Fehler in Benachrichtigungen nach Commit getrennt behandeln, damit eine erfolgreiche Buchung nicht als gescheitert erscheint.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: TEILWEISE ABGESICHERT. Neuer Schweregrad: Niedrig (zuvor Mittel).**
- **Begründung:** Das konkrete Standardszenario ist entkräftet: Event.title besitzt tatsächlich max_length=100, nicht 200. Mit maximal zulässigem Titel und 20 Zeichen Sitzlabel ergibt die Originalvorlage 168 Zeichen und passt in die Spalte. Admin-ModelForm-Validierung und die PostgreSQL-varchar(100)-Spalte verhindern den behaupteten zulässigen 200-Zeichen-Titel. Der allgemeine Expansionsfehler bleibt jedoch für konfigurierte Vorlagen bestehen: Schon die zulässige 39-Zeichen-Vorlage `{event_title}{event_title}{event_title}` erzeugt mit einem gültigen 100-Zeichen-Titel 300 Zeichen. Beide Längen wurden isoliert nachgerechnet. Queue-Insert ruft weder full_clean noch eine Längenbegrenzung auf. Bei einer entsprechend angepassten seat_overwritten-Vorlage kann der on_commit-Callback weiterhin nach bereits persistierter Reservierung scheitern. Das zusätzliche Erfordernis einer solchen Vorlagenkonfiguration reduziert Reichweite und Schwere gegenüber dem Original.
- **Belege / Gegenmaßnahmen:** Konkreter Schutz der Original-Standardvorlage: `events/models.py:82`, `events/migrations/0001_initial.py:18`, `seating/models.py:179`, `emails/defaults.py:102`. Restlücke: `emails/models.py:272`, `:345`, `emails/admin.py:283`, `emails/services.py:70`, `:91`, `:293`. Öffentlich ausgelöster Callback: `seating/urls.py:24`, `seating/views.py:216`, `seating/clan_services.py:38`, `seating/models.py:355`, `:364`, `:373`; PostgreSQL und Queue-Default: `config/settings.py:158`, `:291`. Der View-Handler fängt Fehler während der Reservierung (`seating/views.py:301`), der äußere seating_write-Commit führt den Callback erst danach aus. Der Kontaktservice prüft den fertigen Betreff ausdrücklich (`contact/services.py:127`), schützt aber diesen anderen Mailpfad nicht. Bei explizit synchronem Versand ohne Outbox entfällt der Spaltenfehler. Wegen der belegten Restlücke ist das gesamte Finding kein FALSE POSITIVE; nur sein Standardbeispiel ist falsch.


## Zusätzliche Beobachtungen

- **Zusätzliche Race-Lücke in Stale-Recovery (Bug, Mittel):** Die Kandidatenliste wird nach abgelaufener Lease gefiltert (`emails/services.py:143`). Das spätere `mark_stale_recovered`-UPDATE prüft dagegen weder dieselbe Workerkennung noch eine weiterhin abgelaufene Lease (`emails/models.py:517`). Wenn ein zweiter Recovery-Lauf den Datensatz inzwischen zurückgesetzt und Worker B ihn neu geclaimt hat, kann der erste Lauf auch Bs frische PROCESSING-Lease löschen. Der sent_at-Check schützt bereits gesendete Einträge, aber keine noch sendenden neuen Besitzer. Kandidatenkriterium/Lease bzw. Workerkennung müssen im atomaren UPDATE erneut verglichen werden. Statisch nachverfolgter zusätzlicher Pfad, kein Lasttest.


## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| EMAILS-01 | bestätigt | Alle Worker-Zustandswechsel prüfen PROCESSING, Workerkennung und ungesendeten Zustand per bedingtem UPDATE. Lease wird unmittelbar vor SMTP verlängert und am SMTP-Timeout ausgerichtet. Abgelaufene Besitzer senden nicht; Auswahl überspringt sent_at-Einträge. Administrative Retry-Aktionen prüfen ihren aktuellen Ausgangszustand atomar. |
| EMAILS-02 | teilweise abgesichert | Standardbeispiel mit 200-Zeichen-Eventtitel widerlegt (Modellgrenze 100); konfigurierte Platzhalterexpansion bleibt bestätigt. Gerenderter Betreff wird am Queue-Insert kontrolliert auf die bestehende Spaltenlänge gekürzt und Kürzung geloggt. |

**Prüfungen:** 125 E-Mail-/Kontakt-/Cleanup-/PostgreSQL-Concurrencytests bestanden. 6 neue Regressionstests prüfen alte Workerantworten, Recovery-Snapshots, Leaseverlängerung, Admin-Retry und 300-Zeichen-Betreff vor PostgreSQL-Insert.

Zusatzbeobachtung umgesetzt: Recovery-UPDATE bindet Workerkennung, Lease, updated_at, attempts und weiterhin abgelaufenes Kandidatenkriterium erneut. SMTP bleibt extern und kann nicht atomar mit dem Datenbankcommit gekoppelt werden; kein echter SMTP-Versand ausgeführt.
