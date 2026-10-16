# Leistungs- und Darstellungsnachweise

## Aussagegrenzen

50 bis 1.000+ registrierte Gäste sind eine Zielgröße, keine Zusage für 1.000 gleichzeitige Zugriffe. „Hochperformant“, umfassende WCAG-Konformität oder pauschale mobile Fehlerfreiheit werden ohne passenden aktuellen Nachweis nicht zugesichert. Das bisherige Testclient-Skript misst Anwendungslogik; das neue HTTP-Skript umfasst zusätzlich Nginx und Gunicorn.

## Leistung

Auf einer Wegwerf-Datenbank `entails_smoke_*` und dem lokalen Testproxy:

```bash
ENTAILS_PERF_TEST=1 python scripts/http_performance_smoke.py --base-url http://nginx:8080
```

Dies ist für die isolierte Containerumgebung gedacht; die Datenbank und die vom Proxy angesprochenen Webprozesse müssen dieselbe Wegwerf-DB verwenden. Das Skript erstellt synthetische Daten, aktiviert Testevents und verwendet Test-Sessions; niemals gegen eine echte Installation ausführen. `scripts/container_smoke.py --output-dir /tmp/entails-smoke-evidence --performance` richtet dafür die isolierte Kopie ein und räumt deren Ressourcen auf.

Die Matrix umfasst 50/250/1000 vorhandene Anmeldungen, jeweils 1/12/32 parallele Requests und standardmäßig 32 Messungen je Szenario: neue Anmeldung, konkurrierende Buchung desselben bezahlten Sitzes und Check-in. Für Sitzplatzkonkurrenz wird genau ein Erfolg erwartet; die übrigen fachlichen Ablehnungen sind keine Serverfehler. Erfasst werden p50/p95/p99, Statusverteilung, fachliche Ergebnisprüfung und maximale beobachtete Zahl wartender PG-Verbindungen. Keine Rate-Limits werden für den Test abgeschaltet; Check-in verwendet die vorhandene Staff-Aktion statt den auf 60 QR-Scans begrenzten Scannerpfad.

Das JSON enthält Softwarefingerabdruck, Python/Django/PostgreSQL, Webworkerzahl, Architektur und sichtbare CPU-Anzahl. Für einen Hardwarevergleich zusätzlich Host, RAM, CPU-Quota, Datenträger und Laufbedingungen protokollieren. Eine erste Baseline hat keine verbindliche Latenzschwelle; Produkt/Betrieb müssen daraus tolerierte Wartezeiten und einen späteren Regressionstoleranzbereich beschließen. Ein erfolgreicher Lauf beweist die geprüften Szenarien, keine allgemeine Kapazitätsgarantie.

## Darstellung und Zugänglichkeit

Prüfumgebung: getrennte Vorschau mit synthetischen Daten und eigener Adminanmeldung. Seiten: Registrierung/Login, Dashboard, Sitzplan, Turnierdetail und Kontaktformular (für Kontakt zusätzlich Testkonfiguration/Kategorie aktivieren). Alle neun Themes bei 1440, 390 und 320 Pixeln prüfen. Die neun Theme-Presets stammen aus `configuration/themes.py`.

| Prüfung | Erwartung / Nachweis |
| --- | --- |
| Seitenbreite | Kein unbeabsichtigter Seitenüberlauf; große Sitz-/Turnieransichten besitzen ihre vorgesehene lokale Navigation. Screenshot und Viewport festhalten. |
| Tastatur | Formulare, Navigation und Bestätigungen ohne Maus erreichbar; Reihenfolge nachvollziehbar, Fokus sichtbar und nicht verdeckt; keine Fokusfalle. Manuelles Protokoll. |
| Formulare | Labels zugeordnet, Fehler verständlich und den Feldern zugeordnet; Statusmeldungen auch ohne Farbe wahrnehmbar. Automatische Markupprüfung plus Tastatur-/Screenreader-Stichprobe. |
| Kontrast | Tatsächlich gerenderte Text-/Hintergrundkombinationen und Fokus-/Statusdarstellung prüfen; CSS-Tokenpaare allein sind kein vollständiger Nachweis. Findings je Theme dokumentieren. |
| Bewegung/Zoom | Reduzierte Bewegung respektiert; Zoom und Textvergrößerung verdecken keine notwendigen Aktionen. Manuell prüfen. |
| Richtige Aussage | Einzelne grüne Tests und Screenshots werden nicht als umfassende WCAG-Zertifizierung bezeichnet. |

Protokoll je Lauf: Commit und Dirty-Status, Software-/Browserversionen, Theme, Viewport, geprüfte Seite/Aktion, Ergebnis und Artefaktpfad. Nicht ausgeführte Kombinationen bleiben ausdrücklich offen. CI-Tests unter `scripts/tests/` prüfen JavaScript-Verhalten mit Testdoubles; sie ersetzen diesen Browser-/Screenreader-Nachweis nicht. Der menschliche Ersteinstieg und die manuelle Screenreader-Abnahme bleiben eigenständige QA-Aufgaben.
