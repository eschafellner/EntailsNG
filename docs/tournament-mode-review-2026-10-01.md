# Einzelprüfung der sechs Turniermodi – 1. Oktober 2026

> **Historischer Prüfstand vor den Verbesserungen.** Die anschließend
> beauftragten Korrekturen und Erweiterungen sind umgesetzt; aktuelle Regeln,
> Installation und erfolgreiche Regressionen stehen im
> [Umsetzungsbericht](tournament-mode-improvements-2026-10-01.md).

Geprüft wurde der aktuelle Arbeitsstand einschließlich der Änderung zur
Sichtbarkeit von Entwürfen. Diese Prüfung verändert keine Anwendungslogik.
Die bisherigen Korrekturen aus `tournament-audit-2026-10-01.md` bleiben bestehen;
die folgenden Befunde ergänzen diesen früheren Bericht.

## Umfang und Ergebnis

- Bestehende Turniersuite: **228 Tests entdeckt, 216 bestanden, 12 auf SQLite
  übersprungen**, keine Fehler.
- JavaScript für Turnieransichten: **5 Tests bestanden**.
- Neue, einzeln ausgeführte Modussuiten: **38 Prüffälle, 31 bestanden,
  7 fehlgeschlagene fachliche Prüfkriterien**, keine unerwarteten Laufzeitfehler.
  Die sieben Fehlschläge beschreiben **sechs unterschiedliche Befunde**;
  der Schweizer Blocker wurde auf zwei Ebenen reproduziert.
- Die neuen Prüfkriterien enthalten neben Fehlerprüfungen auch gewünschte
  Verbesserungen: vollständige aktive FFA-Platzierungen und Snake-Seeding.
  Ein Fehlschlag eines solchen Kriteriums ist kein Beweis, dass diese Regel
  bereits als Produktanforderung vereinbart war.
- **52 komplette Turnierverläufe**: je Modus 2, 3, 4, 5, 6, 7, 8, 9 und
  16 Teilnehmer, Gruppenphase erst ab 4. Unterschiedliche Reihenfolgen der
  spielbereiten Matches und wechselnde Sieger; Double Elimination mit Reset.
  Schweizer Normalverläufe verwenden bis zu drei Runden; der kritische
  zusätzliche Fall verwendet vier Runden mit sechs Teilnehmern.
- Zusätzlich geprüft: Start- und Ergebnisrechte, atomare Ablehnung ungültiger
  Ergebnisse, Eventende, serverseitig gerenderte öffentliche Detailansichten,
  schreibfreie GETs, Ergebniskorrektur und Schutz gegen weitere Anmeldungen
  nach einer manuellen Statusänderung bei generiertem Turnierbaum.
- `manage.py check` und der Migrationsabgleich für `tournaments` sind erfolgreich.

| Modus | Zusätzliche Prüffälle | Bestanden | Fachliche Fehlschläge |
|---|---:|---:|---:|
| Single Elimination | 6 | 6 | 0 |
| Double Elimination | 6 | 5 | 1 |
| Liga | 7 | 5 | 2 |
| Gruppenphase + K.O. | 6 | 5 | 1 |
| Free For All | 6 | 5 | 1 |
| Schweizer System | 7 | 5 | 2 |

## 1. Single Elimination

**Ergebnis:** In den geprüften Abläufen kein neuer Funktionsfehler gefunden.
Start, ungerade Felder, Freilose, zufällige Ergebnisreihenfolge und Abschluss
funktionieren. Eine Siegerkorrektur vor Beginn des Finales ersetzt den
Finalteilnehmer korrekt; die normalen Rechte- und Statusprüfungen greifen.

**Verbesserungen:** Optionales Spiel um Platz 3 und eindeutige Kennzeichnung
von Halbfinale/Viertelfinale in Matchnamen. Die derzeit fehlende dritte
Platzierung ist eine bestehende Funktionsgrenze: Der Dienst erfindet ohne
ausgespieltes kleines Finale keinen dritten Platz.

## 2. Double Elimination

**Befund DE-01 – mittlere Priorität, reproduzierter Konsistenzfehler.**

Ein korrigiertes Grand Final hinterlässt ein offenes Reset-Match:

1. Zwei Teilnehmer starten; der Sieger des Winner Brackets erreicht das
   Grand Final in Slot 1.
