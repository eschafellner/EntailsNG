# Verbesserungen der sechs Turniermodi – 1. Oktober 2026

Die Befunde aus der [Einzelprüfung](tournament-mode-review-2026-10-01.md) und die
anschließend beauftragten Erweiterungen sind umgesetzt. Der historische Bericht
und seine JSON-Ergebnisse dokumentieren den Zustand vor diesen Änderungen.

## Änderungen je Modus

| Modus | Korrekturen und Erweiterungen |
|---|---|
| Single Elimination | Optionales Spiel um Platz 3; klare Namen für Viertelfinale, Halbfinale und Finale. Das Turnier endet erst nach Finale und kleinem Finale, unabhängig von deren Reihenfolge. Freilose und Aufgaben werden berücksichtigt. |
| Double Elimination | Eine Grand-Final-Korrektur entfernt ein dadurch überflüssiges, noch ungespieltes Reset-Match atomar. Begonnene oder gewertete Resets bleiben geschützt. Verlierer aus mittleren Winner-Bracket-Runden werden über Kreuz eingespeist; die Vorschau entspricht dem echten Baum. Der Anlass für den Reset wird im Frontend erklärt. |
| Liga | Zurückgezogene Teams behalten ihre historischen Ergebnisse, stehen als zurückgezogen am Tabellenende und erhalten keinen Rang oder Urkundenplatz. Alle aktiven Tabellenplätze werden exportiert. Gleichstandsregeln sind konfigurierbar. |
| Gruppenphase + K.O. | Echtes Snake-Seeding: bei acht Seeds Gruppe A = 1/4/5/8, Gruppe B = 2/3/6/7. Ein oder zwei Qualifikanten pro Gruppe einstellbar, optionales kleines Finale bei Halbfinals. Gruppenspieltage und K.O.-Runden werden in der Ansicht getrennt dargestellt. |
| Free For All | Für den Abschluss benötigt jeder aktive Teilnehmer einen Rang. Disqualifizierte Teilnehmer dürfen ohne Rang bleiben. Genau ein aktiver Rang 1 ist weiterhin erforderlich; ungültige Eingaben verändern keine Ergebnisse. Hilfetext entsprechend angepasst. |
| Schweizer System | Blockierte Paarungen erhalten einen ausdrücklichen Rettungsweg mit Ausnahmevorschau und gesonderter Orga-Freigabe. Die Regeländerung bleibt im Rundenprotokoll und im Frontend sichtbar. |

## Einstellungen und bestehende Turniere

Im Django-Admin stehen vor der Generierung des Turnierbaums zur Verfügung:

- **Spiel um Platz 3:** Standard aus; wirkt bei Single Elimination mit mindestens
  zwei Halbfinals und Gruppenphase mit Halbfinals. Bei zwei SE-Teilnehmern oder
  einer Gruppenphase mit direktem Finale wird kein kleines Finale angelegt.
- **Qualifikanten pro Gruppe:** Standard automatisch; wie bisher bei 4–7 Teams
  je ein Qualifikant, ab acht je zwei. Explizit ein Qualifikant führt direkt ins
  Finale; zwei führen über zwei Halbfinals ins Finale.
- **Gleichstandsregel für Liga und Gruppen:**
  - Historisch: Punkte → Score-Differenz → erzielte Scores → Teamname.
  - Geteilte Plätze: Punkte → Score-Differenz → erzielte Scores; gleiche Werte
    ergeben in der Liga beispielsweise die Ränge 1, 1, 3.
  - Direkter Vergleich: Punkte → Mini-Tabelle der punktgleichen aktiven Teams
    (Punkte, Score-Differenz, erzielte Scores) → Gesamtdifferenz → Gesamtscores;
    gleiche Werte teilen den Ligaplatz. Die Mini-Tabelle greift erst, wenn alle
    Begegnungen innerhalb dieser punktgleichen Teilmenge abgeschlossen sind.

Neue Turniere verwenden standardmäßig geteilte Plätze. Die Migration setzt
sämtliche bereits vorhandenen Turniere auf die historische Gleichstandsregel.
So ändern sich deren angekündigte Regeln und Endstände nicht durch das Update.
Für die Gruppenqualifikation entscheidet bei verbleibendem Gleichstand der
Seed; historische Turniere verwenden weiterhin den Teamnamen. Das Frontend
zeigt die gewählte Ranglistenregel. Ein geteilter erster Platz erzeugt keinen
willkürlichen einzelnen Meister im älteren Podiumsformat; Tabelle und Urkunden
weisen die geteilten Ränge aus.

Nach der Generierung sind die drei neuen Einstellungen serverseitig und im
Admin gesperrt. Ein zulässiger vollständiger Bracket-Reset macht sie wieder
editierbar. Bereits generierte Bäume werden nicht nachträglich umgebaut;
Snake-Seeding, Kreuzverteilung und kleine Finals gelten für neu generierte Bäume.

## Schweizer Ausnahmefreigabe

Die normale Vorschau schließt frühere Begegnungen und wiederholte Freilose
weiterhin aus. Die zulässige Rundenanzahl garantiert bei der schrittweisen
Auslosung allerdings keine vollständige spätere Paarung. Der reproduzierte
Fall mit sechs Teilnehmern und vier Runden bleibt daher im strengen Verfahren
nach Runde 3 mathematisch blockiert.

