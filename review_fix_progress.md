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
| F-004 | mittel | 2 | offen | – |  |
| F-005 | niedrig | 3b | offen | – |  |
| F-006 | niedrig | 3e | offen | – |  |
| F-007 | niedrig | 3e | offen | – |  |
| F-008 | niedrig | 3d | offen | – | Entscheidung nötig (pip-compile/uv) |
| F-009 | hoch | 1 | erledigt | a184018 | Eigener `string.Formatter`: nur `{name}`-Platzhalter, kwargs vorher `str()`, Formatangaben (`{x:>99999}`) ebenfalls abgelehnt (Abweichung: verhindert Speicher-DoS über Breitenangaben). Template übergibt `user_member_team\|stringformat:"s"` statt `.name` (Abweichung: `.name` hätte die bisherige Anzeige `[Tag] Name` verändert, bestehender Test `test_checked_in_user_as_member_sees_captain_must_register_notice`). Tests: `configuration/test_translation_format.py`, `tournaments/test_review_fixes.py::TournamentDetailTranslationPlaceholderTests` (vorher 6/6 rot). Handover-Konvention ergänzt. |
| F-010 | mittel | 2 | offen | – |  |
| F-011 | mittel | 2 | offen | – |  |
| F-012 | niedrig | 3b | offen | – |  |
| F-013 | niedrig | 3e | offen | – |  |
| F-014 | niedrig | 3a | offen | – |  |
| F-015 | mittel | 2 | offen | – | Constraint-Teil: Entscheidung nötig (Prüfabfrage vorab) |
| F-016 | niedrig | 3c | offen | – |  |
| F-017 | niedrig | 3c | offen | – |  |
| F-018 | niedrig | 3e | offen | – |  |
| F-019 | niedrig | 3c | offen | – |  |
| F-020 | hoch | 1 | Entscheidung nötig | (dieser) | Mechanismus umgesetzt: `SENSITIVE_TEMPLATE_KEYS = {'password_reset'}`, Inhalt im Admin ausgeblendet (nur Betreff), nach Versand/Ablauf/endgültigem Fehlschlag/Stale-Fehlschlag geleert, geleerte Einträge nicht erneut einreihbar, Datenmigration `emails.0010` (rückwärts `noop`) leert bestehende abgeschlossene Reset-Mails. Tests `emails/test_sensitive_outbox.py` (vorher 4/6 rot). `change_generalemailsettings` in `docs/security-backlog.md` als superuser-äquivalent vermerkt. **Offen:** `PASSWORD_RESET_TIMEOUT` (+ `expires_at` für Reset-Mails) und ob die Verifizierungsvorlagen ebenfalls sensibel sind. |
| F-021 | niedrig | 3e | offen | – |  |
| F-022 | niedrig | 3b | offen | – |  |
| F-023 | niedrig | 3c | offen | – |  |
| F-024 | mittel | 2 | offen | – | Entscheidung nötig (Sperrumfang, Anonymisieren-Aktion) |
| F-025 | niedrig | 3e | offen | – | Entscheidung nötig (Datenschutz) |
| F-026 | niedrig | 3a | offen | – |  |
| F-027 | niedrig | 3e | offen | – |  |
| F-028 | niedrig | 3b | offen | – |  |
| F-029 | niedrig | 3e | offen | – | nur messen und berichten |
| F-030 | niedrig | 3a | offen | – |  |
| F-031 | mittel | 2 | offen | – | Löschen bestätigen lassen |
| F-032 | niedrig | 3d | offen | – |  |
| F-033 | niedrig | 3c | offen | – |  |
| F-034 | mittel | 2 | offen | – |  |
| F-035 | niedrig | 3c | offen | – |  |
| F-036 | mittel | 2 | offen | – | Entscheidung nötig (Compose-Änderung) |
| F-037 | mittel | 2 | offen | – | Entscheidung nötig (Version/Digests) |
| F-038 | niedrig | 3d | offen | – | Löschen initial_data.json bestätigen lassen |
| F-039 | niedrig | 3b | offen | – |  |
| F-040 | niedrig | 3a | offen | – |  |

## Protokoll

- 2026-10-29: Fortschrittsdatei angelegt, Basisläufe grün (siehe oben).
- 2026-10-29: F-009 umgesetzt. Erster Volllauf rot: 1 Turniertest (Anzeige `.name` → behoben über `stringformat`) und 15 Backup-Tests (`backup_err_compatible`, weil die F-020-Migration während des laufenden Tests angelegt wurde; Artefakt, kein Codefehler). Beobachtet: `TournamentQueryPerformanceTests.test_team_list_constant_queries_regardless_of_team_count` schlug in einem Teillauf reihenfolgeabhängig fehl, einzeln und im Volllauf grün.
- 2026-10-29: F-009 allein (Worktree `a184018`) und F-009+F-020 vollständig geprüft: check, deploy-check, makemigrations, Node 34/34 grün; Django 1433 bzw. 1441 Tests, jeweils **1 Fehlschlag** in `tournaments.tests.TournamentQueryPerformanceTests.test_team_list_constant_queries_regardless_of_team_count` (12 statt ≤ 11 Abfragen).
- 2026-10-29: Dieser Fehlschlag ist **unabhängig von den Änderungen**: Im Modullauf `tournaments.tests` schlug er auf dem unveränderten Ausgangsstand `b6115c5` fehl und war mit den Änderungen grün. Die Zusatzabfrage ist `SiteCustomization.load()`; der zuvor gewärmte Cacheeintrag fehlt zwischen beiden Messpunkten. Vermutlich LocMem-Culling (Django-Standard `MAX_ENTRIES=300`) abhängig von vorherigen Tests. Nicht behoben (außerhalb der Befunde); Vorschlag als Zusatzpunkt im Phasenbericht.
- 2026-10-29: Hinweis Arbeitsweise: Neue Migrationen nicht anlegen, während eine Suite läuft (Backup-Tests prüfen den Migrationsstand auf der Festplatte).