2. Im Grand Final gewinnt zunächst Slot 2. Der Dienst erzeugt ein Reset-Match
   mit Status `READY`.
3. Vor Beginn des Resets korrigiert die Orga das Grand Final auf einen Sieg
   von Slot 1. Diese Korrektur ist nach den bestehenden Regeln erlaubt.
4. Das Turnier steht anschließend auf `FINISHED`, das Reset-Match bleibt
   `READY`. Es kann wegen des abgeschlossenen Turniers nicht gespielt werden.

**Ursache:** `tournaments/services/matches.py:418` beendet das Turnier beim
Sieg von Slot 1, bereinigt aber ein zuvor angelegtes Reset-Match nicht.
Die Sperre bei bereits begonnenem/gewertetem Reset verhindert diesen Fall
nicht, weil sie `READY` ausdrücklich zulässt.

**Empfehlung:** Einen noch ungespielten, durch die Korrektur überflüssigen
Reset atomar entfernen oder fachlich eindeutig annullieren. Gespielte Resets
weiterhin gegen eine solche Korrektur schützen.

Die regulären Verläufe einschließlich Freilosen und Reset bestehen. In den
Simulationsläufen haben nach dem Reset alle ausgeschiedenen Teams zwei
Niederlagen und der Sieger eine Niederlage.

**Weitere Verbesserung:** In der Oberfläche den Anlass für ein Reset erklären.
Die Einspeisung ins Loser Bracket vermeidet frühe Wiederholungsbegegnungen
nicht systematisch; eine bessere Kreuzverteilung wäre eine Fairness-Erweiterung.

## 3. Liga

**Befund LG-01 – hohe fachliche Priorität, reproduzierte Siegerermittlung.**

Ein zurückgezogenes Team kann weiterhin Meister werden:

1. Vier Teams starten. Team 1 gewinnt zwei seiner drei Partien mit 100:0.
2. Team 1 wird über den regulären Forfeit-Dienst zurückgezogen; sein
   `is_forfeited`-Status ist anschließend gesetzt.
3. Die restlichen Spiele werden abgeschlossen. Historische Siege und
   Tordifferenz halten Team 1 an der Tabellenspitze.
4. Das Podium führt dieses zurückgezogene Team als Sieger.

**Ursache:** `tournaments/services/standings.py:130` nimmt sämtliche
Anmeldungen ohne Rückzugsstatus in die Tabelle auf. Der Liga-Zweig in
`tournaments/services/podium.py:75` übernimmt diese Reihenfolge ungeprüft.
Anders als im Schweizer System ist ein Rückzug hier weder als eigener
Tabellenstatus sichtbar noch ein Ausschluss aus der finalen Platzierung.

**Empfehlung:** Rückzugsregeln verbindlich festlegen und konsistent anwenden.
Wenn ein Rückzug aus dem Turnier die Berechtigung auf eine Endplatzierung
aufhebt, historische Ergebnisse behalten, das Team als zurückgezogen
kennzeichnen und aus Siegerermittlung/Urkundenplatzierungen ausschließen.
Ob bereits gespielte Partien zählen, sollte separat festgelegt werden.

**Befund LG-02 – mittlere Priorität, reproduzierter Exportfehler.**

Nach einem vollständig ausgespielten Viererturnier hat Platz 4 eine eindeutige
Tabellenplatzierung, aber `certificate_rows()` liefert für ihn einen leeren
Platzierungstext.

**Ursache:** `TournamentPodiumService.placements()` in
`tournaments/services/podium.py:22` übernimmt bei der Liga lediglich die drei
Podiumsplätze. Die komplette Ligatabelle ist vorhanden, wird für diesen
Export jedoch nicht genutzt.

**Empfehlung:** Für die Liga alle feststehenden Tabellenplätze exportieren.

**Weitere Verbesserung:** Bei vollständigem Gleichstand entscheidet derzeit
der alphabetische Teamname (`standings.py:79`). Das ist im Code ausdrücklich
vorgesehen, kein neu gefundener Implementierungsfehler. Sportlich sinnvoller
können konfigurierbare Regeln, direkter Vergleich oder geteilte Ränge sein.

## 4. Gruppenphase + K.O.

