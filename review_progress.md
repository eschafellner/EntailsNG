# Code-Review EntailsNG – Fortschritt

Beginn: 2026-10-28 · Grundlage: `DEVELOPER_HANDOVER.md` (Stand 16.10.2026) · Repo-Stand: `85ba422` (main, sauber)
Befunde im Detail: [review_findings.md](review_findings.md)

## Arbeitsumgebung des Reviews

- Lokale `.venv`: Python 3.14.8, wird **nicht** verändert (weicht von `requirements.txt` ab, siehe Befund).
- Für Tests: Wegwerf-venv und Wegwerf-PostgreSQL-Cluster (PG 18.6, lokale Binaries) im Scratchpad unter
  `/tmp/claude-1000/-home-edgar-Videos-entails-ng/e9b5d0dc-8b19-5ffd-b42a-2ad22ff5882e/scratchpad`, kein Zugriff auf bestehende DB/Docker-Volumes.
- Kein Redis lokal → Redis-abhängige Prüfungen nur statisch.

## Modulliste (Prüfreihenfolge: Grundlagen vor Abhängigen)

| # | Modul | Umfang (Prod/Test/Migr. Zeilen) | Status | Befunde |
|---|---|---|---|---|
| M00 | Baseline: `check`, Migrations-Dry-Run, Testlauf, Syntax/Imports | – | geprüft (1335 Tests OK, 270 s) | F-001–F-003 |
| M01 | `config` (Settings, URLs, WSGI/ASGI) + `requirements.txt` | 497 / 238 / – | geprüft | F-004–F-008 |
| M02 | `configuration` (Cache, Texte, Middleware, Sanitizer, Themes, Demo, Commands) | 4230 / 1951 / 749 | geprüft | F-009–F-014 |
| M03 | `users` (Auth-Backend, Verifizierung, Sperren, Löschung) | 2333 / 2199 / 337 | geprüft | F-015–F-019 |
| M04 | `emails` (SMTP-Backend, Crypto, Outbox, Commands) | 2380 / 1460 / 349 | geprüft | F-020–F-023 |
| M05 | `events` (Event, Tickets, Anmeldung, Zahlung, Check-in) | 2643 / 2967 / 378 | geprüft | F-024–F-026 |
| M06 | `clans` | 934 / 988 / 181 | geprüft | F-027 |
| M07 | `seating` (Sitzplätze, Clan-Holds, Sammelzahlungen) | 3094 / 2930 / 351 | geprüft | F-028–F-030 |
| M08 | `tournaments` (inkl. `services/`-Paket) | 8025 / 9040 / 756 | geprüft (Schwerpunkt Authz/Integrität) | F-031 |
| M09 | `contact` | 310 / 471 / – | geprüft | F-032 |
| M10 | `info` (CMS, Einbettungen) | 558 / 538 / 198 | geprüft | – |
| M11 | `knowledge` (private Anhänge) | 817 / 500 / 126 | geprüft | – |
| M12 | `news` | 264 / 289 / 103 | geprüft | – |
| M13 | `sponsors` | 287 / 561 / 80 | geprüft | – |
| M14 | `media_designer` | 824 / 540 / 69 | geprüft | – |
| M15 | `backups` | 1638 / 600 / – | geprüft | – |
| M16 | Globale Templates (`base`, Fehlerseiten, Dashboard, `admin/`, `includes/`) | ~6000 Zeilen HTML gesamt | geprüft | F-033 (+ Ergänzung F-006) |
| M17 | Statische Dateien (JS/CSS) | 2301 JS / 3351 CSS | geprüft | F-034, F-035 |
| M18 | `scripts/` + Node-Tests | 1285 | geprüft | – (Node 31/31 OK) |
| M19 | Deployment (Dockerfile, Compose, Entrypoint, Nginx, `.env.example`, install/start) | – | geprüft | F-036–F-039 |
| M20 | CI + Testabdeckung übergreifend | – | geprüft (88 % Coverage) | F-040 |
| M21 | Doku-Abgleich & Repo-Hygiene (README, INSTRUCTIONS, Handover, Altlasten) | – | geprüft | Abweichungstabelle in Befunddatei |

App-spezifische Templates, Management-Commands, Migrationen und Tests werden jeweils im zugehörigen App-Modul geprüft.

## Abweichungen Handover ↔ Repository (laufend)

- Handover-Datei heißt `DEVELOPER_HANDOVER.md`, nicht `developers_handover.md`.
- Handover Z. 79 „Keine Standardkonten/-passwörter“ ↔ `seed_tournaments` (F-031).
- Handover Z. 17/101-105 (separater Mail-Worker) ↔ zusätzlicher Versand-Thread im Webprozess (F-021).
- Handover nennt nicht, dass `change_systemtranslation`, `view_outgoingemail`, `change_generalemailsettings` faktisch superuser-äquivalent sind (F-009, F-020).

## Protokoll

- 2026-10-28: Modulliste erstellt.
- 2026-10-28: M00 check/deploy-check/makemigrations/compileall/pyflakes erledigt; Volltest läuft (Log: Scratchpad `test_full.log`). Wegwerf-PG: `pg_ctl -D <scratchpad>/pgdata` Port 55432, DB `entails_review` (migriert), Env-Datei `<scratchpad>/env.sh`.
- 2026-10-28: M01 abgeschlossen.
- 2026-10-28: M00 Volltest: 1335 Tests OK, 0 übersprungen (CI-äquivalente Env, Redis→LocMem). M02 abgeschlossen (F-009 hoch: Format-String-Leak SECRET_KEY).
- 2026-10-28: M03 abgeschlossen. Offene Querverweise nach M19: Nginx muss X-Real-IP/X-Forwarded-For/-Proto auf allen Eingängen setzen (users/auth_backends.py:24-56, users/forms.py:267).
- 2026-10-28: M04 abgeschlossen (F-020 hoch: Reset-Links in Outbox für Staff lesbar). Querverweis M19: Restart-Policy der Worker-Container prüfen (F-022).
- 2026-10-28: M05 abgeschlossen. Querverweis M17: innerHTML-Senken in guest_list.html:381 und checkin-scanner.js (gescannter Rohtext in message).
- 2026-10-28: M06 abgeschlossen.
- 2026-10-28: M07 abgeschlossen.
- 2026-10-28: M08 abgeschlossen (Algorithmen der Auslosung/Brackets nicht zeilenweise geprüft, durch 9.000 Testzeilen abgedeckt). Querverweis M16: {% t %} in JS-Strings.
- 2026-10-28: M09 (F-032) und M10–M15 abgeschlossen (keine eigenständigen Befunde).
- 2026-10-28: M16 (F-033) und M17 (F-034 mittel: Admin-DOM-XSS über seat_label, F-035) abgeschlossen; Node-Tests 31/31 OK.
- 2026-10-28: M18 (keine Befunde, Schutzschalter in allen Smoke-Skripten) und M19 (F-036–F-039) abgeschlossen. Nginx-Header-Abhängigkeit aus M03 erfüllt.
- 2026-10-28: M20 (Coverage 88 %, F-040) und M21 abgeschlossen. **Review vollständig: 40 Befunde (2 hoch, 9 mittel, 29 niedrig).** Wegwerf-PG gestoppt; Neustart bei Bedarf: `pg_ctl -D <scratchpad>/pgdata -o "-p 55432 -c unix_socket_directories='' -c listen_addresses=127.0.0.1" start`.

## Nächste Schritte (warten auf Freigabe)

Keine Codeänderungen vorgenommen. Vorschlag zur Umsetzungsreihenfolge siehe Zusammenfassung in `review_findings.md`.
