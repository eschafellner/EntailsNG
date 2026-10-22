# Repository-Audit-Bericht: EntailsNG (Phase 1 – Read-Only)

> **Status:** Phase 1 strikt **READ-ONLY**. Es wurden während der Analyse keinerlei bestehende Dateien geändert, verschoben oder gelöscht.  
> **Projekt:** EntailsNG – LAN Event Management CMS  
> **Tech-Stack:** Python 3.12+ / Django 6.0.9, PostgreSQL 16, Redis 7, Nginx, Gunicorn, WhiteNoise, Vanilla JS  
> **Datum der Erhebung:** 18. Oktober 2026  

---

## Inhaltsverzeichnis
1. [Übersicht & Vorgehen](#1-übersicht--vorgehen)
2. [Kategorie: Veraltete Tests](#2-kategorie-veraltete-tests)
3. [Kategorie: Screenshots & Bilder](#3-kategorie-screenshots--bilder)
4. [Kategorie: Dokumentation](#4-kategorie-dokumentation)
5. [Kategorie: Review- & Agent-Artefakte](#5-kategorie-review---agent-artefakte)
6. [Kategorie: Code & Konfiguration](#6-kategorie-code--konfiguration)
7. [Kategorie: Generiertes & Lokales](#7-kategorie-generiertes--lokales)
8. [Sonstiges & Docker-Optimierung](#8-sonstiges--docker-optimierung)
9. [Gesamtzusammenfassung & Ersparnis](#9-gesamtzusammenfassung--ersparnis)
10. [Offene Fragen & Unsichere Fälle](#10-offene-fragen--unsichere-fälle)
11. [Vorschlag für .gitignore & .dockerignore](#11-vorschlag-für-gitignore--dockerignore)
12. [Risiken & Beachtenswertes vor Phase 2](#12-risiken--beachtenswertes-vor-phase-2)

---

## 1. Übersicht & Vorgehen

Im Rahmen von Phase 1 wurde das Repository auf unnötige, veraltete, duplizierte oder verwaiste Dateien untersucht.
Dazu wurden:
- Git-Status, Commit-Historie (`git log --follow`) und Git-Tracking analysiert.
- Statische Verweise in Templates, Views, URLs, Konfigurationen, Skripten und CI-Workflows geprüft.
- Dokumentationsdateien (`README.md`, `DEVELOPER_HANDOVER.md`, `INSTRUCTIONS.MD`, `docs/`) nach bewussten Festlegungen durchsucht.
- Ausnahmen berücksichtigt (Framework-Dateien wie `__init__.py`, Error-Templates `403.html`/`404.html`/`500.html`, reguläre Migrationen).

---

## 2. Kategorie: Veraltete Tests

| Pfad | Größe | Zuletzt geändert | Warum unnötig (Belege) | Referenziert von | Konfidenz | Empfehlung |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `scripts/tournament_mode_review.py` | 20.025 B | 2026-10-07 (`a9de64a`) | Standalone-Testrunner vom 01.10.2026 für die 6 Turniermodi. Die Tests wurden vollständig in die reguläre Django-Testsuite (`tournaments/test_format_improvements.py`) integriert. Weder CI (`.github/workflows/ci.yml`) noch Skripte führen die Datei aus. | Historisch erwähnt in `docs/tournament-mode-review-2026-10-01.md` und `docs/tournament-result-management.md` | **Mittel** | Archivieren / Löschen |
| `scripts/performance_smoke.py` | 6.421 B | 2026-10-06 (`9b42898`) | Früherer In-Memory-Lasttest mit Djangos Testclient. Laut `docs/developer-handover-remediation-plan.md` (Z. 92) durch `scripts/http_performance_smoke.py` ersetzt, welcher echte HTTP-Requests an Gunicorn/Nginx sendet und fest in CI/Container-Smoke eingebunden ist. | `docs/performance-smoke-2026-09-26.md` | **Mittel** | Prüfen / Archivieren |
| `seating/tests.py` (`test_initial_data_fixture_seating_cells_unique_labels`) | ~30 Zeilen (Z. 1659–1688) | 2026-09-22 (`11f83a4`) | Testet ausschließlich das veraltete Fixture `initial_data.json` auf doppelte Sitzplatzbezeichnungen. Fängt das Fehlen per `self.skipTest('initial_data.json nicht vorhanden.')` ab. Wird obsolet, sobald das Fixture entfernt wird. | `seating/tests.py` | **Hoch** | Prüfen / Löschen (zusammen mit `initial_data.json`) |

---

## 3. Kategorie: Screenshots & Bilder

Im Verzeichnis `docs/screenshots/` befinden sich 25 Bilddateien mit einem Gesamtvolumen von ca. 2,3 MB.
Davon werden **11 Dateien in keinem Dokument, Template oder Quellcode referenziert**:

| Pfad | Größe | Zuletzt geändert | Warum unnötig (Belege) | Referenziert von | Konfidenz | Empfehlung |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `docs/screenshots/clan-admins-demotion.png` | 92.825 B | 2026-10-03 (`27bc771`) | Temporärer UI-Screenshot; 0 Referenzen im gesamten Repo. | Niemandem | **Hoch** | Löschen / Archivieren |
| `docs/screenshots/clan-admins-mobile.png` | 70.061 B | 2026-10-03 (`27bc771`) | Temporärer UI-Screenshot; 0 Referenzen im gesamten Repo. | Niemandem | **Hoch** | Löschen / Archivieren |
| `docs/screenshots/clan-admins-mobile-viewport.png` | 35.904 B | 2026-10-03 (`27bc771`) | Temporärer UI-Screenshot; 0 Referenzen im gesamten Repo. | Niemandem | **Hoch** | Löschen / Archivieren |
| `docs/screenshots/clan-payment-pending-mobile.png` | 118.633 B | 2026-10-08 (`9a39f76`) | UI-Screenshot; 0 Referenzen (andere Zahlungsansichten wie `-assigned-` und `-preview-` sind eingebunden). | Niemandem | **Hoch** | Löschen / Archivieren |
| `docs/screenshots/clan-seat-configuration.png` | 79.690 B | 2026-10-04 (`03d652b`) | UI-Screenshot; 0 Referenzen im gesamten Repo. | Niemandem | **Hoch** | Löschen / Archivieren |
| `docs/screenshots/clan-seat-member-mobile.png` | 32.537 B | 2026-10-04 (`03d652b`) | UI-Screenshot; 0 Referenzen im gesamten Repo. | Niemandem | **Hoch** | Löschen / Archivieren |
| `docs/screenshots/clan-seat-member-view.png` | 72.293 B | 2026-10-04 (`03d652b`) | UI-Screenshot; 0 Referenzen im gesamten Repo. | Niemandem | **Hoch** | Löschen / Archivieren |
| `docs/screenshots/clan-seat-selection-desktop.png` | 81.135 B | 2026-10-04 (`03d652b`) | UI-Screenshot; 0 Referenzen im gesamten Repo. | Niemandem | **Hoch** | Löschen / Archivieren |
| `docs/screenshots/clan-seat-selection-mobile.png` | 6.878 B | 2026-10-04 (`03d652b`) | UI-Screenshot; 0 Referenzen im gesamten Repo. | Niemandem | **Hoch** | Löschen / Archivieren |
| `docs/screenshots/team-invitation-accepted-mobile.png` | 84.672 B | 2026-10-03 (`27bc771`) | UI-Screenshot; 0 Referenzen im gesamten Repo. | Niemandem | **Hoch** | Löschen / Archivieren |
| `docs/screenshots/team-invitation-player.png` | 121.223 B | 2026-10-03 (`27bc771`) | UI-Screenshot; 0 Referenzen im gesamten Repo. | Niemandem | **Hoch** | Löschen / Archivieren |

*Zwischensumme: 11 Bilddateien, **795.851 Bytes (~796 KB)**.*

---

## 4. Kategorie: Dokumentation

| Pfad | Größe | Zuletzt geändert | Warum unnötig (Belege) | Referenziert von | Konfidenz | Empfehlung |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `docs/verification-history.md` | 72.303 B | 2026-10-16 (`f681162`) | Enthält historische Prüfberichte aus Sep/Okt 2026. In `DEVELOPER_HANDOVER.md` (Z. 3) ausdrücklich als Alt-Archiv deklariert (*"bleibt archiviert"*). Bläht den Quelltextbaum auf. | `DEVELOPER_HANDOVER.md` | **Mittel** | Außerhalb des Repos archivieren |
| `docs/developer-handover-audit-2026-10-15.md` | 39.092 B | 2026-10-16 (`f681162`) | Dokumentiert den Mängelzustand *vor* den Remediation-Korrekturen (P1–P6). Laut Handover nur noch historischer Referenzstand. | `DEVELOPER_HANDOVER.md` | **Mittel** | Archivieren |
| `docs/developer-handover-remediation-plan.md` | 19.219 B | 2026-10-16 (`f681162`) | Maßnahmenplan für P1–P6; die Punkte sind laut `docs/remediation-progress.md` abgeschlossen. | `docs/remediation-progress.md` | **Mittel** | Archivieren |
| `docs/tournament-audit-2026-10-01.md` | 10.424 B | 2026-10-06 (`9b42898`) | Historisches Vorab-Audit der Turniermodi vor den Bugfixes Anfang Oktober 2026. | Alte Review-Docs | **Mittel** | Archivieren |
| `docs/tournament-mode-review-2026-10-01.md` | 14.128 B | 2026-10-06 (`9b42898`) | Review-Mängelliste der Turniermodi; durch Migrationen 0009–0010 und Tests abgelöst. | Alte Review-Docs | **Mittel** | Archivieren |
| `docs/tournament-mode-improvements-2026-10-01.md` | 8.901 B | 2026-10-06 (`9b42898`) | Implementierungsnotizen zu behobenen Turniermodi. | Alte Review-Docs | **Mittel** | Archivieren |
| `docs/performance-smoke-2026-09-26.md` | 2.605 B | 2026-10-06 (`9b42898`) | Dokumentiert den veralteten Testlauf von `scripts/performance_smoke.py`. | Niemandem aktiv | **Mittel** | Archivieren |

---

## 5. Kategorie: Review- & Agent-Artefakte

| Pfad | Größe | Zuletzt geändert | Warum unnötig (Belege) | Referenziert von | Konfidenz | Empfehlung |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `docs/tournament-mode-review-results-2026-10-01.json` | 7.342 B | 2026-10-03 (`27bc771`) | Enthält rohe Windows-Testfehlermeldungen (`C:\Users\ed_sc\EntailsNG\...`) eines abgebrochenen Laufs von `scripts/tournament_mode_review.py`. 0 Vorkommen im Code oder der Doku. | Niemandem | **Hoch** | Löschen |
| `docs/tournament-mode-improvements-results-2026-10-01.json` | 675 B | 2026-10-03 (`27bc771`) | Maschinenlesbarer Zwischenstand aus dem alten Review. | `docs/tournament-mode-improvements-2026-10-01.md` | **Mittel** | Archivieren / Löschen |
| `docs/verification/` (20 Dateien in `b1-2026-10-16/` und `remediation-2026-10-15/`) | ~28.000 B | 2026-10-16 (`f681162`) | Generierte Testlauf-Dumps (`summary.json`, `runtime.json`, `runtime-requirements.txt`, etc.). Gehören laut CI-Konzept in das ignorierte `/smoke-results/`, wurden aber laut `docs/b1-django-security-update-plan.md` als einmaliger Release-Nachweis committet. | `docs/b1-django-security-update-results.md` | **Niedrig / Mittel** | Prüfen (als Audit-Nachweis belassen oder in Release-Assets auslagern) |

---

## 6. Kategorie: Code & Konfiguration

| Pfad | Größe | Zuletzt geändert | Warum unnötig (Belege) | Referenziert von | Konfidenz | Empfehlung |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `initial_data.json` | 195.179 B | 2026-09-22 (`11f83a4`) | Historischer DB-Snapshot. In `README.md` (Z. 209) und `DEVELOPER_HANDOVER.md` (Z. 93) als *"kein unterstützter Setupweg"* deklariert. Scheitert bei `loaddata` an `IntegrityError` (doppelte Template-Keys). Wurde durch atomares `seed_demo_data` (`configuration/demo.py`) abgelöst. | `seating/tests.py` (mit Skip-Guard) | **Hoch** | Archivieren / Löschen |
| `templates/seating/seating_plan.html` | 481 B | 2026-09-09 (`67c87b0`) | Verwaister HTML-Stub (16 Zeilen) mit Platzhalter: `<!-- Hier dein bestehender Sitzplan-HTML/JS-Code -->`. Der tatsächliche Sitzplan wird über `seating/templates/seating/seating.html` gerendert. 0 Referenzen. | Niemandem | **Hoch** | Löschen |
| `tournaments/management/commands/seed_tournaments.py` | 5.741 B | 2026-09-08 (`0febbbc`) | Veralteter Seeding-Befehl aus der Anfangsphase (erstellt fixe Demo-Spiele). Wird von keinem Skript (`install.sh`, `start.sh`, `entrypoint.sh`), keinem Test und keiner Doku aufgerufen. Vollständig abgelöst durch `seed_demo_data`. | Niemandem | **Hoch** | Löschen |
| `configuration/management/commands/reset_demo_data.py` | 409 B | 2026-10-15 (`f681162`) | Veralteter Alias; gibt selbst aus: *"reset_demo_data ist veraltet; bitte seed_demo_data verwenden. Es erfolgt kein Reset."* Wurde bei der Bereinigung nur als Übergangs-Alias belassen. | `configuration/admin.py` (Button/URL) und Tests | **Mittel** | Prüfen (Admin-Aktion auf `seed_demo_data` umstellen, danach löschen) |

---

## 7. Kategorie: Generiertes & Lokales

| Pfad | Größe | Zuletzt geändert | Warum unnötig (Belege) | Referenziert von | Konfidenz | Empfehlung |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `media/sponsors/test_*.png` | ~18 MB | 2026-10-15 | Hunderte generierte Test-Uploads in `media/`, die sich durch Testläufe/Seeding angesammelt haben. `media/` ist in `.gitignore`, die Dateien belegen aber lokal Speicherplatz. | Frühere temporäre Testdatenbanken | **Hoch** | Lokal bereinigen (`rm -f media/sponsors/test_*`) |
| `staticfiles/` | ~24 MB | Lokaler Stand | Generierte statische Assets aus `collectstatic`. Ist in `.gitignore`. | Nginx im Live-Betrieb | **Hoch** | In `.gitignore` belassen |
| `.agents/` | 0 B | 2026-09-26 | Leeres Verzeichnis aus früherer KI-Agent-Nutzung. Nicht getrackt, aber aktuell nicht in `.gitignore`. | `scripts/container_smoke.py:50` | **Hoch** | In `.gitignore` aufnehmen oder Verzeichnis löschen |
| `.codex/` | 0 B | 2026-09-26 | Leeres Verzeichnis aus früherer Codex-Agent-Nutzung. Nicht getrackt, aber aktuell nicht in `.gitignore`. | `scripts/container_smoke.py:50` | **Hoch** | In `.gitignore` aufnehmen oder Verzeichnis löschen |

---

## 8. Sonstiges & Docker-Optimierung

- **Leere `__init__.py`-Dateien:**  
  Es existieren 28 leere `__init__.py`-Dateien in Modulen und Migrationsordnern (z. B. `config/__init__.py`, `users/migrations/__init__.py`).  
  *Bewertung:* **Erhalt zwingend erforderlich** (Python-Paketdeklaration und Django-App-Discovery). Keine Löschung!
- **Docker-Kontext (`.dockerignore`):**  
  Die Datei `.dockerignore` schließt aktuell weder `docs/` (inkl. 2,3 MB Screenshots), noch `initial_data.json` oder `scripts/tests/` aus. Beim Docker-Build (`COPY . /app/` in `Dockerfile`) landen all diese Artefakte unnötig im Produktions-Image.

---

## 9. Gesamtzusammenfassung & Ersparnis

- **Kandidaten im Git-Repository:** 18 Dateien (11 Screenshots, 3 Code/Template-Dateien, 2 Testskripte, 2 JSON-Ergebnisdateien) + 7 historische Markdown-Dokumente.
- **Geschätzte direkte Platzersparnis im Git-Tree:** ca. **1,03 MB** allein durch verwaiste Screenshots, `initial_data.json` und alte Skripte (bis zu **1,2 MB** bei Auslagerung historischer Dokumentationen).
- **Lokale Dateisystem-Ersparnis:** ca. **18 MB** durch Bereinigung verwaister Test-Medien in `media/sponsors/`.

---

## 10. Offene Fragen & Unsichere Fälle

Vor der Freigabe von Phase 2 sollten folgende Punkte abgestimmt werden:

1. **`docs/verification/` & historische Docs (`docs/verification-history.md`, `docs/developer-handover-audit-2026-10-15.md`):**  
   Sollen diese Dokumente und Prüf-JSONs im Git-Repository verbleiben (als Nachweis für Releases), oder sollen sie in ein externes Archiv / Wiki ausgelagert werden?
2. **`configuration/management/commands/reset_demo_data.py`:**  
   Soll der Alias erhalten bleiben, bis die Admin-Oberfläche (`reset_demo_data_button` in `configuration/admin.py`) formal umbenannt wird, oder soll die Admin-Aktion direkt auf `seed_demo_data` migriert und der Alias gelöscht werden?
3. **`scripts/performance_smoke.py`:**  
   Wird der isolierte In-Memory-Client-Test noch für schnelle Vergleiche ohne laufenden Stack benötigt, oder genügt `scripts/http_performance_smoke.py` vollständig?

---

## 11. Vorschlag für .gitignore & .dockerignore

### Ergänzungen für `.gitignore`:
```gitignore
# KI- und Agenten-Arbeitsverzeichnisse
.agents/
.codex/
.aws/

# Test- & Coverage-Artefakte
.coverage
htmlcov/
.pytest_cache/

# Node-Artefakte (falls lokale Tests ausgeführt werden)
node_modules/
npm-debug.log*

# OS-Artefakte
.DS_Store
Thumbs.db
*.swo
*~
```

### Ergänzungsempfehlung für `.dockerignore`:
```dockerignore
docs/
initial_data.json
scripts/tests/
```

---

## 12. Risiken & Beachtenswertes vor Phase 2

- **Dynamisch geladene Templates:**  
  Django lädt Error-Templates (`403.html`, `404.html`, `500.html`) implizit über den Exception-Handler. Diese dürfen keinesfalls gelöscht werden.
- **Abhängigkeit in `seating/tests.py`:**  
  Vor dem Löschen von `initial_data.json` muss der Test `test_initial_data_fixture_seating_cells_unique_labels` in `seating/tests.py` entfernt oder angepasst werden, da er sonst dauerhaft übersprungen wird.
- **Admin-Verdrahtung von `reset_demo_data`:**  
  `configuration/admin.py` referenziert den URL-Namen `reset_demo_data_admin`. Ein unbedachtes Entfernen ohne Anpassung von `admin.py` würde zu `NoReverseMatch`-Laufzeitfehlern im Django-Admin führen.
