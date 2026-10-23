# B1 – Django-Sicherheitsupdate und Prüfnachweise

Stand: 16. Oktober 2026. Umsetzung auf Ausgangscommit `f681162` mit uncommittierten B1-Änderungen. Status: **technische Abnahme erfolgreich; Rollout der Zielinstallation offen.** Es wurde kein Produktionsdeployment ausgeführt. Der [Umsetzungsplan](b1-django-security-update-plan.md) bleibt als Grundlage erhalten.

## Änderungen

- Django von 6.0.7 auf **6.0.9** aktualisiert. Die [Herstellerhinweise](https://docs.djangoproject.com/en/6.0/releases/6.0.9/) bestätigen die Korrektur von CVE-2026-84429; die [Versionsübersicht](https://www.djangoproject.com/download/) führt 6.0.9 am Prüfdatum als aktuellen Patch der unterstützten 6.0-Reihe. Kein Wechsel der Django-Reihe und keine Fachmigration.
- python-dotenv von 1.0.1 auf **1.2.4** aktualisiert. Der erste Audit meldete CVE-2026-28684 für die bisherige Version; laut [Maintainer-Advisory](https://github.com/theskumar/python-dotenv/security/advisories/GHSA-mf9w-mj56-hr94) ist der Fehler ab 1.2.2 korrigiert. Projektaufrufe von `set_key()`/`unset_key()` wurden nicht gefunden. Die aktualisierte Version beseitigt den Paketbefund ohne Ausnahme.
- **pip 26.2.1** für Dockerbuild und CI-Anwendungsumgebung festgelegt. Der erste Audit des lokalen temporären Environments meldete für pip 26.0.1 vier unterschiedliche CVEs: CVE-2026-8643, CVE-2026-3219, CVE-2026-6357 und CVE-2026-13346. Sie betreffen Installationsvorgänge; das Update des mitgelieferten Installers vermeidet ungeklärte Befunde im vollständigen Imageinventar.
- `scripts/dependency_inventory.py` exportiert alle installierten Distributionen einschließlich pip. Der Guard verlangt den exakten Django-Pin und mindestens Version 6.0.9 innerhalb der gewählten Reihe. Doppelt sichtbare identische Distributionen über `lib`/`lib64` werden zusammengeführt; unterschiedliche Versionen desselben Pakets führen zum Abbruch.
- `scripts/audit_dependencies.py` prüft dieses vollständige Inventar mit **pip-audit 2.10.1**, separat von den Anwendungspaketen, gegen die PyPI-Sicherheitsdatenbank. Es gibt keine CVE-Ausnahmen. Fehlende/übersprungene Pakete, Findings, Abruffehler und Timeouts verhindern eine erfolgreiche Prüfung. Rohmeldungen bleiben erhalten; die Zusammenfassung führt doppelte Advisory-/CVE-Meldungen zusammen.
- CI prüft die Inventare der frischen Python-3.12-Anwendungsumgebung und des tatsächlichen Images. Der Deploymentcheck scheitert bereits bei Warnungen; hierfür wird HTTPS-Weiterleitung gezielt aktiviert, während die Tests ihre bisherige Testkonfiguration behalten.
- Der isolierte Container-Smoke erfasst Image-ID, tatsächliche Versionen und `pip check` aller vier Anwendungsdienste, prüft deren identischen Imagebezug und führt den strikten Deploymentcheck aus. Kleine HTTP-Headerproben unterscheiden erfolgreiche Django-Verarbeitung von Nginx-Ablehnung doppelter Host-Header. Doppelte Content-Type-Header werden auf dieser Strecke mit HTTP 200 verarbeitet. Die 15 Header-/Dependency-Gate-Tests laufen immer im Image; optional führt `--tests` die vollständige Django-Suite aus.
- Zwei vorhandene Deadline-Tests in `seating/test_clan_payments.py` vergleichen jetzt Wiener Kalendertage statt einer festen Anzahl UTC-Stunden. Ein zusätzlicher fester DST-Fall prüft explizit die 49 Stunden zwischen 23. und 25. Oktober 2026. Die Zahlungslogik wurde nicht geändert.

## Kompatibilitätsprüfung der Herstellerhinweise

Die [Release Notes zu 6.0.8](https://docs.djangoproject.com/en/6.0/releases/6.0.8/) und 6.0.9 wurden zusätzlich zum Scanner geprüft:

| Bereich | Projektbezug und Prüfung |
| --- | --- |
| Headerparser / CVE-2026-84429 | Der tatsächlich installierte WSGI-Konstruktor ruft `_set_content_type_params()` und `parse_header_parameters()` auf; 6.0.9 verwendet dort `email.message.Message`. Direkte WSGI-, Accept-, RFC-2231-, Formular- und Multipartprüfungen ergänzt. |
| GeoDjango / CVE-2026-15307, CVE-2026-15830, CVE-2026-87890 | Keine GIS-App und keine GeoDjango-Aufrufe im Projekt gefunden. Die aktualisierte Django-Version enthält trotzdem die zugehörigen Korrekturen; fehlende Projektverwendung wird nicht mit einer behobenen Paketversion verwechselt. |
| Model-/Inlineformsets / CVE-2026-87975 | Fachmodelle verwenden Auto-Primärschlüssel; Ausnahme ist `KnowledgeAttachment.id` als nicht bearbeitbare UUID. Djangos Sessionmodell hat einen CharField-PK, wird aber nicht als bearbeitbares Projektformset angeboten. Vorhandene Formular-/Adminprüfungen bleiben Teil der Gesamtsuite. |
| Sprachcodeverarbeitung | Keine LocaleMiddleware, set_language-Route oder eigenen Aufrufe der betroffenen Sprachcodefunktionen gefunden. Die Herstellerkorrekturen werden mit dem Patch übernommen. |
| Admin-URLField / CVE-2026-15920 | URLFields sind etwa bei Clans und Sponsoren vorhanden. Die Frameworkkorrektur wird übernommen; vorhandene Formular-/Admintests bleiben Teil der Gesamtsuite. |

Die Sicherheitskorrektur wird durch Paketstand und Herstellerhinweise belegt. Der begrenzte Unterprozesstest mit 4.096 Trennzeichen ist ein Regressionssignal mit Timeout, kein DoS-Lastversuch oder Komplexitätsbeweis. Die HTTP-Lastmatrix prüft bestehende Fachabläufe; sie ist ebenfalls kein Header-DoS-Test.

## Reproduzierbare Prüfungen

Primärumgebung: frisch gebautes Python-3.12-Image mit PostgreSQL 16 und Redis 7, eigenen Schlüsseln, Ports, Datenbanken und Volumes. Die Anwendungs-`.env` und bestehenden Daten werden nicht übernommen. Die vollständige Suite und die Setupprüfungen laufen in dieser isolierten Umgebung:

```bash
python3 scripts/container_smoke.py --output-dir /tmp/entails-b1-evidence/acceptance --performance --tests --test-processes 4
```

Das Inventar des Images wird anschließend in einer separaten Werkzeug-venv geprüft:

```bash
python3 -m venv /tmp/entails-b1-audit
/tmp/entails-b1-audit/bin/python -m pip install pip-audit==2.10.1
/tmp/entails-b1-audit/bin/python scripts/audit_dependencies.py \
  --inventory /tmp/entails-b1-evidence/acceptance/runtime-requirements.txt \
  --output-dir /tmp/entails-b1-evidence/acceptance
node --test scripts/tests/*.test.cjs
```

Zusätzliche lokale Python-3.14.8-Prüfung in einer neuen temporären venv: 15 Header-/Dependency-Gate-Tests erfolgreich, `pip check` ohne Konflikte und vollständiger Audit von 18 Paketen ohne bekannte Lücken. Die zusätzliche Python-Version ist kein Ersatz für die Primärumgebung. Der Workflow wurde mit Actionlint geprüft.

Der erste serielle Gesamtlauf fand den bisherigen Datumstestfehler: Bei zwei Wiener Kalendertagen über die Herbstumstellung verlangt die alte Assertion fälschlich exakt 48 statt 49 Stunden. Derselbe einzelne Test wurde in einer separaten Test-venv auf **Django 6.0.7** mit identischem Fehler reproduziert. Die korrigierte Assertion und der feste DST-Fall wurden im abschließenden Gesamtlauf erfolgreich geprüft. Die Paralleloption verwendet separate Django-Testdatenbanken; CI behält seinen seriellen Gesamtlauf.

Im Python-Produktionsimage fehlt absichtlich Node. Deshalb überspringt die Django-Suite dort `SeatingViewerFrontendTests.test_seating_js_listeners_not_duplicated_on_multiple_reloads`. Dieser ausschließlich JavaScript ausführende Test wurde zusätzlich auf dem Host mit Node **24.18.0** direkt und erfolgreich aufgerufen; außerdem bestanden die fünf regulären JavaScript-Testdateien. CI stellt weiterhin Node 22 bereit und führt den Sitzplan-Test regulär über die Django-Suite aus.

## Abschließende Ergebnisse

| Prüfung | Ergebnis |
| --- | --- |
| Django-Gesamtsuite im finalen Python-3.12.15-Image | **1.335 Tests**, 170,389 Sekunden, vier getrennte Testprozesse/-datenbanken; keine Fehler, ein erklärter Node-Skip. Den übersprungenen JavaScript-Test zusätzlich erfolgreich auf dem Host ausgeführt. |
| Header-/Dependency-Gates | Alle 15 Prüfungen bestanden; im Gesamtlauf enthalten, außerdem separat im Image und lokal auf Python 3.14.8 geprüft. |
| JavaScript | Alle fünf Testdateien erfolgreich auf Node 24.18.0; zusätzlicher Sitzplan-Listener-Test erfolgreich. CI verwendet Node 22. |
| Dependency-Audit des finalen Images | 19 Pakete einschließlich transitiver Abhängigkeiten und pip vollständig geprüft; keine Befunde, keine Ausnahmen. |
| Deployment und Konsistenz | Strikter Deploymentcheck ohne Warnungen; `pip check` in Web sowie allen drei Workern erfolgreich. Alle vier verwenden dasselbe geprüfte Image. |
| Setup und Migrationen | PostgreSQL 16.15; frische Migrationen, unveränderte Seed-/Demowiederholung, zehn Seiten, einmalige Teamcode-Rotation und Migrationsabgleich erfolgreich. |
| Laufzeit und HTTP | Reales prozessübergreifendes Redis, DB-/Cache-Ausfallerkennung, sieben laufende Dienste, vier HTTPS-/Assetpfade und fünf Headerproben erfolgreich. |
| Bestehende HTTP-Fachlastmatrix | 864 Requests, keine unerwarteten Fehler; pro Sitzplatzkonkurrenz genau ein Gewinner. Diagnostische Messwerte ohne zugesicherte Latenz-/Kapazitätsgrenze. |
| Statische Prüfung und Aufräumen | Actionlint, Python-Syntax und Diffprüfung erfolgreich. Eigene Testcontainer, Volumes, Netzwerke und temporäre Smoke-Images entfernt. |

Dauerhafte Nachweise (Zusammenfassung, Runtimeinventar, Image-/Dienstabgleich, Audit samt Vollständigkeitsprüfung und Rohmeldungen, Header-HTTP, Setup, Ausfallerkennung, HTTP-Matrix, Baseline-Reproduktion auf Django 6.0.7 und Prüfsummen der geänderten Code-/Konfigurationsdateien) liegen seit 23.10.2026 im Dokumentationsarchiv außerhalb des Projekts unter `entails-ng-archiv/docs/verification/b1-2026-10-16/`.

Das abschließend geprüfte Image hatte die ID `sha256:6b6df3794c93a24f1ce51106564230c486cf1c1053051cda2ccad098a43941ef`. Der Smoke entfernt seine Testimages nach dem Lauf; für einen Rollout ist ein eigener Releasebuild aus dem geprüften Quellstand mit erneutem Paket-/Imageabgleich nötig. Bereinigte Rohlogs einschließlich des ersten fehlgeschlagenen Gesamtlaufs und der erfolgreichen Wiederholung liegen unter `/tmp/entails-b1-evidence/`. Historische Prüfzahlen wurden nicht verändert.

## Betriebsgrenze und nächster Wartungsschritt

Ein erfolgreicher lokaler Containerlauf ist kein GitHub-CI-Run und kein Produktionsrollout. Für die Zielinstallation bleiben die Übernahme des geprüften Quell-/Imagestands, der Versions- und Imageabgleich für Web und aktive Worker sowie externe HTTPS-/Tunnelprüfung nach [updating.md](updating.md) erforderlich. B1 wird für diese Installation erst nach diesem Nachweis geschlossen. In dieser Umsetzung wurde keine bestehende Installation umkonfiguriert.

Django 6.0 erhält laut Hersteller bis April 2027 Sicherheitskorrekturen. Der Wechsel auf eine dann unterstützte Reihe ist als DEP-01 im [Entwicklungsbacklog](development-backlog.md) erfasst. Die Entscheidung zu USERS-03 bleibt unverändert.