**Ergebnis:** Gruppenspiele, Qualifikation und anschließende Finalphase
funktionieren in den geprüften vollständigen Verläufen. Die bisherigen Tests
zum Ausschluss zurückgezogener Qualifikanten bestehen ebenfalls.

**Befund GR-01 – niedrige Priorität, Seeding-Verbesserung.**

Bei acht Teilnehmern erhält Gruppe A die Seeds 1, 3, 5, 7 und Gruppe B die
Seeds 2, 4, 6, 8. Das ist eine alternierende Verteilung. Der Kommentar in
`tournaments/services/brackets.py:660` bezeichnet sie dagegen als
„Snake-Verteilung“. Eine balanciertere Snake-Verteilung wäre beispielsweise
1, 4, 5, 8 gegenüber 2, 3, 6, 7.

**Empfehlung:** Tatsächliches Snake-Seeding implementieren oder das aktuelle
Verfahren bewusst als alternierende Verteilung dokumentieren. Das ist ein
Fairness-/Regelthema, kein Absturz oder Beweis für eine falsche Qualifikation.

**Weitere Verbesserung:** Anzahl der Qualifikanten und Halbfinals konfigurierbar
machen. Derzeit gibt es bei 4–7 Teams direkt ein Finale der Gruppensieger,
erst ab 8 Teilnehmern zwei Halbfinals (`brackets.py:667`). Auch hier ist die
Schwelle eine bestehende feste Regel.

## 5. Free For All

**Ergebnis:** Start, vollständige Wertung, Rechte und Ablehnung mehrerer Sieger
funktionieren. Disqualifikationen und vollständige Ergebnisübermittlung sind
durch die bestehenden Tests abgesichert.

**Befund FF-01 – mittlere fachliche Priorität, Vollständigkeitslücke.**

Bei vier aktiven Teilnehmern kann die Orga lediglich einem Teilnehmer Rang 1
zuweisen und alle anderen Ränge leer lassen. Der Dienst setzt trotzdem Match
und Turnier auf `COMPLETED` beziehungsweise `FINISHED`.

**Ursache:** `tournaments/services/matches.py:499` erlaubt leere Ränge.
Der Abschluss prüft genau einen nicht disqualifizierten ersten Platz
(`matches.py:522`), aber keine vollständige Platzierung der aktiven Teilnehmer.
Alle Ergebniszeilen wurden in der Reproduktion übermittelt; die Prüfung gegen
fehlende Teilnehmer im POST wird daher korrekt erfüllt.

**Empfehlung:** Entscheiden, ob aktive Teilnehmer ohne Rang im Endstand zulässig
sind. Für vollständige Endstände entweder sämtliche aktiven Ränge verlangen
oder einen ausdrücklichen Status wie DNF/DQ anbieten. Punkte, Ränge und
Vollständigkeit sollten vor dem finalen Abschluss getrennt validiert werden.
Der aktuelle Hilfetext verlangt nur genau einen Rang 1; deshalb ist dies
eine fachliche Verbesserung und kein Widerspruch zu einer bereits strengen
UI-Regel. Die Orga kann fehlende Ränge bei noch laufendem Event nachtragen.

## 6. Schweizer System

**Befund SW-01 – hohe Priorität, reproduzierter Turnierblocker.**

Ein reguläres Turnier mit sechs Teilnehmern und vier Runden kann ohne Rückzüge
nach Runde 3 feststecken. Vier Runden entsprechen dem Modellstandard; die
Startprüfung lässt diese Konfiguration zu.

Reproduktion mit festen Seeds 1–6, Paarungszufallswert 0 und wechselnden
Siegern aus `random.Random(0)`:

- Nach drei regulär abgeschlossenen Runden sind keine Teams zurückgezogen.
- Die bereits gespielten Paare sind
  `(1,2), (1,3), (1,4), (2,5), (2,6), (3,5), (3,6), (4,5), (4,6)`.
- Noch ungespielte Begegnungen liegen in zwei getrennten Dreiergruppen
  `{1,5,6}` und `{2,3,4}`. Ohne Wiederholung ist daraus keine vollständige
  vierte Runde möglich.
- Die Vorschau der vierten Runde endet mit „Keine vollständige Paarung ohne
  Wiederholungen möglich“. Runde 4 wird nicht teilweise angelegt; dieser
  Transaktionsschutz funktioniert. Das Turnier bleibt aber laufend und kann
  über den regulären Ablauf nicht beendet werden.

