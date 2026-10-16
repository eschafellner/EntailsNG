# Umsetzung und Nachweise P1–P6

Stand: 15. Oktober 2026. Ausgangspunkt: Commit `97026fd` auf `main` mit bereits vorhandenen lokalen Änderungen am Clan-Websiteformular, dessen Tests und der Sitzplanlegende. Diese Benutzeränderungen bleiben erhalten. Die nachfolgenden Änderungen sind uncommittiert; es wurde kein Produktionsdeployment ausgeführt.

| Paket | Technischer Stand | Verbleibende externe/fachliche Abnahme |
| --- | --- | --- |
| P1 Demo | Gemeinsamer atomarer Generator, Migration 0025, geschützte Wiederholung, unbrauchbare Gastpasswörter, gemeinsame CLI-/Installer-/Containerpfade und nicht löschende Adminaktion implementiert. | Keine produktiven Daten mit dem historischen Snapshot importieren. |
| P2 Deployment | Healthcheck-Vorgabe korrigiert; `check_runtime`, passende Versions-/Backup-/Cacheprüfungen und `updating.md` implementiert. Bestehende 0017 wird unverändert verwendet. | Tatsächlicher Tunnel-Origin und echte ACME-/SMTP-/Restoreprozesse in der Zielumgebung. |
| P3 CI | Frischer Setupweg, echter Redis-Prozessnachweis, isolierter Imagebau/Compose-Start und HTTP-Lastmessungen in CI integriert; qrcode und die zuvor variablen Betriebsimages festgelegt. | GitHub-Workflow nach Push ausführen; lokale Nachweise sind kein behaupteter GitHub-Run. |
| P4 Rechte | Ausschließlich lesender privater Rechtebericht und Sicherheitsbacklog implementiert; USERS-03 bleibt ausdrücklich zurückgestellt. | Produktionsbericht sowie verantwortliche Person/erneuter Termin durch Betreiberteam. |
| P5 Übergabe | Kurzer Einstieg, separate Env-Matrix, vollständiges historisches Archiv und aktuelle Betriebs-/Backlogverweise. | Menschlicher Ersteinstieg auf frischer Umgebung; automatisierter Durchlauf wird separat nachgewiesen. |
| P6 Qualität | HTTP-Messwerkzeug für tatsächliche Nginx-/Gunicornwege, Prüfkriterien und getrennter Funktionsbacklog. | Latenz-SLA/Produktprioritäten und manuelle Browser-/Screenreader-Abnahme; keine allgemeine WCAG-Zertifizierung behauptet. |

## Bereits ausgeführte Paketprüfungen

- 28 gezielte Django-Tests zu Demo, Runtime, Rechtebericht und bestehenden Konfigurationsfällen erfolgreich auf isoliertem PostgreSQL 18.6 mit Python 3.14.8/Django 6.0.7; enthalten echte parallele Demoinitialisierung und Transaktionsrollback.
- Alle fünf JavaScript-Testdateien erfolgreich; Shell-/Python-Syntax und Diff-Prüfung erfolgreich. Keine Anwendungsmigration gegen die vorhandene Anwendungsdatenbank ausgeführt.
- Tatsächlicher Imagebau und sieben laufende Dienste mit PostgreSQL 16.15, Python 3.12.15, Django 6.0.7, Redis 7, Nginx 1.27.5 und drei Gunicorn-Webworkern nachgewiesen. HTTPS-Seiten/Assets, frisches Setup mit zehn Seiten, Seed-/Demo-Wiederholung, nativer Backup-Tool-Abgleich und prozessübergreifender Redis-Nachweis erfolgreich. Certbot meldet 5.8.0, cloudflared 2026.10.0; nur deren Start/Version wurde geprüft, keine echte Ausstellung oder Tunnelverbindung.
- HTTP-Matrix: 50/250/1000 vorhandene Anmeldungen × 1/12/32 parallele Requests × drei Szenarien mit je 32 Requests = 864 HTTP-Messungen. Keine unerwarteten Fehler; jede Sitzplatzkonkurrenz hatte genau einen Gewinner und 31 erwartete Ablehnungen. Es handelt sich um eine lokale Baseline ohne beschlossene SLA.

## Abschließender Stand

**Abgeschlossen:** 1.319 Django-Tests in 267,541 Sekunden erfolgreich, keine Überspringungen (21 zusätzliche Tests gegenüber dem Audit). Alle fünf JavaScript-Testdateien, Actionlint, Shell-/Python-Syntax, Dokumentverweise und Diff-Prüfung erfolgreich.

Der abschließende Imagebau/Containerlauf einschließlich frischer Migrationen, zehn Setupseiten, unveränderter Seed-/Demowiederholung und der Probe „0017 rotiert genau einmal“ ist erfolgreich. Tatsächliche DB-/Redis-Ausfälle wurden über absichtlich falsche Testverbindungen erkannt. Alle sieben Dienste blieben laufend; vier HTTPS-/Assetpfade und 864 HTTP-Messungen bestanden. Native PG-Testinstanz und eigene Container-/Volume-/Image-Testressourcen wurden anschließend gestoppt bzw. entfernt.

Dauerhafte bereinigte Nachweise: [Zusammenfassung](verification/remediation-2026-10-15/summary.json), [frisches Setup/Migration](verification/remediation-2026-10-15/setup.json), [Container](verification/remediation-2026-10-15/container.json), [Ausfallerkennung](verification/remediation-2026-10-15/runtime-negative.json), [HTTP-Messwerte](verification/remediation-2026-10-15/http-performance.json). Rohlogs liegen außerhalb des Repository unter `/tmp/entails-remediation/`. Keine echten Benutzerlisten oder Secrets wurden in die Nachweise übernommen.

## Ergänzung vom 16. Oktober 2026: Sicherheitsupdate B1

Django 6.0.9, python-dotenv 1.2.4 und pip 26.2.1 für Image/CI umgesetzt; Header-/Dependency-Gates, Audit des tatsächlichen Paketbestands und Image-/Workerabgleich ergänzt. Die neue Gesamtsuite umfasst 1.335 Tests und ist erfolgreich (ein Node-Skip im Produktionsimage; derselbe JavaScript-Test separat auf dem Host erfolgreich). Alle fünf JavaScript-Testdateien, strikter Deploymentcheck und vollständiger isolierter Container-Smoke einschließlich 864 HTTP-Requests bestanden. Der vollständige Audit der 19 Imagepakete meldet keine Befunde. Ein bereits unter Django 6.0.7 vorhandener DST-Fehler in Testassertionen wurde korrigiert; keine Änderung der Zahlungslogik. [B1-Bericht und neue Nachweise](b1-django-security-update-results.md). Die obigen Ergebnisse vom 15. Oktober bleiben historische Nachweise; es wurde weiterhin kein Produktionsdeployment ausgeführt.

## Grenzen der ursprünglichen P1–P6-Prüfung

Der Containerlauf verwendet eine getrennte Quellkopie mit eigenen Schlüsseln, Projektnamen, Volumes und Loopbackports; die lokale Anwendungs-`.env` und ihre Daten werden nicht übernommen. Im ersten Container-Testaufbau verhinderten SELinux-Labels die Nginx-Bind-Mounts; das wurde ausschließlich für die temporäre Kopie durch Relabeling und private Zertifikatsvolumes korrigiert. Das ist kein als erfolgreich ausgegebenes Produktionsdeployment.

Historische Angaben im Audit und Archiv bleiben historische Befunde. Der aktuelle Einstieg verweist auf diese Umsetzungsnachweise. Kein Rollen-/Rechtewechsel wurde als Lösung für USERS-03 vorgenommen.