Bei genau diesem Paarungsproblem bietet die Oberfläche
**Ausnahmevorschau mit Wiederholungen prüfen** an:

1. Die Orga öffnet die Ausnahmevorschau. Auch hier wird zuerst eine strenge
   Paarung gesucht; eine bereits mögliche normale Runde wird nicht gelockert.
2. Falls erforderlich, wird eine vollständige Paarung mit möglichst wenigen
   Wiederholungsbegegnungen berechnet. Wiederholte Freilose werden nachrangig
   berücksichtigt, wenn kein zuvor berechtigter Freilos-Kandidat eine Paarung
   ermöglicht. Ausnahmen sind in den Paarungskarten markiert.
3. Die Orga muss die Ausnahme über eine zusätzliche Checkbox ausdrücklich
   genehmigen. Der Server prüft die Zustimmung, auch bei manipulierten POSTs.
4. Veröffentlichung speichert Zeitpunkt, freigebende Person, Eingabe-Prüfsumme,
   Ranglisten-Snapshot und `repeat_pairings_approved`. Im öffentlichen
   Rundenprotokoll bleibt der Hinweis auf die Ausnahme erhalten.

Die Ausnahme ist Teil des signierten Vorschau-Tokens. Ergebnisse oder Rückzüge
nach der Vorschau, ein abgelaufenes Token und eine bereits veröffentlichte Runde
verhindern eine Freigabe mit diesem Token. Rechte, CSRF, Transaktion und Sperren
bleiben erhalten. Frühere Ergebnisse werden nicht umgeschrieben. Mit weniger
als zwei aktiven Teilnehmern gibt es weiterhin keine reguläre weitere Runde.

Die Lösung sichert die Fortsetzung durch eine genehmigte Regelabweichung; sie
plant nicht sämtliche zukünftigen Runden im Voraus. Die Orga entscheidet, ob
eine solche Ausnahme für ihr Turnier fachlich angemessen ist.

## Installation

```sh
python manage.py migrate
python manage.py seed_translations
python manage.py collectstatic --noinput
```

Danach die Web-Prozesse neu starten. Neue Migration:
`tournaments.0010_format_improvements`. Sie ergänzt Turniereinstellungen und
das persistente Schweizer Ausnahmeprotokoll. Diese lokale Umsetzung hat die
App-Datenbank nicht migriert und kein Deployment durchgeführt.

## Nachweise

- Größerer Lauf für `tournaments`, `media_designer` und `events`:
  **362 Tests entdeckt, 350 bestanden, 12 PostgreSQL-Fälle auf SQLite
  übersprungen**, keine Fehler. Zu diesem Zeitpunkt waren 17 neue
  Verbesserungstests enthalten.
- Anschließend ergänzende Regressionen für getrennte Gruppen-/K.O.-Titel,
  erschöpfte Schweizer Freilose und den Erhalt historischer Ranglistenregeln
  bei der Datenmigration: **75 von 75 gezielten Tests bestanden**
  (`test_format_improvements`, `test_draft_visibility`, `test_audit`), darunter
  alle **20 neuen Verbesserungstests**.
- Separate Einzelprüfung aller sechs Modi: **38 von 38 bestanden**. Enthält
  vollständige Turnierverläufe mit 2–16 Teilnehmern, ungerade Felder, Freilose,
  Rückzüge, Ergebniskorrekturen, Rechte, Urkunden und gerenderte Detailseiten.
  Die Schweizer Paarungsprüfung simuliert zusätzlich 200 Auslosungs-/Ergebnis-
  Startwerte und verwendet bei Bedarf den ausdrücklich genehmigten Rettungsweg.
- **5 JavaScript-Tests bestanden**; `manage.py check` ohne Fehler und
  `makemigrations tournaments --check --dry-run` ohne fehlende Migration.

```powershell
$env:DB_ENGINE = 'sqlite'
$env:DEBUG = 'True'
$env:SECRET_KEY = 'local-format-improvements-test'
.\.venv\Scripts\python.exe manage.py test tournaments media_designer events --noinput
.\.venv\Scripts\python.exe manage.py test tournaments.test_format_improvements tournaments.test_draft_visibility tournaments.test_audit --noinput
.\.venv\Scripts\python.exe scripts/tournament_mode_review.py
node --test scripts/tests/tournaments.test.cjs
```

Die zusätzlichen Modussuiten verwenden eine temporäre Testdatenbank und
schreiben ihre aktuellen Ergebnisse nach
[`tournament-mode-improvements-results-2026-10-01.json`](tournament-mode-improvements-results-2026-10-01.json).
Der PostgreSQL-CI-Job umfasst jetzt auch die neuen Verbesserungs- und
Entwurfstests. Lokal fehlt eine PostgreSQL-Instanz: echte konkurrierende
Zeilensperren wurden hier nicht geprüft, und der CI-Job wurde nicht gestartet.
Die Frontendprüfung verwendet gerenderte Django-Seiten und JavaScript-Tests;
ein neuer manueller Browserlauf gehört nicht zu diesen Nachweisen.
