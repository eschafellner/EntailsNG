# Umsetzung der Review-Befunde – Fortschritt

Grundlage: [review_findings.md](review_findings.md) (Review auf `85ba422`), Umsetzung ab `b6115c5` auf Branch `claude/entailsng-review-fixes-jccyu0`.
Status: `offen` · `in Arbeit` · `erledigt` · `Entscheidung nötig` · `nicht reproduzierbar` · `zurückgestellt`

## Prüfumgebung

- Wegwerf-venv mit exakt `requirements.txt` (Python 3.13; Python 3.12 steht im Container nicht zur Verfügung), Django 6.0.9.
- Wegwerf-PostgreSQL 16 (eigener Cluster, Port 55432, DB `entails_review`), kein Zugriff auf bestehende Daten, kein Redis (Tests nutzen LocMem).
- Ausgangsstand auf `4c1642a`/`b6115c5`: `check` und `check --deploy --fail-level WARNING` ohne Befund, `makemigrations --check` ohne Änderung, **1426/1426 Django-Tests** (statt 1335 im Review, neuere Commits), **34/34 Node-Tests** (statt 31).

## Befunde

| ID | Schweregrad | Phase | Status | Commit | Kurznotiz |
|---|---|---|---|---|---|
| F-001 | niedrig | 3d | offen | – |  |
| F-002 | niedrig | 3d | offen | – |  |
| F-003 | niedrig | 3a | offen | – |  |
| F-004 | mittel | 2 | erledigt | 050bb30 | Include `tinymce.urls` entfernt (alle drei Routen öffentlich; `compressor` lieferte anonym 200, die anderen 500). Widget nutzt die Routen ohne `TINYMCE_COMPRESSOR`/Filebrowser nicht; bestehende `news`-Tests prüfen das Widget-Rendering im Admin (Browser nicht geprüft). Test `configuration/test_error_log.py::PublicTinyMCERoutesTests` (vorher rot). |
| F-005 | niedrig | 3b | offen | – |  |
| F-006 | niedrig | 3e | offen | – |  |
| F-007 | niedrig | 3e | offen | – |  |
| F-008 | niedrig | 3d | offen | – | Entscheidung nötig (pip-compile/uv) |
| F-009 | hoch | 1 | erledigt | a184018 | Eigener `string.Formatter`: nur `{name}`-Platzhalter, kwargs vorher `str()`, Formatangaben (`{x:>99999}`) ebenfalls abgelehnt (Abweichung: verhindert Speicher-DoS über Breitenangaben). Template übergibt `user_member_team\|stringformat:"s"` statt `.name` (Abweichung: `.name` hätte die bisherige Anzeige `[Tag] Name` verändert, bestehender Test `test_checked_in_user_as_member_sees_captain_must_register_notice`). Tests: `configuration/test_translation_format.py`, `tournaments/test_review_fixes.py::TournamentDetailTranslationPlaceholderTests` (vorher 6/6 rot). Handover-Konvention ergänzt. |
| F-010 | mittel | 2 | erledigt | 050bb30 | Fingerprint = Ausnahmetyp + URL-Muster (`resolver_match.route`) + auslösende Codezeile; offene Einträge zählen `occurrences`/`last_seen` hoch. Abweichung: URL-Muster statt Pfad, sonst ließe sich die Deduplizierung über wechselnde IDs umgehen; keine zusätzliche Cache-Obergrenze, weil anonyme Fluten nach der Deduplizierung nur Zähler erhöhen. `purge_error_logs [--days] [--dry-run]`, Frist `SYSTEM_ERROR_LOG_RETENTION_DAYS` (Default 30, ab letztem Auftreten, auch offene Einträge); automatisch im stündlichen `purge_guest_photos`-Worker (Abweichung: kein neuer Compose-Dienst nötig). Migration `configuration.0028` (Bestand `last_seen = timestamp`, rückwärts noop; vor/zurück geprüft). Tests `configuration/test_error_log.py` (vorher 7/8 rot). |
| F-011 | mittel | 2 | erledigt | 67e5f15 | Validator serialisiert den geprüften Baum mit eigenem Serializer (Abweichung: `ET.tostring` erzeugt `ns0:`-Präfixe, die Browser nicht als SVG darstellen); Kommentare/PIs/XML-Deklaration entfallen, nur SVG-, xlink- und xml-Namespace bleiben. Zusätzlich `style` und `href`/`src` ohne `#` abgelehnt; `save()` prüft eigene Icons. Bestehender Positivtest (exakter Vergleich) unverändert grün. Bestandsicons ändern sich erst beim nächsten Speichern; Prüfkommando in `docs/updating.md`. Tests `configuration/test_svg_icon.py` (vorher 4/5 rot). Nicht im Browser geprüft. |
| F-012 | niedrig | 3b | offen | – |  |
| F-013 | niedrig | 3e | offen | – |  |
| F-014 | niedrig | 3a | offen | – |  |
| F-015 | mittel | 2 | Entscheidung nötig | 3b2479c (Formular) | Formular-Fix erledigt: `clean_username` ruft `super()` auf (Djangos case-insensitive Prüfung). Tests `users/test_review_fixes.py::UsernameCaseCollisionTests` (vorher 3 Fehlschläge). Offen: Unique-Constraint auf `Lower('username')`; Prüfabfrage siehe Protokoll 2026-10-29 (Phase 2). Admin-Änderungsformular prüft Schreibweise weiterhin nicht (nur über Constraint abgedeckt). |
| F-016 | niedrig | 3c | offen | – |  |
| F-017 | niedrig | 3c | offen | – |  |
| F-018 | niedrig | 3e | offen | – |  |
| F-019 | niedrig | 3c | offen | – |  |
| F-020 | hoch | 1 | erledigt | 1449cdb, (Folgecommit) | Mechanismus umgesetzt: `SENSITIVE_TEMPLATE_KEYS = {'password_reset'}`, Inhalt im Admin ausgeblendet (nur Betreff), nach Versand/Ablauf/endgültigem Fehlschlag/Stale-Fehlschlag geleert, geleerte Einträge nicht erneut einreihbar, Datenmigration `emails.0010` (rückwärts `noop`) leert bestehende abgeschlossene Reset-Mails. Tests `emails/test_sensitive_outbox.py` (vorher 4/6 rot). `change_generalemailsettings` in `docs/security-backlog.md` als superuser-äquivalent vermerkt. Entscheidung 2026-10-29: Option A (nur `password_reset` sensibel); `PASSWORD_RESET_TIMEOUT` = 3600 s, per Umgebungsvariable einstellbar, Reset-Mails mit gleichem `expires_at` eingereiht (Tests `PasswordResetLifetimeTests`, vorher 2/2 rot). |
| F-021 | niedrig | 3e | offen | – |  |
| F-022 | niedrig | 3b | offen | – |  |
| F-023 | niedrig | 3c | offen | – |  |
| F-024 | mittel | 2 | Entscheidung nötig | – | Trifft weiter zu (`EventRegistration.user/.event` CASCADE, `EventAdmin` ohne Löschsperre, `CustomUserAdmin` sperrt nur gesperrte Konten). Optionen siehe Phasenbericht 2. |
| F-025 | niedrig | 3e | offen | – | Entscheidung nötig (Datenschutz) |
| F-026 | niedrig | 3a | offen | – |  |
| F-027 | niedrig | 3e | offen | – |  |
| F-028 | niedrig | 3b | offen | – |  |
| F-029 | niedrig | 3e | offen | – | nur messen und berichten |
| F-030 | niedrig | 3a | offen | – |  |
| F-031 | mittel | 2 | nicht reproduzierbar | – | `seed_tournaments` wurde mit `5aa34e3` (Audit-Bereinigung) entfernt; `manage.py seed_tournaments` → unbekanntes Kommando, `password123` nur noch in Tests. Lokal liegt nur eine verwaiste, ignorierte `.pyc` in `tournaments/management/commands/__pycache__/` (nicht ladbar, nicht im Image). |
| F-032 | niedrig | 3d | offen | – |  |
| F-033 | niedrig | 3c | offen | – |  |
| F-034 | mittel | 2 | erledigt | 4ab0ccd | Picker per DOM-API (`textContent`, `title`, `addEventListener`, `replaceChildren`), API-Fehler als Text. Serverseitig Validatoren `validate_seat_label` (Buchstaben, Ziffern, Leerzeichen, `. - / #`) und `validate_text_label` (zusätzlich `, : ! ? & + ( )`) am Modell (Admin) und in `save_grid` (Editor-API, Meldung mit Position). Migration `seating.0011` (SQL no-op, vor/zurück geprüft). Neuer Standardtext `seating_label_invalid_chars`. Bestandsprüfung (schreibfrei) in `docs/updating.md`, an Probedaten geprüft. Tests: `scripts/tests/admin-seat-picker.test.cjs` (vorher 0/3), `seating/test_review_fixes.py` (vorher 4/5 rot). Nicht im Browser geprüft. |
| F-035 | niedrig | 3c | offen | – |  |
| F-036 | mittel | 2 | Entscheidung nötig | – | Trifft weiter zu (Redis ohne Passwort, `127.0.0.1:6379` veröffentlicht). Optionen siehe Phasenbericht 2. |
| F-037 | mittel | 2 | Entscheidung nötig | – | Online bestätigt (29.10.2026): `nginx:1.27-alpine` = 1.27.5 vom 16.04.2025, keine Updates mehr; aktueller Stable 1.30.6, Mainline 1.31.8. Vorschlag mit Digests siehe Phasenbericht 2. |
| F-038 | niedrig | 3d | offen | – | Hinweis: `initial_data.json` samt Test bereits mit `5aa34e3` entfernt; Hashes bleiben im Git-Verlauf. Übrige Punkte (Build-Pakete, `.dockerignore`) in Phase 3 prüfen. |
| F-039 | niedrig | 3b | offen | – |  |
| F-040 | niedrig | 3a | offen | – |  |

