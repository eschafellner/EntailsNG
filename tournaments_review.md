# QA-Review Turniermodul – EntailsNG

Datum: 31.10.2026 · Rolle: QA (rein lesend, keine Code-/Konfigurationsänderung) · Prüfgegenstand: alle 6 Turniermodi von der Anlage bis zur Ergebnisbestätigung.

## 1. Zusammenfassung

Das Turniermodul ist funktional robust. In allen 6 Modi (Single Elimination, Double Elimination, Liga, Gruppenphase + KO, FFA, Schweizer System) liefen Teilnehmerzahlen von 2 bis 32 vollständig durch: Anlage, Anmeldung, Auslosung, alle Runden, Bestätigung. Dabei wurden Freilose korrekt erzeugt, die Platzierungen stimmten mit den Erwartungen überein und die Anzeige deckte sich mit dem Backend. Ungültige Eingaben, Korrekturen, Unentschieden und die Kaderregeln werden konsistent geprüft.

Gefundene Befunde (7):

| Schweregrad | Anzahl |
| --- | --- |
| kritisch | 0 |
| hoch | 1 |
| mittel | 1 |
| niedrig | 5 |

Größte Risiken:
1. **B-01 (hoch):** Wenn die Orga in 1v1-Turnieren ein bestimmtes Team anmeldet, wird stattdessen ihr eigenes Solo-Team angemeldet. Die Erfolgsmeldung nennt das falsche Team. Die Orga kann Spieler in 1v1-Turnieren also nicht stellvertretend anmelden.
2. **B-02 (mittel):** Zieht sich in SE/DE ein Finalist zurück, hängt die Endplatzierung vom Zeitpunkt ab. Ist das Finale schon besetzt, bekommt das zurückgezogene Team Platz 2. Steht der Gegner noch nicht fest, bleibt Platz 2 leer. Liga, Swiss und FFA vergeben an zurückgezogene Teams gar keinen Rang.

## 2. Testumgebung

| Punkt | Stand |
| --- | --- |
| Code | Branch `main`, Commit `aeb0ec8` (Arbeitsbaum unverändert) |
| Laufzeit | Projekt-venv: Python 3.14.8, **Django 6.0.7** (Lockfile pinnt 6.0.9, siehe Abschnitt 6) |
| Datenbank | lokaler Docker-Container `entailsng_postgres` (PostgreSQL 16.15). Für den Test wurde eine **separate DB `entails_qa`** angelegt, migriert und mit den drei System-Seeds befüllt. Die Entwicklungs-DB `entails` wurde nicht angefasst. |
| Cache/Mail | `REDIS_URL` leer → LocMemCache (Redis lief nicht), Mail-Backend locmem; nur als Prozessvariablen gesetzt, `.env` unverändert |
| Einstufung | Entwicklungsumgebung: `DEBUG=True`, localhost, Container nur an 127.0.0.1 gebunden |
| Zugriffswege | Django-Test-Client gegen die echten Views/URLs (Admin-Formular für die Turnieranlage, Frontend-Endpunkte für Anmeldung, Auslosungsvorschau/-veröffentlichung, Ergebniseingabe, FFA-Wertung, Swiss-Vorschau/-Veröffentlichung, KO-Freigabe, Bestätigung, Admin-Aktionen). Zusätzlich Browserlauf (Playwright/Chromium) gegen `runserver 127.0.0.1:8765`: Auslosung per Button, Ergebnis per Modal, Darstellung je Modus. Massendaten (Benutzer, Check-in, Teams) per ORM. |
| Testdaten | Event „QA LAN“ (aktiv, läuft), Spiele `QA 1v1`, `QA 2v2`, `QA 5v5`, Superuser `qa_admin`, rund 2.700 synthetische Spieler `qa_p*` (eingecheckt, kostenloses Ticket), ca. 240 Turniere |
| Skripte | `/tmp/claude-1000/-home-edgar-Videos-entails-ng/80df8a78-de26-5c4e-b920-61129a911bd7/scratchpad/qa/` (`qalib.py`, `run_counts.py`, `run_rules.py`, `run_special.py`, `run_targeted.py`, `repro_se.py`, `sweep.py`, `sweep2.py`, `browser.js`, Screenshots `shot_*.png`) |

