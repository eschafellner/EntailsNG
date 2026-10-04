# 🚀 EntailsNG – Entwickler-Übergabe & Projektstatus (Developer Handover)

> **Stand:** Oktober 2026
> **Repository:** `entails-ng`  
> **Git-Branch:** Aktuellen Arbeitsstand mit `git status` prüfen
> **Test-Status:** Vollständiger Projektlauf am **1. Oktober 2026: 715 Tests, 695 erfolgreich, 20 PostgreSQL-Fälle auf SQLite übersprungen**, keine Fehler. Anschließend alle **38 Knowledge-Tests: 35 erfolgreich, 3 PostgreSQL-Fälle übersprungen**, einschließlich eines ergänzten Vergleichsfalls. Frühere Turnierprüfung: **12 JavaScript-Tests erfolgreich**. Details und Grenzen: [Interne Wissensbasis](docs/internal-knowledge-base.md), [Turnierprüfung](docs/tournament-audit-2026-10-01.md). Weitere Erweiterungen: [Solo-Reaktivierung](docs/solo-team-reactivation.md), [Schweizer Turniere](docs/swiss-tournaments.md). Der globale Migrationscheck meldet weiterhin die bereits dokumentierten Theme-Farbdefaults.
> **Python / Django:** Python 3.12+ (kompatibel mit 3.14) / Django 6.0  

> **Aktuelle Regression vom 3. Oktober 2026:** Vollständiger SQLite-Projektlauf:
> **822 Tests, 799 erfolgreich, 23 übersprungen**, keine Fehler. Backup-Modul
> zusätzlich nativ gegen PostgreSQL 16.15: **47 Tests, 45 erfolgreich, zwei
> übersprungen** (POSIX-Dateirechte unter Windows und SQLite-Dateiverbindungen).
> **12 JavaScript-Tests** und
> Syntaxprüfung des Backup-JavaScripts erfolgreich. Docker-Imagebau und CI wurden
> lokal nicht ausgeführt. Der bekannte globale Migrationscheck zu drei
> Theme-Farbdefaults besteht weiterhin; das Backup-Modul benötigt keine Migration.

---

## 📌 1. Projekt-Steckbrief & Zielsetzung

**EntailsNG** ist eine moderne, hochperformante Open-Source-Webplattform für das Management von LAN-Partys, Gaming-Events und E-Sports-Turnieren für Veranstaltungen von **50 bis 1.000+ Teilnehmern**.

### Kerncharakteristika
1. **100% Offline-LAN-fähig (Zero-External-Leak):**
   * Keine Abhängigkeiten zu externen CDNs (Google Fonts liegen lokal als `.woff2` in `static/fonts/`).
   * QR-Codes (Check-in-Tickets und SEPA-GiroCodes) werden vollständig serverseitig per Python (`qrcode`) im Speicher generiert – keine Datenübertragung an Drittanbieter-APIs.
2. **Hybrides Deployment:**
   * Läuft wahlweise auf einem Heimserver hinter **Cloudflare Tunnel** (ohne Router-Portfreigaben, ohne Redirect-Loops), auf einem regulären **Linux-VPS** mit automatischen Let's-Encrypt-Zertifikaten oder komplett autark vor Ort auf einem **Offline-Laptop/Server**.
3. **Konfigurierbar & Mehrsprachig:**
   * Über 185 Systemtexte und Spielmodi können dynamisch im Admin-Bereich angepasst werden (`SystemTranslation`).
   * 9 integrierte Themes (Warm Amber, Cyberpunk Neon, Terminal Green/Mainframe, Quake 99, Arena Pro, etc.) mit globaler UI-Skalierung.

---

## 🏗️ 2. Architektur & Tech-Stack

```mermaid
graph TD
    Client["Browser (Desktop & Mobile)"] -->|HTTPS / HTTP| Nginx["Nginx Reverse Proxy (Port 80/443)"]
    Nginx -->|Statics / Media / Fonts| StaticFiles["WhiteNoise & Nginx Cache"]
    Nginx -->|App Requests| Gunicorn["Gunicorn WSGI (3 Worker, per WEB_CONCURRENCY konfigurierbar)"]
    Gunicorn --> Django["Django 6 App-Server"]
    Django --> Postgres["PostgreSQL 16 (oder SQLite Dev)"]
    Django --> Redis["Redis 7 (Sitzplan & Cache)"]
```

| Komponente | Technologie | Zweck & Besonderheiten |
|---|---|---|
| **Backend** | Python 3.12+ / Django 6.0 | Robuster Monolith mit domänenspezifischem Service-Layer (Turniere, Zahlungen, E-Mail Outbox) |
| **Datenbank** | PostgreSQL 16 (Prod) / SQLite 3 (Dev/Test) | Umschaltbar über `DB_ENGINE=sqlite` oder `DB_ENGINE=postgres` |
| **Caching & Queue** | Redis 7 / Django Cache Framework | Sitzplan-Reservierungs-Cache, Session-Store, Translations-Cache |
| **Webserver** | Nginx & WhiteNoise | Gunicorn-Proxy mit Cloudflare-Tunnel-Erkennung & Fallback-Certs |
| **Frontend** | Vanilla ES6 JS + Semantic CSS Variables | Kein schweres JS-Framework (React/Vue), dadurch blitzschnelle Ladezeiten |
| **Fonts & Assets** | Barlow Condensed, DM Sans, JetBrains Mono | 100% lokal eingebunden via `static/css/fonts.css` |

