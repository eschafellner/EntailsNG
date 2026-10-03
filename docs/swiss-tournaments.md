# Schweizer Turniere

Die anschließende modulweite Prüfung und die aktuellen Testergebnisse sind im
[Prüfbericht vom 1. Oktober 2026](tournament-audit-2026-10-01.md) dokumentiert.
Die spätere [Verbesserungsrunde](tournament-mode-improvements-2026-10-01.md)
ergänzt einen explizit genehmigten Rettungsweg für blockierte Auslosungen.

Stand: 1. Oktober 2026. Das Schweizer System ist der sechste Turniermodus und
funktioniert sowohl für Einzelspieler als auch für Teams. Es endet mit einer
Rangliste; eine anschließende K.-o.-Phase gehört nicht zu diesem Modus.

## Bedienung durch die Orga

1. Im Django-Admin ein Turnier mit Modus **Schweizer System** anlegen. Rundenanzahl
   und die Option **Unentschieden erlauben** vor dem Start einstellen. Standard:
   vier Runden, keine Unentschieden. Die Anmeldung funktioniert wie bisher.
2. Auf der Turnierseite **Runde 1 vorbereiten** öffnen. Die Vorschau zeigt alle
   Paarungen und gegebenenfalls das Freilos. **Paarungen veröffentlichen und Runde
   freigeben** startet das Turnier und schließt die Anmeldung.
3. Ergebnisse über die bestehenden Matchdialoge erfassen. Teilnehmer können ihre
   eigene Niederlage und – bei aktivierter Option – ein Unentschieden bestätigen.
   Eigene Siege können weiterhin nur von der Turnierleitung eingetragen werden.
4. Sobald sämtliche Matches der aktuellen Runde abgeschlossen sind, erscheint
   für die Turnierleitung **Nächste Runde auslosen**. Paarungen prüfen und explizit
   veröffentlichen. Eine neue Runde wird nie automatisch angelegt.
5. Nach dem letzten Ergebnis der letzten vorgesehenen Runde wird das Turnier
   automatisch beendet. Abschlusstabelle, geteilte Podiumsplätze und Urkunden
   verwenden dieselbe Rangfolge. Schweizer Urkunden haben auch jenseits der ersten
   drei Plätze einen Rang; zurückgezogene Teilnehmer erhalten keinen Rang.

Staff, Turnieradmin und Turniersupport haben die bestehenden Orga-Rechte.
Die Django-Admin-Aktion zum Turnierstart verweist bei Schweizer Turnieren auf die
Frontend-Vorschau. Rundenprotokolle sind im Admin lesbar.

## Paarungen und Grenzen

- Mindestens zwei aktive Teilnehmer. Rundenanzahl 1 bis 100; bei gerader Anzahl N
  höchstens N−1, bei ungerader Anzahl höchstens N Runden.
- Manuelle Seeds werden zuerst berücksichtigt. Teilnehmer ohne Seed erhalten
  eine zufällige Startreihenfolge. Mit Runde 1 werden Teilnehmer, Seeds,
  Rundenanzahl, Unentschieden-Regel, Spiel und Veranstaltung festgeschrieben.
- Paarungen minimieren die Punkteunterschiede über die gesamte Runde. Schon
  veröffentlichte Begegnungen sind ausgeschlossen, auch kampflose Begegnungen.
  Seed-Abstände und ein gespeicherter Zufallswert entscheiden weitere Gleichstände.
  Dies ist eine E-Sports-Auslosung, kein zertifiziertes FIDE-Dutch-Verfahren.
- Bei ungerader Anzahl erhält nach Möglichkeit der niedrigstplatzierte berechtigte
  Teilnehmer ein Freilos. Wer bereits ein Freilos oder einen kampflosen Sieg hatte,
  erhält kein weiteres Freilos. Falls das verbleibende Feld damit nicht vollständig
  gepaart werden kann, wird der nächste berechtigte Kandidat geprüft.
- Eine spätere vollständige Paarung kann auch ohne Rückzüge unmöglich werden.
  Bei fehlender Paarung oder fehlendem Freilos-Kandidaten legt die Vorschau keine
  Teilrunde an. Sie bietet eine Ausnahmevorschau mit möglichst wenigen
  Wiederholungen, die eine zusätzliche ausdrückliche Orga-Zustimmung erfordert.
  Die Ausnahme ist an das signierte Token gebunden und bleibt im Rundenprotokoll
  sichtbar. Mit weniger als zwei aktiven Teilnehmern bleibt die weitere Runde
  gesperrt. Eine Absage im Admin erzeugt keine reguläre Abschlusstabelle.

## Punkte, Feinwertung und Rückzüge

Sieg: 3, Unentschieden: 1, Niederlage: 0. Freilos oder kampfloser Sieg: 3.
Freilose und kampflose Ergebnisse haben eine eigene Ergebnisart und keine
erfundenen Matchscores. Die S/U/N-Anzeige zählt auch kampflose Siege/Niederlagen;
Freilose sind zusätzlich separat ausgewiesen.

Die Rangfolge ist **Punkte → Buchholz → Sonneborn-Berger**:

- Bei gespielten Matches ist die Gegnerstärke dessen aktuelle Punktzahl.
  Für bereits zurückgezogene Gegner wird jede veröffentlichte Runde ohne Match
  mit einem neutralen Punkt berücksichtigt, ausschließlich für die Feinwertung.