Spielregel der Simulation: Die Anmeldereihenfolge legt die Stärke fest, und das stärkere Team gewinnt 2:1. Daraus ergeben sich für jeden Modus eindeutige Soll-Platzierungen: SE/DE/Gruppe/Liga/FFA Platz 1–3 = Team 0–2, für Swiss Konsistenzprüfungen.

## 3. Testmatrix

Legende: ✅ bestanden · ❌ fehlgeschlagen · ➖ nicht testbar/nicht anwendbar. SE = Single Elimination, DE = Double Elimination, GS = Gruppenphase.

### 3.1 Teamanzahl (kompletter Durchlauf bis FINISHED, Podium und Anzeige gegen Backend geprüft)

| N | SE (mit Spiel um Platz 3) | DE | Liga | GS (mit Spiel um Platz 3) | FFA | Swiss |
| --- | --- | --- | --- | --- | --- | --- |
| 2 | ✅ | ✅ | ✅ | ✅ korrekt abgelehnt (min. 4) | ✅ | ✅ (1 Runde) |
| 3 | ✅ 2 Freilose | ✅ | ✅ | ✅ korrekt abgelehnt | ✅ | ✅ |
| 4 | ✅ | ✅ | ✅ | ✅ direktes Finale | ✅ | ✅ |
| 5 | ✅ 3 Freilose | ✅ | ✅ | ✅ | ✅ | ✅ |
| 7 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 8 | ✅ | ✅ | ✅ | ✅ Halbfinale + Platz 3 | ✅ | ✅ |
| 15 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 16 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 17 | ✅ 15 Freilose | ✅ 30 Freilose | ✅ | ✅ | ✅ | ✅ |
| 31 | ✅ | ✅ | ✅ 465 Spiele | ✅ | ✅ | ✅ |
| 32 | ✅ | ✅ 62 Spiele | ✅ 496 Spiele | ✅ 244 Spiele | ✅ | ✅ |

Zusätzlich geprüft: Anzahl der Spiele (SE N−1 plus Platz 3, Liga N(N−1)/2), DE (jedes Team außer dem Sieger genau 2 Niederlagen), Swiss (keine wiederholten Paarungen, höchstens ein Freilos pro Team, Punkte = 3·S + U, alle Teams spielen jede Runde). 108 Tabellen (Liga, Gruppen, Swiss, FFA) werden in Backend-Reihenfolge angezeigt. 1.070 Seitenaufrufe (Detailseite als Admin/Gast/Spieler, Admin-Änderungs- und Ergebnisseite, Listen) liefen ohne 5xx.

### 3.2 Teamgröße und unvollständige Teams (Spiel 5v5 bzw. 1v1)

| Szenario | SE | DE | Liga | GS | FFA | Swiss |
| --- | --- | --- | --- | --- | --- | --- |
| STRICT 5/5 anmelden und starten | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| STRICT 4/5 (unter Mindestgröße) → abgelehnt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Team ohne Mitglieder → abgelehnt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 6/5 (über Maximum) → abgelehnt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| BY_START 4/5: Anmeldung ok, Start blockiert, nach Auffüllen Start ok | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| ALLOW_INCOMPLETE 3/5: Anmeldung und Start ok | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Mitglied nach Anmeldung entfernt → Start mit klarer Meldung blockiert | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Letztes Mitglied verlässt angemeldetes Team → Team und Anmeldung entfernt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Anmeldung nach Anmeldeschluss (Kapitän und Admin) → abgelehnt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `max_teams` überschritten → abgelehnt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Mitglied nicht eingecheckt → abgelehnt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Team eines anderen Spiels → abgelehnt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Spieler in zwei Teams → Start blockiert (Anmeldung wird angenommen, B-06) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 1v1: Selbstanmeldung; ohne Check-in abgelehnt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 1v1: Orga meldet Spieler an | ❌ B-01 | ❌ B-01 | ❌ B-01 | ❌ B-01 | ❌ B-01 | ❌ B-01 |
| Austritt/Kick/Abmeldung im laufenden Turnier → gesperrt | ✅ (stichprobenartig in SE) | ➖ | ➖ | ➖ | ➖ | ➖ |

