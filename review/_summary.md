# Gesamtübersicht der Review-Umsetzung

Stand: 11. Oktober 2026.

Alle 15 Module wurden einzeln bearbeitet. Alle 31 Findings besitzen ein dokumentiertes Urteil: **29 bestätigt, 2 teilweise abgesichert, 0 False Positives, 0 nicht entscheidbar**. Für 30 Findings wurden technische Korrekturen umgesetzt. **USERS-03 ist bestätigt und bleibt auf ausdrücklichen Wunsch des Nutzers vorerst zurückgestellt.** „Erledigt“ in `_progress.md` bezeichnet gemäß Arbeitsablauf die abgeschlossene Prüfung und Bewertung sämtlicher Findings eines Moduls.

| Modulbericht | Bestätigt | Teilweise abgesichert | False Positive | Nicht entscheidbar |
| --- | ---: | ---: | ---: | ---: |
| [_project-findings.md](_project-findings.md) | 4 | 0 | 0 | 0 |
| [users-findings.md](users-findings.md) | 4 | 0 | 0 | 0 |
| [events-findings.md](events-findings.md) | 4 | 0 | 0 | 0 |
| [configuration-findings.md](configuration-findings.md) | 2 | 1 | 0 | 0 |
| [contact-findings.md](contact-findings.md) | 0 | 0 | 0 | 0 |
| [seating-findings.md](seating-findings.md) | 2 | 0 | 0 | 0 |
| [info-findings.md](info-findings.md) | 1 | 0 | 0 | 0 |
| [knowledge-findings.md](knowledge-findings.md) | 0 | 0 | 0 | 0 |
| [news-findings.md](news-findings.md) | 1 | 0 | 0 | 0 |
| [clans-findings.md](clans-findings.md) | 3 | 0 | 0 | 0 |
| [emails-findings.md](emails-findings.md) | 1 | 1 | 0 | 0 |
| [tournaments-findings.md](tournaments-findings.md) | 4 | 0 | 0 | 0 |
| [media_designer-findings.md](media_designer-findings.md) | 1 | 0 | 0 | 0 |
| [sponsors-findings.md](sponsors-findings.md) | 1 | 0 | 0 | 0 |
| [backups-findings.md](backups-findings.md) | 1 | 0 | 0 | 0 |
| **Gesamt** | **29** | **2** | **0** | **0** |

## Umgesetzte Änderungen

- Proxy-Vertrauensgrenzen, ACME-Bootstrap, Zertifikats-Reload und Berechtigungen mutierender Admin-Aktionen korrigiert.
- Aktivierungsanfragen liefern neutrale Antworten; erst ein geprüftes Passwort stellt die Verifikationssitzung wieder her. Inaktive Konten und parallele Reset-/Beitrittsanfragen werden begrenzt.
- Check-in nur über POST, korrekte Rückmeldung konkurrierender Scans, kontrollierte JSON-Fehler und Kapazitätsprüfung bei Admin-Reaktivierungen ergänzt.
- HTML-Sanitizer, Singleton-Berechtigungen und Farbberechnung korrigiert; Legal-, Info-, News- und Sponsor-Altinhalte werden auch bei der Ausgabe bereinigt.
- Unveränderte bezahlte Sitzplätze bleiben im Editor bearbeitbar; Sitzplan-JSON wird vor Zugriff und ORM geprüft.
- Clanpasswörter in Frontend und Admin explizit validiert und gehasht, Formulare nach Sperrerwerb neu gebunden und Passwortbeitritte begrenzt.
- E-Mail-Zustandswechsel und Recovery an Workerbesitz bzw. den gelesenen Ausgangszustand gebunden; Lease vor SMTP erneuert und Betreff vor Queue-Insert begrenzt.
- Teamcodes ausschließlich für Mitglieder ausgegeben, verlängert und durch Migration rotiert. Admin-Reaktivierung verwendet den bestehenden Assistenten; Rückzüge vor Playoff-Freigabe berechnen Qualifikanten neu. Zahlenparameter werden begrenzt validiert.
- Media-Designer behandelt falsche Datenquellentypen als Formularfehler.
- Bestätigte Backup-Recovery prüft den Live-Stand erneut und gibt die Website unabhängig von nachgelagerten Cleanup-Fehlern frei. Cleanup wird dauerhaft gespeichert und später wiederholt.

Kontakt und Wissensbasis enthielten keine Findings; die vorhandenen Schutzmechanismen wurden geprüft und die Regressionstests ausgeführt. Einzelbegründungen und Prüfpfade stehen in den Modulberichten. Historische Review-Texte wurden erhalten.

## Verifikation

- **1.293 Django-Tests erfolgreich**, einschließlich PostgreSQL-Concurrency und nativer Backup-/Restore-Prüfungen mit temporären Datenbankkopien.
- **13 gezielte Tests nach den letzten Anpassungen erfolgreich**: zusätzliche JSON-Grenzfälle, Teamcode-Vertraulichkeit, Reaktivierung, Playoff-Rückzug und responsive Teamansicht.
- **5 JavaScript-Testdateien erfolgreich** (`node --test scripts/tests/*.test.cjs`).
- Django-Systemcheck, `makemigrations --check --dry-run`, Shell-Syntax, Compose-Konfiguration und `git diff --check` erfolgreich. Keine fehlende Modellmigration.

Die Tests liefen auf einem eigens eingerichteten PostgreSQL-Cluster; Produktionsdaten wurden nicht verändert. ACME-Ausstellung und Nginx-Reload wurden über Shell-Regressionen mit Docker-Doubles geprüft; ein echtes öffentliches Zertifikat oder ein produktives Deployment wurde nicht ausgeführt. Die SMTP-Prüfungen verwendeten Test-/Mock-Backends. SMTP-Bestätigung und Datenbankzustand können weiterhin nicht in einer gemeinsamen Transaktion bestätigt werden; die entsprechenden Grenzen von EMAILS-01 sind dokumentiert.

## Zurückgestelltes Finding

**USERS-03:** Der Nutzer hat ausdrücklich entschieden, dieses Finding vorerst außen vor zu lassen. Die bestehenden Rechte der Benutzerverwaltung bleiben unverändert. Das Finding ist bewertet, aber nicht umgesetzt; es wird nicht als behoben ausgegeben.

## Deployment

- Neue Migration `tournaments/0017_rotate_exposed_invite_codes` anwenden. Sie ersetzt sämtliche bisherigen Teamcodes; bestehende Code-Einladungen verlieren ihre Gültigkeit. Die Rotation ist nicht rückwärts ausführbar.
- Nginx-/Certbot-Container mit der aktualisierten Compose-Konfiguration neu erstellen; neue Watcher-Datei und Deploy-Hook gehören gemeinsam zur Zertifikatserneuerung.
- Bei Cloudflare Tunnel den Origin gemäß README und INSTRUCTIONS auf `http://nginx:8080` einstellen; Port 8080 bleibt intern. Öffentliches HTTP/HTTPS vertraut keinen eingesandten Client-IP-Headern.