### Worker und Betriebskonfiguration

Der `web`-Container startet Gunicorn mit standardmäßig **3 Web-Workern**. Die Zahl wird über `WEB_CONCURRENCY` in `.env` gesetzt; das Dockerfile gibt 3 vor, falls die Variable fehlt. Der feste `--workers`-Parameter wurde entfernt, damit Gunicorn die Variable auswertet. Nach einer Änderung muss der Web-Container mit `docker compose up -d --build --force-recreate web` neu erstellt werden. `WEB_CONCURRENCY` wirkt nicht auf `./start.sh` beziehungsweise Djangos Entwicklungsserver und verändert auch nicht die Zahl der PostgreSQL-Worker.

Die Worker-Zahl gehört zur Deployment-Konfiguration und nicht zu `GeneralConfiguration` im Django-Admin: Ein Datenbankwert kann laufende Gunicorn-Prozesse nicht zuverlässig und dauerhaft umstellen. Zusätzliche Web-Worker verbrauchen RAM, halten potenziell weitere Datenbankverbindungen offen und können die Wartezeit an der Event-Zeilensperre erhöhen. Die lokale [Lastmessung](docs/performance-smoke-2026-09-26.md) zeigte bei 32 parallelen Anmeldungen 52,9 ms p95 und bis zu 31 wartende PostgreSQL-Sessions; das ist kein Anlass, PostgreSQL-Parallel-Worker pauschal zu erhöhen.