### 3.3 Turnierablauf und Sonderfälle

| Szenario | SE | DE | Liga | GS | FFA | Swiss |
| --- | --- | --- | --- | --- | --- | --- |
| Ungültige Eingaben (Text, negativ, leer, Dezimal, Überlauf, fremder/textueller Sieger, Sieger ≠ Score ohne Grund, veralteter Stand, Unbeteiligter, Teilnehmer trägt eigenen Sieg ein) | ✅ | ✅ | ✅ | ✅ ¹ | ✅ ² | ✅ |
| Unentschieden | ✅ KO ohne Sieger abgelehnt, mit Sieger ok | ✅ | ✅ 1:1 ergibt je 1 Punkt; komplett unentschieden ergibt 4× Rang 1 (B-05) | ✅ in Gruppe erlaubt, im KO abgelehnt | ➖ (geteilte Ränge 2/2 akzeptiert) | ✅ abhängig von `swiss_allow_draws` |
| Ergebnis korrigieren (ohne Grund abgelehnt, mit Grund ok, Folgematch angepasst, nach gespieltem Folgematch gesperrt, Protokoll) | ✅ | ✅ | ✅ Tabelle angepasst | ✅ | ✅ Podium angepasst | ✅ nach Folgerunde gesperrt |
| Walkover/Nichtantreten (Admin-Wertung 0:0 mit Sieger und Grund) | ✅ (B-04) | ✅ | ✅ | ✅ | ➖ (DQ) | ✅ (B-04) |
| Team zieht sich während des Turniers zurück | ✅ ³ (B-02) | ✅ (B-02) | ✅ ohne Rang | ✅ | ✅ disqualifiziert, ohne Rang | ✅ über Swiss-Rückzug, ohne Rang |
| Bestätigung vor Abschluss → abgelehnt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Turnierbaum zurücksetzen (ohne Ergebnisse ok, mit Ergebnissen blockiert) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Browser: Auslosung per Button, Ergebnis per Modal, ungültige Eingabe (−1) durch das Formular blockiert, keine JS-Fehler | ✅ | ✅ (nur Darstellung) | ✅ (Darstellung) | ✅ (Darstellung) | ✅ (Darstellung) | ✅ (Darstellung) |

¹ Im Sammellauf zunächst ❌, Ursache war das Testskript: Der KO-Fall wurde auf ein Gruppenspiel angewendet. Die gezielte Nachprüfung (`run_targeted.py`) ergab KO-Finale 1:1 → 400 und Unbeteiligter → 403. Es liegt kein Befund vor.
² Doppelter Rang 1, Rang 0, Rang > N, Text als Punkte, fehlender Teilnehmer, kein Rang 1 und veralteter Stand wurden abgelehnt.
³ Ergebnis abhängig vom Zeitpunkt, siehe B-02.

## 4. Befunde

### B-01 – Orga-Anmeldung in 1v1-Turnieren registriert das Orga-Konto statt des gewählten Spielers
- **Modus:** alle (betrifft jedes Turnier, dessen Spiel `team_size = 1` hat)
- **Schweregrad:** hoch
- **Reproduktion:**
  1. Als Superuser anmelden. Spiel mit Teamgröße 1 und ein beliebiges Turnier dazu anlegen, Anmeldung öffnen.
  2. Für einen eingecheckten Spieler existiert ein Solo-Team (z. B. Team-ID 1147).
  3. `POST /tournaments/<slug>/register/` mit `team_id=1147` als Superuser senden (entspricht der Anmeldung über die Detailseite).