**Ursache:** `SwissPairingService.pair()` optimiert in
`tournaments/services/swiss.py:138` nur die aktuelle Runde. Es prüft nicht,
ob die restlichen vorgesehenen Runden anschließend noch vollständig paarbar
sind. Die Grenze N−1/N in `swiss.py:169` garantiert das für eine schrittweise
Auslosung nicht. Der Blocker tritt somit auch ohne die bereits dokumentierten
problematischen Rückzüge auf.

**Nachweis:** Sowohl direkt mit dem Paarungsdienst als auch durch echte
gespeicherte Runden, signierte Vorschau/Freigabe und normale Ergebniserfassung
reproduziert.

**Empfehlung:** Paarungen mit Blick auf die verbleibenden Runden absichern,
oder einen ausdrücklich geregelten Rettungsweg anbieten, etwa eine genehmigte
Wiederholungsbegegnung beziehungsweise einen vorzeitigen fachlichen Abschluss.
Ein einfaches erneutes Auslosen der vierten Runde löst diesen konkreten Fall
nicht: Die erlaubten restlichen Begegnungen bilden bereits keine vollständige
Paarung mehr. Regeländerungen und resultierende Platzierungen müssen sichtbar
und protokolliert bleiben.

Freilose, Remis, Tokenprüfung, Korrektursperren und geteilte Platzierungen
bestehen in den vorhandenen Tests; die zusätzlichen normalen Drei-Runden-
Verläufe bestehen ebenfalls.

## Priorisierung

1. SW-01: Fortsetzung eines zulässigen Turniers kann unmöglich werden.
2. LG-01: Rückzugsstatus und finale Siegerermittlung konsistent regeln.
3. DE-01: Korrektur des Grand Finals und Lebenszyklus des Resets zusammenführen.
4. LG-02: Vollständige bekannte Ligaplatzierungen für Urkunden ausgeben.
5. FF-01: Fachliche Vollständigkeitsregel für den FFA-Abschluss festlegen.
6. GR-01 sowie optionale Tie-Break-/Qualifikationsregeln: Fairness und Transparenz.

## Nachweise, Wiederholung und Grenzen

Die zusätzlichen Modusprüfungen laufen auf einer von Django erzeugten und nach
dem Lauf entfernten Testdatenbank. Die App-Datenbank wurde nicht migriert oder
mit Turnierdaten befüllt.

```powershell
$env:DB_ENGINE = 'sqlite'
$env:DEBUG = 'True'
$env:SECRET_KEY = 'local-mode-review-test-key'
$env:ALLOWED_HOSTS = 'localhost,127.0.0.1,testserver'
.\.venv\Scripts\python.exe manage.py test tournaments --noinput
node --test scripts/tests/tournaments.test.cjs
.\.venv\Scripts\python.exe scripts/tournament_mode_review.py
```

Das zusätzliche Audit-Skript ist kein Bestandteil der regulären Testdiscovery.
Beim ursprünglichen Audit lieferte es wegen der dokumentierten Fehlschläge
Exitcode 1. Die historischen Detailergebnisse liegen unverändert in
`docs/tournament-mode-review-results-2026-10-01.json`. Das Skript prüft inzwischen
die umgesetzten Regeln einschließlich genehmigter Schweizer Ausnahmen und
liefert bei erfolgreicher Regression Exitcode 0; aktuelle Ergebnisse stehen in
`docs/tournament-mode-improvements-results-2026-10-01.json`.

Lokal ist keine PostgreSQL-Instanz beziehungsweise kein entsprechendes
Serverwerkzeug verfügbar. Die zwölf Tests für echte Zeilensperren wurden deshalb
übersprungen. Dieser Lauf belegt keine fehlerfreie Verarbeitung konkurrierender
Anfragen unter PostgreSQL. Der vorhandene PostgreSQL-CI-Job wurde hier nicht
ausgeführt. Die Frontendprüfung umfasst gerenderte Django-Seiten und vorhandene
JavaScript-Tests; es gab keinen neuen manuellen Testlauf in echten Browsern.

Keine neuen Fehler in diesen Prüfungen bedeutet keine Garantie, dass alle
untersuchten Modi in sämtlichen möglichen Abläufen fehlerfrei sind.
