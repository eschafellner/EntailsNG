# Gesamtübersicht der Verifikation (Stufe 2)

**Aktuelle Umsetzung (11. Oktober 2026):** [Gesamtübersicht](_summary.md) und [Modulfortschritt](_progress.md). USERS-03 ist auf Wunsch des Nutzers vorerst zurückgestellt. Die folgenden Abschnitte dokumentieren die historische Verifikation.

Verifiziert am **9. Oktober 2026**, Checkout `9a39f769af58d9e841a89901921d95c79e521711`.

**31 Original-Findings: 29 BESTÄTIGT / 2 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR.**

Zuerst wurden sämtliche Dateien in `review/` gelesen und die Bereiche inventarisiert. Anschließend wurden die 15 Findings-Dateien in der untenstehenden Reihenfolge einzeln abgeschlossen. Jedes Finding enthält unmittelbar darunter einen Verifikationsblock mit Urteil, Begründung, Gegenmaßnahmen, konkreten Belegstellen und Schweregrad. Die Original-Findings und die ursprüngliche Übersicht sind erhalten.

| Modul / Bereich | Bestätigt | Teilweise abgesichert | False Positive | Nicht entscheidbar | Bericht |
| --- | ---: | ---: | ---: | ---: | --- |
| Projekt / config / Deployment | 4 | 0 | 0 | 0 | [_project-findings.md](_project-findings.md) |
| users | 4 | 0 | 0 | 0 | [users-findings.md](users-findings.md) |
| events | 4 | 0 | 0 | 0 | [events-findings.md](events-findings.md) |
| configuration | 2 | 1 | 0 | 0 | [configuration-findings.md](configuration-findings.md) |
| contact | 0 | 0 | 0 | 0 | [contact-findings.md](contact-findings.md) |
| seating | 2 | 0 | 0 | 0 | [seating-findings.md](seating-findings.md) |
| info | 1 | 0 | 0 | 0 | [info-findings.md](info-findings.md) |
| knowledge | 0 | 0 | 0 | 0 | [knowledge-findings.md](knowledge-findings.md) |
| news | 1 | 0 | 0 | 0 | [news-findings.md](news-findings.md) |
| clans | 3 | 0 | 0 | 0 | [clans-findings.md](clans-findings.md) |
| emails | 1 | 1 | 0 | 0 | [emails-findings.md](emails-findings.md) |
| tournaments | 4 | 0 | 0 | 0 | [tournaments-findings.md](tournaments-findings.md) |
| media_designer | 1 | 0 | 0 | 0 | [media_designer-findings.md](media_designer-findings.md) |
| sponsors | 1 | 0 | 0 | 0 | [sponsors-findings.md](sponsors-findings.md) |
| backups | 1 | 0 | 0 | 0 | [backups-findings.md](backups-findings.md) |
| **Gesamt** | **29** | **2** | **0** | **0** | **15 Findings-Dateien** |

Nach Verifikation verbleibende Schweregrade der 31 Original-Findings: **Kritisch 0 / Hoch 5 / Mittel 19 / Niedrig 7 / Info 0**. Die zusätzlichen Beobachtungen sind darin nicht mitgezählt. `contact` und `knowledge` enthielten keine Original-Findings; die Nullwerte sind keine Aussage vollständiger Fehlerfreiheit.

## Wesentliche Präzisierungen

- **CONFIGURATION-02 — teilweise abgesichert:** Der Clan-Konfigurations-Admin erzeugt und sperrt den Singleton vor der schreibenden Add-Prüfung. Dieser konkrete Teil des Originalbefunds ist entkräftet. Bei `GeneralConfiguration` und `SiteCustomization` fehlen weiterhin Add-Permission-Prüfungen, solange der jeweilige Datensatz fehlt. Für den verbleibenden Bankdatenpfad bleibt **Hoch** bestehen. [Belege](configuration-findings.md).
- **EMAILS-02 — teilweise abgesichert, Mittel → Niedrig:** Ein gültiger Eventtitel hat höchstens **100**, nicht 200 Zeichen. Die Standardvorlage erzeugt selbst mit maximalen Werten nur **168** Zeichen und überschreitet die Outbox-Grenze nicht. Angepasste Vorlagen können einen gültigen Platzhalter jedoch mehrfach expandieren; eine zulässige Vorlage mit drei Eventtitel-Platzhaltern erzeugt **300** Zeichen für die 255-Zeichen-Spalte. Deshalb bleibt eine enger begrenzte Restlücke. [Belege](emails-findings.md).
- **Kein vollständiges Finding als False Positive:** Andere untersuchte Schutzmechanismen begrenzen vielfach Rolle, Erreichbarkeit oder Auswirkungen, schließen den jeweils beschriebenen verbleibenden Pfad aber nicht. Bei bereits ausdrücklich bedingten Befunden bleiben die Voraussetzungen Teil des Urteils, etwa delegierte Staff-Rechte, fehlende Singletons oder Prozessabbruch mit anschließendem Cleanup-Fehler.