- **Erwartet:** Das gewählte Team bzw. der gewählte Spieler wird angemeldet. Alternativ wird die Aktion mit einem Hinweis abgelehnt.
- **Tatsächlich:** Meldung „Team "qa_admin (Solo)" erfolgreich für "…" angemeldet!“. In `TournamentRegistration` steht das automatisch erzeugte Solo-Team des Admins; das gewählte Team ist nicht angemeldet. In allen 6 Modi reproduziert (`run_rules.py`, Fall „1v1: Admin meldet Spieler an“). Ursache: `TournamentRegistrationService.register_team` ignoriert bei `team_size == 1` den Parameter `team_id` und verwendet `user` (`tournaments/services/registration.py:234-235`).

### B-02 – Rückzug eines Finalisten (SE/DE): Platz 2 abhängig vom Zeitpunkt, zurückgezogenes Team erhält einen Podiumsplatz
- **Modus:** Single Elimination, Double Elimination
- **Schweregrad:** mittel
- **Reproduktion A (Finale schon besetzt):**
  1. SE-Turnier mit 4 Teams (2v2) starten, beide Halbfinals werten.
  2. Admin → Teams → Finalteilnehmer markieren → Aktion „Ausgewählte Teams aus laufenden Turnieren zurückziehen“.
  3. Ergebnisse bestätigen.
  - Ergebnis: Das Finale wird als `WALKOVER` gewertet. Das Podium zeigt das **zurückgezogene Team auf Platz 2**. Mit „Spiel um Platz 3“ ergeben sich die Platzierungen [1, 2 = zurückgezogenes Team, 3]. DE verhält sich bei Rückzug im Grand Final gleich (Podium [S00, zurückgezogenes S01, S02]).
- **Reproduktion B (Gegner noch offen, `repro_se.py`):**
  1. SE-Turnier mit 4 Teams starten und nur Halbfinale 2 werten. Der Sieger steht im Finale, das Finale ist PENDING.
  2. Diesen Sieger wie oben zurückziehen, danach Halbfinale 1 werten und bestätigen.
  - Ergebnis: Das Finale wird zum Freilos (`is_bye=True`, `result_type=PLAYED`, `loser=None`, Grund „Admin-Entscheidung / Disqualifikation“). Podium `[Sieger, None, None]`, Platzierungen nur `[(1, Sieger)]`. **Platz 2 bleibt leer**, der Halbfinal-Verlierer wird nicht nachgezogen.
- **Erwartet:** Dieselbe Situation führt unabhängig vom Zeitpunkt zu derselben Wertung. Laut `docs/tournament-result-management.md` bleiben zurückgezogene Teilnehmer disqualifiziert, und in Liga, Swiss und FFA erhalten sie keinen Rang. Das Finale sollte als kampflose Wertung (`WALKOVER`) erscheinen, nicht als „Freilos“.
- **Tatsächlich:** wie oben. Der Unterschied betrifft Podium, Siegerehrung und spätere Urkunden.

### B-03 – Freilos-Finale nach Rückzug mit uneinheitlicher Ergebnisart
- **Modus:** SE (gleiche Logik in DE/GS-KO über `check_and_advance_match`)
- **Schweregrad:** niedrig
- **Reproduktion:** wie B-02, Variante B.
- **Erwartet:** Ein automatisch entschiedenes Match hat die Ergebnisart `BYE` oder `WALKOVER`.
- **Tatsächlich:** `is_bye=True`, aber `result_type=PLAYED`. Die Anzeige lautet „<Sieger> vs BYE“, der Grund stammt vom Rückzug. Auswertungen, die nach `result_type` filtern, zählen das Match als gespielt.