## Protokoll

- 2026-10-29: Fortschrittsdatei angelegt, Basisläufe grün (siehe oben).
- 2026-10-29: F-009 umgesetzt. Erster Volllauf rot: 1 Turniertest (Anzeige `.name` → behoben über `stringformat`) und 15 Backup-Tests (`backup_err_compatible`, weil die F-020-Migration während des laufenden Tests angelegt wurde; Artefakt, kein Codefehler). Beobachtet: `TournamentQueryPerformanceTests.test_team_list_constant_queries_regardless_of_team_count` schlug in einem Teillauf reihenfolgeabhängig fehl, einzeln und im Volllauf grün.
- 2026-10-29: F-009 allein (Worktree `a184018`) und F-009+F-020 vollständig geprüft: check, deploy-check, makemigrations, Node 34/34 grün; Django 1433 bzw. 1441 Tests, jeweils **1 Fehlschlag** in `tournaments.tests.TournamentQueryPerformanceTests.test_team_list_constant_queries_regardless_of_team_count` (12 statt ≤ 11 Abfragen).
- 2026-10-29: Dieser Fehlschlag ist **unabhängig von den Änderungen**: Im Modullauf `tournaments.tests` schlug er auf dem unveränderten Ausgangsstand `b6115c5` fehl und war mit den Änderungen grün. Die Zusatzabfrage ist `SiteCustomization.load()`; der zuvor gewärmte Cacheeintrag fehlt zwischen beiden Messpunkten. Vermutlich LocMem-Culling (Django-Standard `MAX_ENTRIES=300`) abhängig von vorherigen Tests. Nicht behoben (außerhalb der Befunde); Vorschlag als Zusatzpunkt im Phasenbericht.
- 2026-10-29: Hinweis Arbeitsweise: Neue Migrationen nicht anlegen, während eine Suite läuft (Backup-Tests prüfen den Migrationsstand auf der Festplatte).
- 2026-10-29: Entscheidung F-020 umgesetzt (1 Stunde, Option A). Neue Umgebungsvariable `PASSWORD_RESET_TIMEOUT` in `.env.example` und `docs/configuration.md`. Volllauf: check/deploy/makemigrations grün, Node 34/34, Django 1443 Tests mit 1 Fehlschlag (bekannter instabiler Performance-Test, siehe oben). Phase 1 auf `main` gepusht.
- 2026-10-29 (Phase 2): Neue Prüfumgebung auf dem Entwicklungsrechner (Fedora): eigener PG-Cluster **18.6** (nur diese Version lokal installiert; Compose/CI nutzen 16) unter `~/.local/share/entails-review/pgdata`, Port 55432; frische venv mit exakt `requirements.txt` (Python 3.14.8, Django 6.0.9); Node 24.18. Vorhandene Entwicklungs-DB (5432) und Redis (6379) nicht angefasst; die lokale `.env` wird für alle Läufe durch eigene Prozessvariablen überschrieben (u. a. `REDIS_URL=` leer → LocMem). Arbeitsbranch `claude/review-fixes-phase2` ab `4085d17`. Volläufe je Commit in eigenen `git worktree`s mit eigener DB.
- 2026-10-29: Basislauf `main` (`4085d17`): 1443 Tests, 1 Fehlschlag `backups.tests.NativeRoundTripTests.test_guest_photos_are_not_backed_up_and_removed_by_restore` (`backup_err_operation`). Ursache umgebungsbedingt: PostgreSQL 18 erlaubt das Beenden von Autovacuum-Prozessen nur Rollen mit `pg_signal_autovacuum_worker`; beim Restore lief zufällig einer auf der Zieldatenbank (`pg_terminate_backend` → `InsufficientPrivilege`). Der Wegwerf-Rolle wurde diese Rolle gewährt. Hinweis für Betrieb: Bei einem späteren Wechsel auf PG ≥ 17/18 braucht die Restore-Rolle dieses Recht (oder Restore muss den Fehler tolerieren) – kein Befund dieser Phase.
- 2026-10-29: F-034 umgesetzt (`4ab0ccd`). Volllauf auf dem Commit: check, deploy-check, makemigrations, Node 37/37, **Django 1448/1448 OK**.
- 2026-10-29: F-015 Formularteil (`3b2479c`), F-004+F-010 (`050bb30`), F-011 (`67e5f15`) umgesetzt. Gezielte Läufe grün (users 186, configuration/news/info/sponsors/knowledge + Gastfoto/Kontolöschung 287, configuration/info 146). Ein Fehlschlag `test_navigation_visibility_for_guests_users_and_staff_with_shared_cache` trat nur mit `--keepdb` nach vorherigen TransactionTestCase-Läufen auf (migrationsbefüllte Navigation geleert) und war mit frischer Test-DB grün – Artefakt, kein Codefehler.
- 2026-10-29: F-031 nicht reproduzierbar (siehe Tabelle). F-037 online geprüft (nginx.org, Docker-Hub-Registry, nur lesend).
- 2026-10-29: Prüfabfrage F-015 (schreibfrei, auf Produktion auszuführen): `docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT lower(username) AS name_klein, count(*) AS anzahl, array_agg(id ORDER BY id) AS ids, array_agg(username ORDER BY id) AS namen FROM users_user GROUP BY lower(username) HAVING count(*) > 1;"'` (0 Zeilen = Constraint kann ohne Bereinigung angelegt werden). Gegen die Wegwerf-DB geprüft (0 Zeilen).
- 2026-10-29: Volläufe `050bb30` (F-015 Formular + F-004/F-010): check, deploy-check, makemigrations, Node 37/37, **Django 1458/1458 OK**. `67e5f15` (zusätzlich F-011): dieselben Prüfungen, **Django 1463/1463 OK**. Der bekannte instabile Performance-Test trat in keinem Phase-2-Lauf auf. Phase 2 abgeschlossen bis auf Entscheidungen (F-015 Constraint, F-024, F-036, F-037). Nicht geprüft: Browserdarstellung (Picker, TinyMCE-Widget, SVG-Icons), Docker/Compose.
