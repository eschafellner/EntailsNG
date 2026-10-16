# Entwicklungsbacklog

Stand: 16. Oktober 2026. Technische Fehler und optionale Funktionen werden getrennt geführt. Verantwortlich sind zunächst Rollen; konkrete Personen und Produktprioritäten sind offen, bis das Projektteam sie festlegt.

| ID | Typ / Status | Nutzende und Problem | Abnahme | Priorität / Rolle / Abhängigkeit |
| --- | --- | --- | --- | --- |
| OPS-01 | Betrieb / Zielnachweis offen | Betrieb braucht verlässlichen Tunnel-/TLS-Zugriff. | Reales Origin HTTP nginx:8080 bzw. ACME-Erneuerung und Nginx-Reload in Zielumgebung protokolliert. | Hoch; Betrieb; Zugriff auf Zielumgebung. |
| DEP-01 | Wartung / offen | Django 6.0 erhält laut Hersteller nur bis April 2027 Sicherheitskorrekturen. | Vor Supportende auf eine dann unterstützte Reihe mit aktuellem Patch wechseln; Herstellerhinweise, Kompatibilität, Suite, Audit und Container-Smoke prüfen. | Hoch, vor April 2027 einplanen; Entwicklung/Betrieb; gesondertes Upgradepaket. |
| USERS-03 | Sicherheit / zurückgestellt | Delegierte Benutzerverwaltung besitzt weitreichende Rechte. | Bestehende Entscheidung und private Rechteübersicht nach `security-backlog.md`. | Mittel; Sicherheits-/Betriebsverantwortung; keine automatische Rechteänderung. |
| QA-01 | Nachweis / Kriterien festgelegt, manuelle Abnahme offen | Entwicklung braucht aktuelle Darstellungs-/Zugänglichkeitsnachweise. | Prüfmatrix und manuelle Protokolle nach `quality-verification.md`. | Niedrig; Entwicklung/QA; getrennte Vorschau. |
| PERF-01 | Nachweis / Messwerkzeug vorhanden | Betrieb braucht konkrete Lastgrenzen. | Reproduzierbare HTTP-Baseline für 50/250/1000 Gäste und 1/12/32 parallele Requests; danach Grenzwerte beschließen. | Niedrig; Entwicklung/Betrieb; isolierte Laufumgebung. |
| FEATURE-01 | Idee / offen | Turniergäste sehen fremde Ergebnisse erst nach Aktualisierung. | Turnieransicht aktualisiert neue freigegebene Ergebnisse selbstständig; Rechte bleiben erhalten; Mobil-/Offlineverhalten definiert. | Produktpriorität offen; Produkt/Entwicklung; Polling/WebSocket-Entscheidung offen. |
| FEATURE-02 | Idee / offen | Orga benötigt einen Turnierbaum außerhalb der Website. | Gewünschtes Format PDF und/oder JSON fachlich festlegen, vollständig ausgegebene Paarungen/Ergebnisse für die unterstützten Modi prüfen. Urkundenexport zählt nicht als Bracketexport. | Produktpriorität offen; Produkt/Entwicklung; Formatentscheidung. |
| FEATURE-03 | Teilweise vorhanden | Scanner zeigt Zahlen und Prozent; Orga wünscht eventuell eigenes Dashboard und Stoßzeiten. | Vorhandene Scanneranzeige erhalten; zusätzlich Zeitraum, Aggregation, Berechtigung und Aktualisierungsintervall für Widget/Auswertung festlegen. | Produktpriorität offen; Produkt/Entwicklung; Statistikdefinition. |
| FEATURE-04 | Idee / offen | Orga benötigt einen gedruckten Sitzplan. | A3/A4-PDF mit lesbaren Sitzlabels/Namen, Seitenaufteilung und festgelegter Zugriffsberechtigung. | Produktpriorität offen; Produkt/Entwicklung; Drucklayout. |
| FEATURE-05 | Idee / offen | Clans wünschen turnierübergreifende Wertung. | Wertungsregeln und Gleichstände je Modus festlegen; beendete/bestätigte Turniere aggregieren; Korrektur-/Absageverhalten definieren. | Produktpriorität offen; Produkt/Entwicklung; Punktesystem. |

Abgeschlossene technische Änderungen und ihr Nachweis stehen in `remediation-progress.md`; historische Funktionsprüfungen in den jeweiligen Fachberichten. Neue Ideen werden nicht allein aus dem Audit als beauftragte Funktionen behandelt.