### B-04 – Kein eigener Walkover/Nichtantreten-Ergebnistyp für ein einzelnes Match
- **Modus:** SE, DE, Liga, GS, Swiss
- **Schweregrad:** niedrig
- **Reproduktion:** In einem bereiten Match als Admin `score_team1=0`, `score_team2=0`, `winner_id=<Team 2>`, `decision_reason="Nichtantreten"` speichern.
- **Erwartet:** Die Wertung wird als kampflos (`WALKOVER`) gespeichert, wie beim Rückzug.
- **Tatsächlich:** Gespeichert wird `result_type=PLAYED`. In Swiss zählt das Match als „gespielt“ statt als kampfloser Sieg, mit Auswirkung auf die Kennzahlen `played`/`walkovers` und die Buchholz-Behandlung. Ein echter Walkover entsteht nur, wenn das Team insgesamt zurückgezogen wird. Diese Admin-Aktion wirkt laut Code auf **alle** aktiven Turniere des Teams (`forfeit_team_in_active_tournaments`).

### B-05 – Liga mit geteiltem 1. Platz: keine Siegerehrung, keine Platzierungsübersicht
- **Modus:** Liga (Gleichstandsregel SHARED, Standard)
- **Schweregrad:** niedrig
- **Reproduktion:** Liga mit 4 Teams starten, alle Spiele 1:1 werten, Ergebnisse bestätigen, Detailseite öffnen.
- **Erwartet:** Ein beendetes Turnier zeigt einen Endstand bzw. die geteilten Plätze, analog zur Swiss-Platzierungskarte.
- **Tatsächlich:** `TournamentPodiumService.calculate` liefert `first/second/third = None`. Die Karte „Siegerehrung & Endstand“ fehlt; nur die Tabelle mit 4× Rang 1 wird angezeigt. `placements()` liefert die geteilten Ränge korrekt, sie werden aber nicht genutzt.

### B-06 – Spieler in zwei Teams desselben Turniers wird erst beim Start erkannt
- **Modus:** alle
- **Schweregrad:** niedrig
- **Reproduktion:** Team A (5 Mitglieder) anmelden. Team B anlegen, das einen Spieler aus A enthält, und anmelden. Danach Auslosung veröffentlichen.
- **Erwartet:** Die Anmeldung von B wird mit Hinweis abgelehnt, oder es wird sofort gewarnt.
- **Tatsächlich:** B wird mit Erfolgsmeldung angemeldet. Erst der Start scheitert mit der Sammelmeldung „Spiel, Veranstaltung, Archivstatus, Kapitän oder aktive Mitglieder prüfen; Spieler dürfen nur für ein Team antreten.“ Die Meldung nennt den betroffenen Spieler nicht. Hinweis: Die Doppelmitgliedschaft wurde per ORM erzeugt; ob die Team-UI sie überhaupt zulässt, wurde nicht geprüft.

### B-07 – DE mit Teilnehmerzahl knapp über einer Zweierpotenz: Loser Bracket voller leerer Freilos-Karten
- **Modus:** Double Elimination
- **Schweregrad:** niedrig (Darstellung)
- **Reproduktion:** DE mit 17 Teams starten, Detailseite öffnen, Ansicht „Turnierübersicht“ (Screenshot `shot_qa-double_elimination-n17_tree.png`).
- **Erwartet:** Leere Matches (beide Slots leer) werden ausgeblendet oder zusammengefasst.
- **Tatsächlich:** Das Bracket enthält 30 Freilos-Matches, darunter zahlreiche Karten „Freilos (BYE) – Freilos (BYE)“ in den Loser-Runden 1/2. Die Funktion ist korrekt, die Seite aber sehr lang und schwer lesbar.

## 5. Nicht getestet / offene Fragen