## Zusätzliche Beobachtungen

Zwei neue eigenständige Beobachtungen stehen jeweils am Ende ihres Modulberichts; sie verändern die Zählung der 31 Original-Findings nicht:

- **Projekt, Niedrig:** Der dokumentierte Tunnel-Start aktiviert das erforderliche Compose-Profil `tunnel` nicht. [Zusätzliche Beobachtung](_project-findings.md).
- **emails, Mittel:** Die Stale-Recovery prüft beim späteren UPDATE nicht erneut, ob Lease und Workerbesitz noch zu ihrem alten Kandidatensnapshot passen. Dadurch kann ein paralleler Recovery-Lauf eine inzwischen frisch vergebene PROCESSING-Lease zurücksetzen. [Zusätzliche Beobachtung](emails-findings.md).

## Nachweise und Prüfgrenzen

Die Prüfung verfolgt die konkret betroffenen URL-/Admin-/Worker-Pfade über Middleware, Decorators, Formulare, Model-/Service-Prüfungen und Ausgabe. Gegenpfade, Model-/Datenbankgrenzen, CSRF, Escaping, Hashing, Berechtigungen und Transaktionen wurden gezielt berücksichtigt. Ausgewählte Fehler wurden mit unveränderten Originalhelfern, isolierten Formularen oder Templates und gemockten Abhängigkeiten erneut nachvollzogen. Keine neuen Tests oder Änderungen am Anwendungscode wurden angelegt.

Ein vollständiger Anwendungs-/Admin-Integrationstest war mit der vorhandenen Prüfumgebung nicht möglich: `django-tinymce` ist lokal nicht installiert. Die dort verfügbaren Django-6-Prüfungen liefen mit **6.0.9**, während `requirements.txt` **6.0.7** pinnt. Das relevante Admin-Aktionsverhalten wurde zusätzlich am offiziellen 6.0.7-Quellcode abgeglichen. TinyMCE-HTMLField-Verhalten wurde anhand der offiziellen Dokumentation und des Upstream-master-Quelltexts beurteilt; der versionsgenaue 5.0.0-Quelltext war über den Recherchezugang nicht abrufbar. Diese Grenze ist in INFO-01 und SPONSORS-01 offengelegt. Es erfolgten keine echten SMTP-Vorgänge, Last-/Race-Tests oder PostgreSQL-Backups/Restores; statisch geprüfte Race-Szenarien sind entsprechend gekennzeichnet.

Produktions-Firewall, externe Zertifikatserneuerung und tatsächlich delegierte Gruppen-/Staffrechte sind aus dem Repository nicht bestimmbar. Die zugehörigen Findings bewerten die ausdrücklich genannten Bedingungen im vorliegenden Code, ohne diese Betriebszustände als nachgewiesen zu behandeln.

Abschlusskontrolle: Zu allen **31** Original-IDs existiert genau ein Verifikationsblock; Zählungen und zitierte Dateipfade/Zeilen wurden geprüft. Der SHA-256-Abgleich aller **603** bei Prüfungsbeginn erfassten versionierten Dateien zeigte **keine Änderung**. Die bereits vor Beginn vorhandene Änderung an `.gitignore` wurde nicht angefasst. Alle in diesem Auftrag geschriebenen Dateien liegen ausschließlich in `review/`.

---

## Ursprüngliche Übersicht (Stufe 1, unverändert)

Zusammenfassung: 31 Findings — Kritisch: 0, Hoch: 5, Mittel: 20, Niedrig: 6, Info: 0.

Security-/Backend-Review EntailsNG, Stufe 1, 9. Oktober 2026. Geprüfter Checkout: `9a39f769af58d9e841a89901921d95c79e521711`. Alle 14 eigenen Django-Apps wurden in der folgenden Reihenfolge einzeln abgeschlossen. Anwendungscode und laufende Dienste wurden nicht verändert; sämtliche erzeugten Dateien liegen in `review/`.