- Bei Freilosen wird ein virtueller Gegner mit `min(eigene Punkte, Rundenanzahl)`
  berücksichtigt. Bei kampflosen Ergebnissen gilt
  `min(eigene Punkte, angepasste Punkte des vorgesehenen Gegners)`.
- Buchholz ist die Summe dieser Gegnerstärken. Sonneborn-Berger summiert je Match
  `Gegnerstärke × erzielte Turnierpunkte` (3/1/0). Diese Skalierung ist auf die
  Punktwertung des Veranstaltungsmoduls angepasst.
- Bei identischen drei Werten teilen Teilnehmer den Rang, beispielsweise
  1, 1, 3. Der Seed stabilisiert lediglich die Anzeigereihenfolge und erzeugt
  keinen künstlichen Sieger. Zwischenstände sind vorläufig.

Während des Turniers kann die Orga im Bereich **Teilnehmer zurückziehen** einen
Teilnehmer mit Begründung zurückziehen. Ein offenes Match wird als kampfloser Sieg
des aktiven Gegners gewertet. Bereits abgeschlossene Ergebnisse bleiben erhalten;
zukünftige Runden berücksichtigen den Teilnehmer nicht mehr. Der Rückzug ist
endgültig. Die allgemeine Team-Aufgabe verwendet dieselbe Schweizer Logik.

Historische Teams werden bei erzwungener Team-Löschung archiviert. Einzelne
historische Anmeldungen und Teams sind gegen Löschung geschützt; das reguläre
Löschen eines gesamten Turniers kann dessen eigene Historie weiterhin entfernen.

## Konsistenz und technische Integration

Die Vorschau schreibt keine Runden oder Matches. Ihr signiertes Token ist zehn
Minuten gültig und bindet Freigabe an Turnier, Rundennummer, Startwert, Teilnehmer
und Ergebnisse. Änderungen oder eine bereits erfolgte Freigabe machen die Vorschau
ungültig. Eine erneute Vorschau ist dann erforderlich.

Ergebnisse der aktuellen Runde können durch die Orga korrigiert werden, bis die
nächste Runde veröffentlicht wird. Ein abgeschlossenes Turnier ist gesperrt.
Freilose und kampflose Ergebnisse können nicht als gespieltes Match überschrieben
werden. Ein Reset ist regulär nur vor dem ersten gespielten/gewerteten Match möglich.

Schreibaktionen sperren **Event → Turnier → Anmeldung/Match** in einer Transaktion.
Eindeutige Datenbank-Constraints schützen Rundennummer, Matchnummer je Runde und
die einmalige Teilnahme eines Teams je Runde. `SwissRound` hält Zeitpunkt, Orga,
Eingabe-Prüfsumme, Ranglisten-Snapshot und eine ausdrückliche Ausnahmefreigabe;
`SwissRoundEntry` hält die Teilnahme.
Die Auslosung verwendet NetworkX für ein globales Matching.

## Installation und Prüfung

```sh
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_translations
python manage.py collectstatic --noinput
```

Danach die Web-Prozesse neu starten. Schweizer Grundfunktionen benötigen
`tournaments.0009_swissroundentry_tournament_swiss_allow_draws_and_more`, die
Ausnahmefreigabe zusätzlich `tournaments.0010_format_improvements`. Bestehende
Turniere werden nicht in Schweizer Turniere umgewandelt. Neue Systemtexte können
wie bisher im Admin angepasst werden.

```sh
python manage.py test tournaments --noinput
python manage.py makemigrations tournaments --check --dry-run
```

Die Schweizer Tests prüfen komplette gerade/ungerade Turniere, Punkte und
Feinwerte, Freilose, Rückzüge, Korrektursperren, Vorschau-Manipulation und -Ablauf,
Rechte/CSRF, Historienerhalt, Admin-Sperren und Urkunden mit geteilten Rängen.
Eine zusätzliche Paarungsprüfung deckt Felder mit 2, 3, 7, 8, 16, 32 und 64
Teilnehmern ab.

Abschließender lokaler Turnierlauf: 144 Tests entdeckt, 139 erfolgreich,
fünf PostgreSQL-Tests übersprungen. Darin sind 32 neue Schweizer Tests enthalten.
`manage.py check`, der Migrationsabgleich für `tournaments` und `git diff --check`
sind erfolgreich.

Fünf separate PostgreSQL-Tests prüfen doppelte Freigaben, die beiden Reihenfolgen
von Korrektur/Freigabe, Rückzug/Freigabe und gleichzeitig eintreffende letzte
Ergebnisse. Sie sind in der PostgreSQL-CI eingebunden und werden unter SQLite
übersprungen. Lokal war PostgreSQL nicht verfügbar; die CI wurde hier nicht
ausgeführt.

Frontend-Kontrolle mit separater SQLite-Testdatenbank: Vorschau, erste und zweite
Freigabe, Ergebniseingabe inklusive Unentschieden, Korrektursperre und Rangliste
auf Desktop sowie bei 390 × 844 Pixeln. Die Rangliste scrollt auf kleinen Geräten
innerhalb ihres Bereichs.

Beim Regressionstest über `tournaments users events media_designer` liefen 346
Tests: 340 erfolgreich, fünf PostgreSQL-Tests übersprungen, ein bekannter
Windows-Fehler in `test_uploaded_background_is_saved_and_used_for_export`
(offene PNG-Datei beim Aufräumen des temporären Verzeichnisses).