- **Nicht getestet:** Parallelität und Sperren (es gibt eigene Concurrency-Tests im Repo), Clan-Vermeidung, Mischen und Tauschen bei der Auslosung, explizite Seeds, Gleichstandsregeln `LEGACY` und `HEAD_TO_HEAD`, explizite Einstellung „1/2 Qualifikanten pro Gruppe“ (nur Automatik geprüft), Swiss-Freigabe von Wiederholungspaarungen, Aktion „Match starten“, Neustart-Assistent, Einladungen/Bewerbungen, Eventabschluss mit Teamarchivierung, mobile Darstellung und Barrierefreiheit, echter Redis-Cache und Mail-Versand.
- **Austritt, Kick und Abmeldung im laufenden Turnier** nur in SE geprüft. Die Sperre ist modusunabhängig implementiert (`Team.is_in_active_tournament`).
- **Offene Frage 1:** Welche Endplatzierung soll ein zurückgezogener Finalist in SE/DE erhalten (Platz 2, disqualifiziert/leer, oder Nachrücken des Halbfinal-Verlierers)? Das ist Voraussetzung für die Behebung von B-02.
- **Offene Frage 2:** Soll ein Rückzug pro Turnier möglich sein? Für Nicht-Swiss-Modi existiert nur die teamweite Admin-Aktion. Der Fall „ein Team in zwei Turnieren“ wurde nicht getestet.
- **Offene Frage 3:** Die Gruppenphase bildet unabhängig von N immer genau 2 Gruppen (bei 32 Teams 2 × 16, also 240 Gruppenspiele) und hat maximal Halbfinals. Ist das so gewollt?
- **Offene Frage 4:** In der Gruppenphase mit 4–7 Teams wird „Spiel um Platz 3“ stillschweigend ignoriert, weil es nur ein direktes Finale gibt. Das entspricht dem Hilfetext; eine Warnung beim Speichern wäre hilfreich.

## 6. Empfehlungen (priorisiert)

1. **B-01 beheben:** In 1v1-Turnieren `team_id` bzw. einen Ziel-Spieler auswerten, wenn eine Orga-Person anmeldet. Andernfalls die Anmeldung für Orga-Konten ohne eigenen Teilnahmewunsch mit klarer Meldung ablehnen. Regressionstest ergänzen.
2. **B-02/B-03:** Eine fachliche Regel für Rückzüge in KO-Modi festlegen (offene Frage 1), sie zeitunabhängig umsetzen und automatisch entschiedene Matches immer mit `BYE` bzw. `WALKOVER` typisieren. Die Regel in `docs/tournament-result-management.md` dokumentieren.
3. **B-04:** In der Ergebniseingabe eine Option „kampflos/Nichtantreten“ anbieten, die `WALKOVER` setzt, ohne das Team aus allen Turnieren zurückzuziehen. Optional einen Rückzug pro Turnier für alle Modi.
4. **B-05:** Für Liga (und allgemein bei geteilten Rängen) die vorhandenen `placements()` anzeigen, analog zur Swiss-Karte.
5. **B-06:** Doppelte Spieler bereits bei der Anmeldung prüfen und den betroffenen Spieler in der Meldung nennen.
6. **B-07:** Leere Freilos-gegen-Freilos-Matches in der Bracket-Ansicht ausblenden oder zusammenfassen.
7. **Umgebung:** Das Projekt-venv enthält Django 6.0.7, `requirements.txt` pinnt 6.0.9 (Sicherheitsupdate B1). `./start.sh` bzw. `scripts/check_requirements.py` vor dem nächsten Lauf ausführen. Die Testergebnisse oben beziehen sich auf 6.0.7.
8. **Aufräumen:** Die QA-Datenbank `entails_qa` bleibt für die Reproduktion bestehen. Nach Abschluss mit `docker exec entailsng_postgres psql -U entailsdemo -d postgres -c 'DROP DATABASE entails_qa'` entfernen.