| Geprüfter Bereich | Kritisch | Hoch | Mittel | Niedrig | Info | Findings-Datei |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Projekt / config / Deployment | 0 | 0 | 4 | 0 | 0 | [_project-findings.md](_project-findings.md) |
| users | 0 | 1 | 2 | 1 | 0 | [users-findings.md](users-findings.md) |
| events | 0 | 0 | 3 | 1 | 0 | [events-findings.md](events-findings.md) |
| configuration | 0 | 1 | 2 | 0 | 0 | [configuration-findings.md](configuration-findings.md) |
| contact | 0 | 0 | 0 | 0 | 0 | [contact-findings.md](contact-findings.md) |
| seating | 0 | 0 | 1 | 1 | 0 | [seating-findings.md](seating-findings.md) |
| info | 0 | 1 | 0 | 0 | 0 | [info-findings.md](info-findings.md) |
| knowledge | 0 | 0 | 0 | 0 | 0 | [knowledge-findings.md](knowledge-findings.md) |
| news | 0 | 1 | 0 | 0 | 0 | [news-findings.md](news-findings.md) |
| clans | 0 | 0 | 2 | 1 | 0 | [clans-findings.md](clans-findings.md) |
| emails | 0 | 0 | 2 | 0 | 0 | [emails-findings.md](emails-findings.md) |
| tournaments | 0 | 0 | 3 | 1 | 0 | [tournaments-findings.md](tournaments-findings.md) |
| media_designer | 0 | 0 | 0 | 1 | 0 | [media_designer-findings.md](media_designer-findings.md) |
| sponsors | 0 | 1 | 0 | 0 | 0 | [sponsors-findings.md](sponsors-findings.md) |
| backups | 0 | 0 | 1 | 0 | 0 | [backups-findings.md](backups-findings.md) |
| Gesamt | 0 | 5 | 20 | 6 | 0 | 15 Findings-Dateien |

Weitere installierte Apps laut `config/settings.py:69`: `django.contrib.admin`, `django.contrib.auth`, `django.contrib.contenttypes`, `django.contrib.sessions`, `django.contrib.messages`, `django.contrib.staticfiles` und `tinymce`. Ihre Integration und relevante Framework-Schutzmechanismen wurden berücksichtigt. Ein vollständiger Audit des externen Paketquellcodes oder Abgleich gegen aktuelle CVE-Datenbanken war nicht Teil dieser Prüfung. `config` ist das Projektpaket.

Die hohen Befunde betreffen delegierte Benutzerverwaltung (USERS-03), fehlende Add-Permissions bei Konfigurations-Singletons (CONFIGURATION-02) und persistentes XSS in Info-, News- und Sponsor-Inhalten. Die jeweilige Voraussetzung einer delegierten Berechtigung bzw. eines noch fehlenden Singletons steht im Finding. CONFIGURATION-01 und INFO-01 teilen dieselbe Sanitizer-Ursache; PROJECT-04 fasst das Muster fehlender Admin-Aktionsberechtigungen appübergreifend zusammen. Die Anzahl zählt dokumentierte Findings, einschließlich solcher Zusammenhänge.

Die Prüfung basiert auf Codeanalyse und ausgewählten isolierten Nachweisen ohne Datenbankänderungen: Sanitizer-Payloads, Kurzfarben, Clan-Passwortbehandlung, gerenderte Betrefflänge, öffentliche Einladungscode-Ausgabe, Integer-/JSON-Typfehler, Django-Admin-Aktionsfilter und Backup-Recovery mit gemockten Abhängigkeiten. Eine vollständige Testsuite, Lasttests, tatsächliche SMTP-Vorgänge sowie echte PostgreSQL-Backups/Restores wurden nicht ausgeführt. Format, Schweregradzählungen, eindeutige IDs und Existenz der genannten Dateien/Zeilen wurden abschließend geprüft.

Für Stufe 2 sind insbesondere delegierte Produktionsrechte bei USERS-03/PROJECT-04, die Singleton-Voraussetzung von CONFIGURATION-02, das bedingte Recovery-Szenario BACKUPS-01 und die statisch nachvollzogenen Race Conditions zu prüfen. Alle Findings enthalten Auswirkung, kurzen Codeauszug, Empfehlung und Konfidenz. In `contact` und `knowledge` wurden keine nachvollziehbaren Findings festgestellt.

Erzeugte Dateien: die 15 oben verlinkten Findings-Dateien und diese Übersicht (`review/README.md`), insgesamt 16 Markdown-Dateien.
