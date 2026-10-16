# B1 – Umsetzungsplan für das Django-Sicherheitsupdate

Stand: 16. Oktober 2026. Status: **technisch umgesetzt und abgenommen; Zielrollout offen**; aktueller Stand und Nachweise: [Umsetzung B1](b1-django-security-update-results.md). Die folgenden Abschnitte halten den ursprünglichen Umsetzungsplan fest. Priorität: Releaseblocker. Aufwand: **M** – begrenztes Dependency-Update mit zusammenhängender Sicherheits-, Integrations- und Betriebsprüfung; keine verbindliche Zeitschätzung.

## Ziel und Versionsentscheidung

EntailsNG soll vor der Releasefreigabe einen korrigierten Django-Patchstand verwenden. Ziel ist **Django 6.0.9**, laut [offizieller Versionsübersicht](https://www.djangoproject.com/download/) am Prüfdatum der aktuelle Patch der weiterhin unterstützten 6.0-Reihe. Unmittelbar vor der Umsetzung die Herstellerhinweise erneut prüfen und gegebenenfalls den neueren korrigierten 6.0.x-Patch **exakt** pinnen. Ein Wechsel auf 6.1 ist für diesen Blocker nicht erforderlich. Die Sicherheitsunterstützung von 6.0 endet im April 2027; die Folgemigration gehört rechtzeitig ins Entwicklungsbacklog.

Die [Release Notes zu 6.0.9](https://docs.djangoproject.com/en/6.0/releases/6.0.9/) bestätigen die Korrektur von CVE-2026-84429 und eine Änderung des Headerparsers. Deshalb gehören Headerverarbeitung und betroffene Anfrageformate ausdrücklich zur Abnahme. Zusätzlich werden die Änderungen aus [6.0.8](https://docs.djangoproject.com/en/6.0/releases/6.0.8/) auf Projektbezug geprüft.

## Verifizierter Projektausgangspunkt

- [requirements.txt](../requirements.txt) pinnt `Django==6.0.7` und `python-dotenv==1.0.1`. Direkte Abhängigkeiten sind exakt gepinnt; daraus folgt keine vollständige Festlegung aller transitiven Pakete.
- [DEVELOPER_HANDOVER.md](../DEVELOPER_HANDOVER.md) nennt Python 3.12 als Image-/CI-Basis, PostgreSQL 16 und Redis 7. Die dokumentierten 1.319 erfolgreichen Django-Tests beziehen sich auf den bisherigen Stand und ersetzen keinen neuen Prüflauf.
- [CI](../.github/workflows/ci.yml) enthält bereits vollständige Django-/JavaScript-Tests, Deployment- und Migrationschecks, Setup-/Redis-Nachweise sowie einen isolierten Container-Smoke. Ein Dependency-Audit ist dort bisher nicht enthalten.
- [Dockerfile](../Dockerfile) installiert aus `requirements.txt`. Web-, Mail-, Clan- und optionaler Backup-Worker werden aus demselben Quellstand gebaut; ihre tatsächlich eingesetzten Versionen müssen nachgewiesen werden.
- [scripts/container_smoke.py](../scripts/container_smoke.py) erstellt eine isolierte Kopie mit eigenen Schlüsseln, Volumes und Ports und prüft sieben Dienste einschließlich Backup-Worker. Das ist der vorgesehene Weg für die Containerprüfung.

Der im Pre-Release-Befund dokumentierte WSGI-Aufrufpfad wird bei der Umsetzung erneut gegen das tatsächlich installierte Paket geprüft. In dieser Planung wurden weder ein DoS-Versuch noch ein neuer Test-/Auditlauf ausgeführt.

## Arbeitspakete in Umsetzungsreihenfolge

### 1. Ausgangsstand und Prüfumgebung festhalten

**Verantwortung: Entwicklung.** Commit und lokale Änderungen aufnehmen; vorhandene Änderungen erhalten. Eine frische Python-3.12-Umgebung mit eigener PostgreSQL-16-Testdatenbank, Redis 7 und passenden nativen PostgreSQL-Tools bereitstellen. Bestehende Anwendungsdaten und die lokale Betriebs-`.env` nicht für Smoke-Tests verwenden.

Python-, Django- und Paketversionen sowie den bisherigen Imagebezug dokumentieren. Vorhandene Prüfnachweise als Baseline verwenden; bei neuen Fehlern den betroffenen Test auf dem Ausgangsstand gezielt gegenprüfen. Für einen späteren Betriebsrollout Sicherung und Wiederanlauf nach [updating.md](updating.md) vorbereiten.

**Ergebnis:** Reproduzierbarer Ausgangsstand und getrennte Testressourcen.

### 2. Patch aktualisieren und Kompatibilität sichten

**Verantwortung: Entwicklung.** Den Django-Pin in `requirements.txt` auf den bestätigten Zielpatch setzen. In der frischen Umgebung installieren und mit `python -m pip check` die aufgelösten Abhängigkeiten prüfen. Drittanbieterintegrationen wie django-tinymce berücksichtigen. Weitere Paketänderungen nur bei belegter Notwendigkeit aufnehmen und begründen.

Alle Sicherheits- und Kompatibilitätshinweise aus 6.0.8 und 6.0.9 abgleichen, insbesondere Headerparser, Admin-URL-Darstellung, Sprachcodeverarbeitung, GeoDjango und Model-/Inlineformsets mit bearbeitbaren Primärschlüsseln. Die erste Quelltextsuche fand keine GeoDjango-Verwendung; die UUID des Wiki-Anhangs ist `editable=False`. Das ist ein Ausgangspunkt für die Prüfung, keine pauschale Entwarnung für sämtliche Formsets oder Drittanbieterpfade.

Keine Fachmigration ist durch den geplanten Pinwechsel vorgesehen. `makemigrations --check --dry-run` und die Migrationen auf einer frischen Testdatenbank müssen das bestätigen. Keinen eigenen Django-Parserpatch und keinen Monkeypatch einführen.

**Ergebnis:** Kleiner, nachvollziehbarer Dependency-Diff mit dokumentierter Kompatibilitätsprüfung.

### 3. Headerverarbeitung gezielt absichern

**Verantwortung: Entwicklung.** Regressionstests in einer neuen Datei `config/test_header_parsing.py` ergänzen und vorhandene Formular-/Uploadtests wiederverwenden:

- Den Konstruktor von `WSGIRequest` direkt mit `Content-Type` durchlaufen, damit eine Begrenzung durch Nginx oder Gunicorn den betroffenen Django-Pfad nicht verdeckt.
- Gültige Typ-/Charset-Parameter, zitierte Parameter mit Trennzeichen sowie ausgewählte fehlerhafte Header prüfen. Erwartetes Verhalten an der korrigierten Django-Version und den Anwendungsanforderungen ausrichten; kein historisches Fehlverhalten festschreiben.
- `Accept`-Verarbeitung über die dafür vorgesehene Django-Request-API prüfen. Wiederholte Header zusätzlich im isolierten HTTP-Pfad berücksichtigen, weil ein WSGI-Dictionary deren Übertragung und Zusammenführung nicht vollständig abbildet.
- Formular-POSTs und Multipart-Uploads einschließlich geschützter Wiki-Anhänge auf korrekte Daten-/Dateiverarbeitung und unveränderte Zugriffskontrollen prüfen.

Für den sicherheitsbezogenen Parserfall eine begrenzte synthetische Eingabe und einen abbrechbaren Unterprozess mit großzügigem Timeout verwenden. Keine Lastattacke, keine unbeschränkten Payloads und keine empfindlichen Millisekunden-Grenzwerte in CI. Ein solcher Test ist ein Regressionssignal; der Nachweis der Sicherheitskorrektur stützt sich zusätzlich auf Herstellerhinweis und installierten Paketstand.

**Ergebnis:** Reproduzierbare Prüfungen des erreichbaren WSGI-Pfads und der relevanten Anfrageformate.

### 4. Gesamte Prüfung und Dependency-Audit wiederholen

**Verantwortung: Entwicklung und Review.** In der isolierten Primärumgebung ausführen:

```bash
python -m pip check
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput
node --test scripts/tests/*.test.cjs
```

`python manage.py check --deploy` zusätzlich mit produktionsnaher Konfiguration ausführen. Warnungen samt Begründung erfassen; bekannte CI-Testeinstellungen wie deaktivierte HTTPS-Weiterleitung sind kein ausreichender Produktionsnachweis. Neue Fehler oder ungeklärte Sicherheitswarnungen verhindern die Abnahme.

Einen aktuellen Dependency-Audit über **alle tatsächlich installierten Anwendungspakete einschließlich transitiver Abhängigkeiten** erstellen. Dafür das Paketinventar der frischen Umgebung und des gebauten Images erfassen und mit einem separat betriebenen, versioniert dokumentierten Auditwerkzeug prüfen. Beispiel: `pip freeze` aus dem Zielimage exportieren und dieses Inventar mit `pip-audit --requirement … --format json --output …` prüfen. Das Werkzeug gehört nicht in die Produktionsanforderungen. Auditdatum, Datenquelle, Toolversion, Exitstatus und Rohbefunde speichern; ein fehlgeschlagener Abruf gilt nicht als sauberer Audit.

Befunde nach Paket und CVE zusammenführen, alternative Advisory-IDs als Aliase erhalten. Originalmeldungen bleiben nachvollziehbar. Zusätzlich die offiziellen Django-Sicherheitshinweise abgleichen, auch wenn der Scanner CVE-2026-84429 noch nicht führt.

Für verbleibende Befunde eine Bewertung mit installiertem Stand, betroffener Funktion, Projektverwendung, Erreichbarkeit, Maßnahme und zuständiger Rolle erstellen. Die GeoDjango-Meldungen und der python-dotenv-Befund werden erneut geprüft. `set_key()`/`unset_key()` einschließlich Hilfsskripten sichten; fehlende Aufrufe begründen eine projektspezifische Einordnung, beseitigen aber die gemeldete Paketlücke nicht. Ein erforderliches dotenv-Update ist ein separat begründeter Folgeschritt. Keine pauschalen CVE-Ausnahmen oder stillen Unterdrückungen.

In `.github/workflows/ci.yml` den Audit samt Artefaktablage ergänzen. Unbewertete Findings und technische Auditfehler lassen den Prüfschritt fehlschlagen. Falls eine befristete Ausnahme fachlich beschlossen wird, muss sie eng begrenzt mit Begründung, Verantwortlichem und Wiederprüfanlass dokumentiert sein. Der konkrete Django-Zielstand wird zusätzlich geprüft, damit fehlende Scannerabdeckung den Blocker nicht verdeckt.

**Ergebnis:** Neue Testergebnisse, vollständiges Paketinventar und bewerteter Audit; alte Prüfzahlen bleiben als historische Nachweise erhalten.

### 5. Image bauen und isolierten Container-Smoke abnehmen

**Verantwortung: Entwicklung.** Den vorhandenen Smoke erweitern: erwarteten Django-Patch explizit mit der installierten Version vergleichen, Image-ID und Paketinventar erfassen, `pip check` und Deploymentcheck im Image ausführen und die Version in `web`, `email_worker`, `clan_seat_worker` und `backup_worker` bestätigen. Dann den vollständigen bestehenden Ablauf starten:

```bash
python scripts/container_smoke.py --output-dir /tmp/entails-b1-evidence --performance
```

Frisches Setup, Migrationen, Seeds, Demowiederholung, echter Redis, HTTPS-Seiten, Assets, alle Worker und vorhandene HTTP-Szenarien müssen erfolgreich bleiben. Kleine Header-Stichproben über Nginx/Gunicorn ergänzen; erwartete Proxyablehnungen von erfolgreicher Django-Verarbeitung unterscheiden. Die vorhandenen Lastszenarien werden als Regression wiederholt und sind kein Header-DoS-Test.

**Ergebnis:** Nachweis, dass das neu gebaute Image den Zielpatch enthält und im gesamten vorgesehenen Stack funktioniert. Ein vorhandenes altes Image oder ein erfolgreicher lokaler Import allein reicht nicht.

### 6. Dokumentieren und Betriebsrollout abschließen

**Verantwortung: Entwicklung für Releaseunterlagen; Betrieb für Zielsystem und Freigabe.** Nach erfolgreicher Prüfung die Versionsangabe in `DEVELOPER_HANDOVER.md` aktualisieren und einen neuen datierten B1-Nachweis unter `docs/verification/` ablegen. Verweise in `docs/remediation-progress.md` ergänzen; historische Ergebnisse nicht umetikettieren. Nachweis enthält Commit/Änderungsstand, Befehle, Laufzeitversionen, Image-ID, Ergebnisse, Auditbewertung und Grenzen; keine Geheimnisse oder personenbezogenen Betriebsdaten.

Im Zielsystem das geprüfte Image für Web und alle aktivierten Worker zusammen ausrollen; verwendete Compose-Profile erhalten. Anschließend Versionen/Imagebezug, Dienstzustände, Logs, `/api/health/`, Login, Formular-/Uploadstichprobe und folgenden Laufzeitcheck prüfen:

```bash
docker compose exec -T web python manage.py check_runtime --health-host 127.0.0.1 --require-redis
docker compose exec -T web python manage.py check --deploy
```

Externe Erreichbarkeit für den tatsächlich genutzten VPS-/Tunnelweg separat nachweisen. Rolloutbefehle und Wiederanlauf richten sich nach `docs/updating.md`. Bei Fehlern Schreibzugriffe und Worker bei Bedarf kontrolliert pausieren, Zustand sichern und eine korrigierte Version bereitstellen. Eine Rückkehr zu 6.0.7 öffnet die bekannte Lücke erneut und darf keine öffentlich freigegebene Dauerlösung sein. Falls vorübergehend unvermeidbar, betroffene öffentliche Erreichbarkeit unterbinden. Datenwiederherstellung nur bei tatsächlichem Bedarf nach geprüftem Verfahren; keine Volumes löschen und keine Migrationen blind zurücksetzen.

**Ergebnis:** Technische Releaseabnahme und gesonderter Betriebsnachweis für das ausgerollte Artefakt.

## Abnahmekriterien für B1

1. Der exakte, offiziell korrigierte 6.0.x-Patch ist gepinnt und in frischer Umgebung, gebautem Image und allen eingesetzten Anwendungsdiensten nachgewiesen.
2. Header-/WSGI-Regressionen, vollständige Django-/JavaScript-Suite, Dependency-Konsistenz und Migrationscheck sind erfolgreich. Testanzahl, Fehler und eventuelle Überspringungen sind ausgewiesen und erklärt.
3. Deploymentcheck und vollständiger isolierter Container-Smoke sind erfolgreich; verbleibende Warnungen sind nachvollziehbar bewertet.
4. Ein aktueller Audit erfasst den tatsächlichen Paketbestand. Herstellerhinweise sind separat abgeglichen. CVE-2026-84429 ist durch den korrigierten Paketstand behoben; weitere Befunde sind behoben oder ausdrücklich bewertet und entschieden.
5. Die Dokumentation enthält neue, zu diesem Artefakt gehörende Nachweise. Die technische Releasefreigabe erfolgt erst nach 1–4; B1 wird für eine konkrete Installation erst nach nachgewiesenem Rollout geschlossen.

Geplante Änderungsdateien: `requirements.txt`, `config/test_header_parsing.py`, bei Bedarf bestehende Formular-/Uploadtests, `.github/workflows/ci.yml`, `scripts/container_smoke.py`, `DEVELOPER_HANDOVER.md` sowie B1-Nachweis und Verweise unter `docs/`. Fachliche Erweiterungen, ein Django-Reihenwechsel und allgemeine Paketmodernisierung sind separate Aufgaben.