PostgreSQL-Parameter wie [`max_worker_processes`](https://www.postgresql.org/docs/16/runtime-config-resource.html#RUNTIME-CONFIG-RESOURCE-ASYNC-BEHAVIOR) sind separate Serverparameter; `max_worker_processes` wird erst beim Start des Datenbankservers wirksam. Sie sollten nur anhand konkreter Datenbankabfragen und Serverressourcen angepasst werden. Ebenso ist `email_worker` in `docker-compose.yml` ein eigener Prozess für die E-Mail-Warteschlange und unabhängig von `WEB_CONCURRENCY`.

---

## 📦 3. App- & Modul-Übersicht

Das Projekt ist in saubere Django-Apps unterteilt:

### 🎟️ `events` (Event-, Ticket- & Check-in-Management)
* **Modelle:** `Event`, `TicketCategory`, `EventRegistration`.
* **Services:** `PaymentService` (`events/services.py`) entkoppelt Seiteneffekte (Sitzplatz-Reservierung, Zahlungs-Mail, Cache-Invalidierung) sauber von den Models.
* **Aktives Event:** Immer über `Event.objects.get_active()` abfragen (Single Source of Truth).
* **Helfer Check-in Scanner (`/checkin/scanner/`):** Kamera, USB-/Code-Eingabe und Teilnehmerliste zeigen auf dem Scanner-Gerät eine große Bestätigung mit Nickname, Sitzplatz und lokaler Uhrzeit. Drei Sekunden Lesepause und Unterdrückung dauerhaft sichtbarer QR-Codes verhindern das Überschreiben durch Mehrfachscans. Ablehnungen und unbestätigte Verbindungsfehler sind sichtbar; Ton/Vibration ergänzen die Anzeige. Die Enter-Suche checkt ausschließlich ein. Zentrale Prüfung über `can_check_in()`. Details und Testnachweise: [Scanner-Rückmeldung](docs/scanner-feedback.md).
* **Veranstaltung abschließen:** Die Admin-Eventliste bietet eine Abschlussaktion mit Bestätigungsseite. `EventLifecycleService.finish_event()` verlangt, dass alle Turniere beendet oder abgesagt sind, beendet und deaktiviert das Event atomar und archiviert seine Teams. Entwürfe und abgesagte Events können nicht abgeschlossen werden. Das reguläre Admin-Formular verhindert den direkten Abschluss und die Wiederöffnung eines abgeschlossenen Events.
* **Anmeldung öffnen:** Die Aktion „Bereitschaft prüfen und Anmeldung öffnen“ in der Admin-Eventliste zeigt Sperrgründe (Entwurfsstatus, gültiger künftiger Zeitraum, Ort, Kapazität, keine andere aktive Veranstaltung, aktive Tickets, betriebsbereite E-Mail-Konfiguration und bei kostenpflichtigen Tickets Zahlungsdaten) sowie Hinweise (Beschreibung, Sitzplan, E-Mail-Testmodus). `EventLifecycleService.open_registration()` prüft beim Bestätigen erneut und öffnet die Anmeldung atomar. Das Admin-Formular verhindert einen direkten Wechsel auf „Anmeldung geöffnet“. Beim Anlegen eines Events wird ein Standardticket nur erzeugt, wenn nach dem Speichern der Ticket-Inlines keine Kategorie vorhanden ist.
* **Sperren nach Eventende:** Abgelaufene und abgeschlossene Events erlauben keinen neuen Check-in oder neue Turnieranmeldungen mehr. Die Prüfungen sitzen in den zentralen Modellen und Services; Eventabschluss, Check-in und Turnieranmeldung sperren die Event-Zeile zuerst.
* **GiroCode (EPC-QR):** Generiert SEPA-Überweisungs-QRs mit vorbefülltem Betrag und Verwendungszweck.

### 🖨️ `media_designer` (Vorlagen & Druckexport)
* **Vorlagen:** Eventgebundene Badge- und Urkundenvorlagen mit optionalem JPG/PNG/WebP-Hintergrund und validierten Textfeldern in relativen Koordinaten (`schema_version=1`). Der Editor ist unter `/media-designer/` für Mitarbeiter erreichbar.
* **Schriftarten:** `MediaFont` verwaltet TTF-, OTF- und WOFF2-Dateien bis 5 MB im Django-Admin. Jedes Textfeld kann eine verwaltete Schrift oder die Standardschrift wählen; Vorschau und PDF-Export verwenden die Auswahl. Beim Löschen werden Verweise in vorhandenen Vorlagen auf die Standardschrift zurückgesetzt und die Datei nach dem Datenbank-Commit entfernt.
* **Seriendruck:** Badges verwenden Anmeldungen; die Empfänger können nach Bezahlstatus und zugewiesenem Sitzplatz gefiltert werden. Stornierte Anmeldungen bleiben ausgeschlossen. Urkunden verwenden angemeldete Teams abgeschlossener Turniere. Platzierungen kommen aus `TournamentPodiumService`; unbekannte Platzierungen bleiben leer. Die Orga kann pro Export eine frei benannte Auszeichnung vergeben.
* **Zusätzliche Felder:** Veranstaltungsbeginn und -ende stehen mit lokaler Uhrzeit für Badges und Urkunden bereit. Urkunden können bestätigte Teammitglieder zeilenweise als Gamer-Tags ausgeben; maßgeblich ist der aktuelle Teamkader beim Export, kein historischer Turnier-Snapshot.
* **Druck:** Serverseitige PDF-Erzeugung mit Pillow bei 300 DPI. A6/A7/A8-Badges sind einzeln oder auf A4-Bögen mit 5 mm Rand, 4 mm Abstand und Schnittmarken exportierbar (A8: 9 pro Bogen). A4-Urkunden werden einzeln ausgegeben.
* **Grenzen der ersten Version:** Hochformat und keine Druckbeschnittzugabe. Hintergründe werden proportional zugeschnitten. Die Textvorschau verwendet Beispieldaten; der Export verkleinert lange Texte bis auf 1,5 mm und meldet danach einen Fehler.

### 🏆 `tournaments` (Turnier-Engine & Team-Management)
* **Turnier-Neustarts im Backend (2. Oktober 2026):** Der Button „Neustart vorbereiten“ an einem Turnier erstellt für alle sechs Modi und alle Ausgangsstatus eine neue Ausgabe als Entwurf. Titel/Termine, Teamauswahl, Übernahme von Seeds und optionale Absage des offenen/laufenden Originals werden in einer Vorschau festgelegt. Ergebnisse, Gruppen, Rückzüge und Schweizer Runden beginnen neu; die ursprüngliche Historie bleibt erhalten. Signierte Vorschau, atomare Erstellung, Schutz gegen doppelte Formularübermittlung und schreibgeschützte Herkunftsprotokolle sind enthalten. Erforderlich: Mitarbeiterstatus sowie Rechte zum Anlegen/Ändern von Turnieren und zum Anlegen von Turnieranmeldungen. Archivierte Teams werden nicht automatisch reaktiviert; der Turnierstart prüft die aktuellen Kader. Beendete Events erlauben nur die Vorbereitung eines Entwurfs. Migration `tournaments.0011_tournament_restart` und `seed_translations` erforderlich. Bedienung und Tests: [Turnier-Neustarts](docs/tournament-restarts.md).
* **Verbesserungen aller sechs Modi (1. Oktober 2026):** Die Befunde aus der Einzelprüfung sind korrigiert: expliziter Schweizer Rettungsweg mit signierter Ausnahmevorschau und zusätzlicher Orga-Zustimmung, Ausschluss zurückgezogener Liga-Teams aus Platzierungen, Bereinigung überflüssiger Grand-Final-Resets, vollständige Ligaplatzierungen für Urkunden und vollständige aktive FFA-Ränge. Dazu kommen optionales kleines Finale, klare Rundennamen, DE-Kreuzverteilung, echtes Snake-Seeding sowie konfigurierbare Liga-/Gruppen-Gleichstandsregeln und Gruppenqualifikanten. Neue Regeln werden nach Generierung gesperrt; vorhandene Turniere behalten ihre historische Gleichstandsregel. Migration `tournaments.0010_format_improvements`, `seed_translations` und `collectstatic` erforderlich. Größerer Testlauf: 350 bestanden, 12 PostgreSQL-Fälle auf SQLite übersprungen; 38 separate Modusprüfungen und 5 JavaScript-Tests erfolgreich. Details und aktuelle Regressionen: [Umsetzung der Verbesserungen](docs/tournament-mode-improvements-2026-10-01.md); historischer Befundbericht: [Einzelprüfung der Modi](docs/tournament-mode-review-2026-10-01.md).
* **Entwürfe im Frontend (1. Oktober 2026):** Entwurfsturniere sind nur für angemeldete, aktive Mitarbeiter (`is_staff`) und Superadmins sichtbar. Gäste erhalten auch beim direkten Aufruf der Detail- und Turnieraktions-URLs keinen Zugriff; eine Zuweisung als Turnieradmin oder Support ersetzt den Mitarbeiterstatus nicht. Ein Klick auf „Entwurf“ in Übersicht oder Detailansicht öffnet die Anmeldung über einen CSRF-geschützten POST und `TournamentLifecycleService.open_registration()`. Die Aktion prüft den aktuellen Entwurfsstatus, sperrt Event und Turnier in dieser Reihenfolge und verhindert das Öffnen bei beendetem/abgesagtem Event oder generiertem Turnierbaum. Anmeldezeiträume bleiben erhalten. Keine Migration erforderlich; neue Texte über `seed_translations` verwalten. Tests: `tournaments.test_draft_visibility`.
* **Modi:** Single Elimination, Double Elimination, Liga (Round Robin), Gruppenphase + K.O., Free For All (FFA), Schweizer System.
* **Services:**
  * `TournamentBracketService`: Generierung aller Turnierbäume inkl. automatischer Freilos-Verteilung (BYEs).
  * `TournamentMatchService`: Score-Verarbeitung, Gewinner-Vorlauf, Bracket-Reset, Walkover-Automatisierung beim Löschen von Teams.
  * `SwissTournamentService`, `SwissPairingService`, `SwissStandingService`: rundenweise Auslosung und Orga-Freigabe, 3/1/0-Punkte, optionale Unentschieden, Buchholz/Sonneborn-Berger und geteilte Ränge. Reines Schweizer System ohne K.-o.-Phase.
* **Schweizer System (1. Oktober 2026):** Teilnehmer und Regeln werden mit Runde 1 festgeschrieben. Weitere Runden werden erst nach vollständigen Ergebnissen manuell freigegeben. Signierte Vorschauen, Rundenprotokolle und Datenbank-Constraints sichern die Veröffentlichung ab. Frühere Ergebnisse sind nach Freigabe der Folgerunde gesperrt; Rückzüge behalten die Historie. Urkunden übernehmen auch geteilte Ränge. Installation: Requirements aktualisieren, Migration `tournaments.0009` anwenden und `seed_translations` ausführen. Details und Testgrenzen: [Schweizer Turniere](docs/swiss-tournaments.md).
* **Team-Management:**
  * **Clanaufnahme und persönliche Einladungen (3. Oktober 2026):** Der aktuelle Kapitän kann bestätigte Mitglieder seines eigenen Clans per Mehrfachauswahl sofort aufnehmen und weitere Spieler per Nickname persönlich einladen. Clan-Adminrechte sind nicht nötig. Clanexterne Spieler müssen selbst annehmen oder ablehnen; der Kapitän kann Einladungen zurückziehen und Bewerbungen ablehnen. Ein späterer Clanaustritt lässt die Teammitgliedschaft bestehen. Der rote Punkt berücksichtigt offene eigene Einladungen und Bewerbungen an eigene Teams auf Desktop und Mobilgeräten. Kadergröße, ein aktives Team pro Spiel, Archiv-/Event-/Turniersperren und gemeinsame Benutzer-/Event-/Teamsperren bleiben maßgeblich. Einladungscode bleibt erhalten; offene Einladungen reservieren keine Plätze. Erforderlich: Migration `tournaments.0012_team_invitations`, `seed_translations`, `collectstatic`. SQLite-Gesamtlauf: 860 Tests, 831 erfolgreich, 29 übersprungen; 29 neue Funktionstests erfolgreich, sechs PostgreSQL-Paralleltests auf SQLite übersprungen und in CI aufgenommen. Bedienung, Lebenszyklus und Prüfgrenzen: [Teamaufnahme und Einladungen](docs/team-recruitment.md).
  * **Automatische Solo-Reaktivierung (1. Oktober 2026):** Die normale Einzelspieler-Anmeldung verwendet das aktuelle Team oder reaktiviert ein archiviertes Solo-Team desselben Accounts und Spiels. Team-ID und Turnierhistorie bleiben erhalten; die neue Turnieranmeldung übernimmt keine alten Ergebnisse oder Aufgaben. Laufende/generierte Turniere, offene alte Anmeldungen und widersprüchliche Kader werden vor dem Wechsel gesperrt. Ein erneuter Abschluss des früheren Events archiviert kein inzwischen reaktiviertes Team. Neue Accounts erhalten keinen Zugriff auf frühere Teams. Details und Tests: [Solo-Reaktivierung](docs/solo-team-reactivation.md). Keine zusätzliche Migration erforderlich.
  * **Spielbezug & Filter:** Teams zeigen das zugehörige Spiel (`team.game.name`); die Teamübersicht bietet Filter-Pills und Sortierung nach Spiel.
  * **Fairplay-Regel:** Ein Teilnehmer darf pro Spiel nur maximal einem aktiven Team angehören (verhindert Doppelteilnahmen).
  * **Benachrichtigungspunkt:** Roter Indikator am Menüpunkt „Teams“ (Sidebar & Mobile Nav) und im Team-Header bei offenen Beitrittsanfragen.
* **Highlights:**
  * **Dynamischer Anmeldestatus:** Buttons spiegeln den Status direkt wider (`✓ Angemeldet` vs. `🎮 Jetzt anmelden →`).
  * **Turnierstart:** Datenfeld `tournament_start` mit transparentem Fallback auf `registration_end` (`effective_tournament_start`).
  * **Responsive Kacheln:** `.tournament-grid` verhindert horizontales Scrollen auf Smartphones ($\le 390\text{px}$).
  * **Loser-Reporting mit Fairplay-Schutz:** Unterlegene Teams können die eigene Niederlage selbst erfassen (`is_loser_reporting`).
  * **Double Elimination 3-Teilung:** Getrennte Bereiche für Winner Bracket (grün), Loser Bracket (orange) und zentrierte goldene Abschluss-Kachel für das **Grand Final**.
  * **Siegerehrung & Podium:** Dynamische Berechnung von Platz 1, 2 und 3 nach Match-Abschluss.
  * **Admin-Vorschau:** Interaktiver Simulations-Tab für Admins vor Turnierstart.

### 🗺️ `seating` (Interaktiver 2D-Sitzplan)
* **Clan-Sitzplatzvormerkungen (4. Oktober 2026):** Globaler Unterpunkt „Clan Sitzplatz Vormerkung“ mit Aktivierung, Standardkontingent **8**, Event-/Tages-/Fixfristen; optionale Clanüberschreibung einschließlich Sperre mit 0. Jeder Clan startet seine Tagesfrist mit seiner eigenen ersten bestätigten Vormerkung. Clan-Admins wählen mehrere freie Plätze im vorhandenen Sitzplan; Logos und dynamischer Tooltip kennzeichnen offene Plätze. Nur bestätigte aktive Mitglieder mit Eventanmeldung dürfen übernehmen; übernommene Plätze zählen weiter zum Kontingent. Administrative Reduzierungen verlangen gezielte Auswahl und Freigabebestätigung. Eigener Compose-Worker `process_clan_seat_holds --daemon` sowie Erinnerungs-/Ablaufvorlagen in der bestehenden Outbox. Buchungsprüfung respektiert Fristen auch ohne Worker; persönliche Buchungen bleiben bei Ablauf erhalten. Migrationen `configuration.0021`, `clans.0006`, `seating.0009`, `seed_translations`, `seed_email_templates`, `collectstatic` und `PUBLIC_BASE_URL` erforderlich; Feature zunächst deaktiviert. SQLite-Gesamtlauf: 941 Tests, 898 erfolgreich, 43 PostgreSQL-Fälle übersprungen. 42 neue Funktionstests, acht neue Paralleltests; gemeinsamer PostgreSQL-18.6-Lauf: 88 erfolgreich. PostgreSQL-16-CI erweitert. Bedienung, Sperren, Betriebsregeln und Screenshots: [Clan-Sitzplatzvormerkungen](docs/clan-seat-holds.md).
* **Modelle:** `SeatingPlan`, `SeatingCell`.
* **Editor & Viewer:** Modularisiertes JavaScript (`static/js/seating.js`), Zoom & Pan, Toast-Feedback und HTML-Modals (keine nativen `alert`/`confirm`-Popups).
* **Feature:** Konfigurierbare Überschreibung unbezahlter Sitzplätze (`allow_unpaid_seat_overwrite`) mit automatischer E-Mail-Benachrichtigung (`seat_overwritten`).

### 👥 `users` (Authentifizierung & Sicherheit)
* **Selbstlöschung im Profil (30.09.2026):** Gast-Accounts können sich nach Passwortbestätigung endgültig löschen. `UserService.delete_account()` entfernt persönliche Profildaten, hält einen irreversiblen Restdatensatz (`deleted_at`) für die Historie und gibt Namen/E-Mail zur Neuregistrierung frei. Neue Accounts erhalten eine neue ID ohne alte Tickets oder Mitgliedschaften. Jede `PAID`-Anmeldung sowie laufende/generierte Turnierbeteiligungen blockieren die Selbstlöschung bis zur Klärung mit der Orga. Clan-/Team-Nachfolgen, Sitzplatzfreigabe, Code-/Session-Invalidierung und Bereinigung zuordenbarer Mail-/Fehlerkopien sind enthalten. Mitarbeiterkonten werden an die Administration verwiesen. Nach dem Update `migrate` und `seed_translations` ausführen. Details, Testnachweise und Betriebsgrenzen: [Account-Löschung](docs/account-deletion.md).
* **Login:** Flexibel per E-Mail oder Benutzername über `CustomAuthenticationBackend`.
* **Brute-Force & Rate-Limiting:** Echte Client-IP-Erkennung hinter Proxies (`CF-Connecting-IP`, `X-Real-IP`).
* **Double-Opt-In:**
  * Bei Registrierung (6-stelliger Code).
  * Bei E-Mail-Änderung im Profil: Bisherige E-Mail bleibt intakt, neuer Code geht an die Zieladresse (kein Aussperren bei Tippfehlern!).

### 🛡️ `clans` (Clan-System)
* Clans, Logos, Beitrittspasswörter.
* **Partieller UniqueConstraint:** Ein Benutzer kann immer nur in **maximal einem aktiven Clan** Mitglied sein (`condition=Q(status='ACCEPTED')`).
* Inline-Bestätigungen für Kicken und Verlassen (ohne störende Browser-Popups).
* **Mehrere gleichberechtigte Clan-Admins (3. Oktober 2026):** Unbegrenzte Anzahl, öffentliche Übersicht der aktiven Admins und ihrer Anzahl im Clanprofil. Beförderung und Herabstufung benötigen eine Inline-Bestätigung; die Mitgliedschaft bleibt erhalten. Nur aktive, bestätigte Mitglieder erhalten Adminrechte. Der letzte aktive Admin ist geschützt, auch bei veralteten Formularen und parallelen Rollenänderungen/Austritten. Benutzer-/Clan-/Mitgliedschaftssperren koordinieren die Rollenverwaltung mit der Kontolöschung; die Nachfolge bevorzugt aktive Mitglieder. Beitrittsentscheidungen verarbeiten ausschließlich offene Anfragen. SQLite-Regression: 113 Tests, 101 erfolgreich, 12 PostgreSQL-Fälle übersprungen; sieben neue Paralleltests in PostgreSQL-CI aufgenommen, lokal nicht gegen PostgreSQL ausgeführt. Desktop und Mobilansicht (390 px) geprüft. Einführung: `seed_translations`, `collectstatic`; keine Migration. Bedienung und Grenzen: [Clan-Admins](docs/clan-admins.md).

### ⚙️ `configuration` (CMS, Themes & System-Services)
* **Translations:** `SystemTranslation` & `configuration/translations.py`.
  * Globale Hilfsfunktion `get_translation(key, default, **kwargs)`.
  * Globales Template-Tag `{% t "key" "Standard" %}` (als Builtin registriert – kein `{% load %}` nötig!).
* **Themes & Branding:** Live-Anpassung von Farbschemata, Logo und `UIScale`.
  * Kontrastreiche, theme-abhängige Statusfarben für Hinweise und Warnungen (WCAG AA).
* **Navigation & Caching:** `NavigationItem` mit automatischer SVG-Bereinigung und robuster Cache-Invalidierung auch bei Massenlöschungen. Im Admin kann jeder Menüpunkt für alle Besucher, nur angemeldete Benutzer oder nur Mitarbeiter (`is_staff`) sichtbar gemacht werden. Die gemeinsame Menüliste wird nach dem Laden aus dem Cache pro Anfrage gefiltert; die Migration `0020` setzt bestehende Medien-Designer-Menüpunkte auf „Nur Mitarbeiter“. Die Zielseiten müssen ihre Zugriffsrechte selbst prüfen.
* **Error-Logging:** `DynamicDebugMiddleware` loggt ungefangene 500er-Fehler persistent als `SystemErrorLog` in die DB und vergibt eine Referenz-ID für den Benutzer.

### 📄 `info`, `news`, `emails`, `sponsors`
* **`knowledge` – interne Wissensbasis (1. Oktober 2026):** Eigene Frontend-App unter `/knowledge/` mit veranstaltungsübergreifenden beziehungsweise eventbezogenen Bereichen, Seitenbaum, Suche, lokalem TinyMCE-Editor, Entwürfen, Veröffentlichung, Versionshistorie, Textvergleich, Wiederherstellung und optimistischer Konfliktprüfung. Alle aktiven Mitarbeiter (`is_staff`) dürfen lesen, bearbeiten und veröffentlichen; Gäste bleiben vollständig ausgeschlossen. Anhänge liegen außerhalb von `MEDIA_ROOT` im privaten Speicher und werden nur nach Mitarbeiterprüfung ausgeliefert. Docker erhält dafür das ausschließlich im Web-Container eingebundene Volume `private_media_data`. Einführung: `migrate`, `seed_translations`, `seed_features`, `collectstatic`; neue Container mit der aktualisierten Compose-Konfiguration erstellen. Details: [Interne Wissensbasis](docs/internal-knowledge-base.md).
* `info`: Mehrseiten-CMS mit Tab-Leiste (`/info/<slug>/`), Slugs mit automatischer Kollisionsauflösung (`-2`, `-3`), XSS-Bereinigung (`sanitize_html`), granularen Rechten (`info.view_eventinfo`), Gast-Fallback auf `/info/` und atomarer Menü-Synchronisation (`NavigationItem`).
* `news`: Newsartikel mit lokalem TinyMCE-Editor im Django-Admin (3. Oktober 2026). Das Inhaltsfeld verwendet `AdminTinyMCE` mit GPL-Konfiguration, Formatierung, Listen, Links, Bildern per URL, Tabellen, Quelltext und Vorschau. Die Newsansicht rendert das von berechtigten Mitarbeitern verfasste HTML; bestehende reine Textbeiträge behalten ihre Absätze und Zeilenumbrüche. Dashboard-Auszüge bleiben reine Textvorschauen. Keine zusätzliche Abhängigkeit oder Migration erforderlich. Prüfung: `python manage.py test news`.
* `emails`: Multi-Backend-E-Mail-Versand (SMTP, Resend API, Console) mit verschlüsselter Speicherung von Passwörtern (`FIELD_ENCRYPTION_KEY`) und transaktionssicherer E-Mail-Warteschlange (`OutgoingEmail` Outbox-Pattern).
* `sponsors`: Partner- und Sponsoren-Verwaltung.

### 💾 `backups` (3. Oktober 2026)
* **Bedienung:** `/admin/backups/` und Link auf der Admin-Startseite, ausschließlich
  für aktive Superuser mit Mitarbeiterstatus. Manuelle Sicherung, verschlüsselter
  Download, Upload/Vorprüfung und vollständiger Datenersatz nach Passwortbestätigung.
* **Umfang:** Native PostgreSQL-/SQLite-Sicherung sowie öffentliche und private
  Medien, AES-256-GCM mit separatem `BACKUP_ENCRYPTION_KEY`. `.env`, Schlüssel,
  Quellcode, Zertifikate und Redis werden separat gesichert.
* **Betrieb:** Ein eigener Prozess `process_backup_jobs --daemon`, optionales
  Compose-Profil `backups`, standardmäßig eine CPU und 512 MB RAM. Gemeinsamer,
  nicht öffentlich ausgelieferter `backup_data`-Speicher für Web-, Mail- und
  Backup-Worker; PostgreSQL-16-Clients im Anwendungsimage. Keine neue Queue oder
  externe Dienste, keine Zeitplanung. Einrichtung und Grenzen: [Backup-Anleitung](docs/backups.md).
* **Konsistenz und Rücksetzung:** Dateisperren koordinieren Webanfragen und Mail,
  Wartungsfenster für Datenaufnahme und Wiederherstellung, isolierte Vorprüfung,
  automatische Sicherung vor Datenersatz und Journal außerhalb der Datenbank.
  Ein unterbrochener Wechsel wird beim Worker-Start zurückgesetzt. Nach Restore
  werden Sessions/Codes gelöscht, Caches und Verbindungen erneuert und Mail pausiert.
* **Kompatibilität:** Derselbe produktive Code, Migrationsstand, Datenbanktyp und
  dieselbe Datenbank-Hauptversion. Für lokale Dateisysteme/gemeinsame Docker-Volumes
  auf einem Host; zusätzliche Schreibprozesse und Deployments im Wartungsfenster
  stoppen. Kein unterstützter Betrieb über verteilte Hosts/NFS.
* **Aktivierung:** `BACKUP_ENCRYPTION_KEY` setzen und separat aufbewahren,
  `docker compose --profile backups up -d --build`, `seed_translations` ausführen.
  Keine zusätzliche Datenbankmigration erforderlich. Tests: `backups/tests.py`,
  eigener PostgreSQL-16-Job in CI; beide nativen Datenbankverfahren lokal geprüft.

---

## 💻 4. Entwickler-Setup & Lokale Ausführung

### Voraussetzungen
* Python 3.12 oder 3.13 / 3.14
* SQLite (Dev) oder Docker/Podman (PostgreSQL 16 + Redis 7)

### Schritt-für-Schritt Einrichtung

```bash
# 1. Repository klonen & Verzeichnis betreten
git clone <repo-url> entails-ng
cd entails-ng

# 2. Virtuelle Umgebung erstellen & aktivieren
python3 -m venv .venv
source .venv/bin/activate

# 3. Abhängigkeiten installieren
pip install --upgrade pip
pip install -r requirements.txt

# 4. Umgebungskonfiguration (.env) anlegen
cp .env.example .env
# Für SQLite Development: Sicherstellen, dass DB_ENGINE=sqlite gesetzt ist

# 5. Datenbank migrieren
python manage.py migrate

# 6. Obligatorische System-Seeds ausführen (Idempotent!)
python manage.py seed_translations    # Befüllt über 500 Systemtexte in die DB
python manage.py seed_features        # Richtet Standard-Navigationspunkte & Icons ein (NavigationItem)
python manage.py seed_email_templates # Richtet alle HTML-E-Mail-Vorlagen ein
# (Hinweis: Die Kontext-Processor-Keys 'features' und 'feature_flags' sind reservierte Platzhalter für künftige Feature-Toggles.)

# 7. (Optional) Testdaten & Standard-Accounts laden
python manage.py loaddata initial_data.json
# Standard-Zugänge aus Demo-Daten:
# Superadmin: sadmin / EntailsDemo2026!
# Orga-User:  organizer / EntailsDemo2026!
# Gamer-User: gamer1 / EntailsDemo2026!

# 8. Entwicklungs-Server starten
python manage.py runserver
```

---

## 🧪 5. Testing & Qualitätssicherung

Das Projekt verfügt über eine umfassende automatisierte Testsuite (**537 Tests** über alle Module, auf SQLite und PostgreSQL bestanden; Stand 26.09.2026).

> [!NOTE]
> Die 537 Tests stellen den Testumfang dar. Zur Ermittlung der metrischen Zeilen- und Verzweigungsabdeckung (Code Coverage) wird das Tool `coverage` empfohlen:
> ```bash
> coverage run manage.py test
> coverage report
> ```

> **Wichtiger Hinweis zu Parallelitätstests & Zeilensperren:**  
> SQLite prüft `select_for_update()` nicht (`has_select_for_update = False`). Während logische Datenbank-Constraints (wie `UniqueConstraint`) auch auf SQLite greifen, sollten Zeilensperren-Konflikte (`FOR UPDATE`) gezielt unter **PostgreSQL** mit `TransactionTestCase` und getrennten Datenbankverbindungen getestet werden.

Die manuelle Browser-Simulation wurde mit einer getrennten PostgreSQL-Testdatenbank durchgeführt: Event-Entwurf und Bereitschaftsprüfung, Öffnung der Anmeldung, Gastregistrierung mit E-Mail-Code, Eventanmeldung, Zahlung und Check-in, zwei Solo-Turnieranmeldungen, Turnierbaum und Finale sowie Eventabschluss.

### Tests ausführen

```bash
# Gesamte Testsuite ausführen (SQLite im Speicher):
DB_ENGINE=sqlite python manage.py test

# Gezielt nur das Turniermodul testen:
DB_ENGINE=sqlite python manage.py test tournaments

# Gezielt Sitzplan & Events testen:
DB_ENGINE=sqlite python manage.py test seating events

# Testlauf mit Failfast (bricht beim ersten Fehler ab):
DB_ENGINE=sqlite python manage.py test --failfast

# PostgreSQL (mit eigener lokalen Testinstanz und passenden DB_*-Variablen):
DB_ENGINE=postgresql python manage.py test --noinput
```

---

## 📐 6. Wichtige Programmier- & Design-Richtlinien

Wenn du neuen Code schreibst oder bestehende Funktionen erweiterst, beachte bitte folgende Konventionen:

### 1. Service-Layer Pattern (fortlaufende Umsetzung)
* **Status:** Vollständig umgesetzt in `tournaments/services.py` (`TournamentBracketService`, `TournamentMatchService`), `events/services.py` (`PaymentService`) und `emails/services.py` (Transactional Outbox & Rendering).
* **Entwicklungsziel:** Geschäftslogik schrittweise aus Views und Models in Services auslagern. Domänenlogik in `SeatingCell.reserve_for_user()` (`seating/models.py`) und Profil-/Verifizierungsabläufe in `users/views.py` sind künftige Kandidaten für die vollständige Kapselung in dedizierte Services (`seating/services.py`, `users/services.py`).
* Model-Methoden delegieren an Services (z. B. `EventRegistration.mark_as_paid()` delegiert an `PaymentService.mark_paid()`).

### 2. Single Source of Truth für das aktive Event
* **Niemals** `Event.objects.filter(is_active=True).first()` aufrufen!
* **Immer** `Event.objects.get_active()` verwenden. Diese Methode cached das aktive Event intelligent (Request-Cache + Redis) und garantiert Konsistenz über alle Apps.

### 3. Übersetzungen & Texte
* **Niemals** benutzerseitige Strings hardcodieren!
* **In Templates:** `{% t "schluessel_name" "Standardtext falls nicht in DB" %}`
  *(Hinweis: `translations` ist in `TEMPLATES['OPTIONS']['builtins']` registriert – kein `{% load %}` erforderlich!)*
* **In Python-Code / Flash Messages:**
  ```python
  from configuration.translations import get_translation
  msg = get_translation("mein_key", "Mein Fallback-Text {name}", name=user.username)
  messages.success(request, msg)
  ```
* Neue Standardschlüssel in `configuration/translations.py` im Dictionary `DEFAULT_TEXTS` ergänzen und anschließend `python manage.py seed_translations` ausführen.

### 4. Keine nativen Browser-Dialoge (`confirm` / `alert`)
* Moderne Web-UX: Verwende **keine** synchronen Browser-Dialoge (`confirm(...)` oder `alert(...)`).
* Für Aktionen mit Bestätigung (Löschen, Verlassen, Kicken, Bracket-Generierung) nutzen wir das **Inline 2-Schritt-Pattern**:
  1. Klick auf den Aktionsbutton blendet den Button aus und einen kleinen Bestätigungscontainer ein (`#action-confirm`).
  2. Enthält `✓ Ja` und `✕ Abbrechen`.
* Für Fehlermeldungen in Modals nutzen wir dedizierte Fehler-Container (z. B. `#scoreFormError`).

### 5. Caching & Redis-Ausfallsicherheit
* Verwende für Cache-Löschungen immer `safe_cache_delete(...)` aus `configuration.cache` bzw. `configuration.models`, damit ein temporärer Redis-Ausfall niemals Datenbank-Transaktionen abbricht.

---

## 🚀 7. Deployment-Optionen im Überblick

| Modus | Startbefehl | Wann nutzen? |
|---|---|---|
| **🟢 Weg A: Cloudflare Tunnel** | `docker compose --profile tunnel up -d` | **Empfohlen** für Heimserver, Mini-PCs & lokale VMs. Keine Portweiterleitung im Router nötig; vollautomatisches SSL. |
| **🔵 Weg B: Linux-VPS** | `bash nginx/init-letsencrypt.sh` | Für öffentliche Server (Hetzner, Netcup etc.) mit eigener IPv4 und offenen Ports 80/443. |
| **🟡 Weg C: Offline / Vor-Ort** | `./start.sh` | Autarker Betrieb in Schützenheimen oder Hallen ohne Internetanbindung. |

*(Ausführliche Schritt-für-Schritt-Anweisungen finden sich in `INSTRUCTIONS.MD`.)*

---

## 📋 8. Empfohlene nächste Schritte (Backlog für Weiterentwickler)

Falls du weiter an EntailsNG arbeiten möchtest, sind hier die aktuell sinnvollsten Ausbaustufen und Ideen:

1. **Turnier-Erweiterungen:**
   * **Live-Ticker / WebSockets:** Automatische Aktualisierung des Turnierbaums via HTMX-Polling oder WebSockets, sobald ein Ergebnis eingetragen wird (aktuell über standardmäßigen Seiten-Reload).
   * **Turnier-Exporte:** Exportfunktion der Brackets als PDF oder JSON/Challonge-Kompatibilität.
2. **Check-in & Einlass-Statistiken:**
   * Ein Live-Dashboard-Widget für Orga-Admins, das anzeigt, wie viele Prozent der Gäste bereits eingecheckt sind und zu welchen Stoßzeiten der Einlass stattfand.
3. **Sitzplan-Export:**
   * Export des finalen Sitzplans mit Namen als Druck-PDF (A3/A4) zum Aushängen am Halleneingang.
4. **Clan-Turnier-Statistiken:**
   * Aggregierte Clan-Rankings über mehrere Turniere hinweg (Clan-Meisterschaft).

---

*Viel Erfolg bei der Weiterentwicklung von EntailsNG! Bei Fragen helfen die Unittests in den jeweiligen App-Ordnern (`tests.py`) als ideale Dokumentation der erwarteten Verhaltensweisen.*
