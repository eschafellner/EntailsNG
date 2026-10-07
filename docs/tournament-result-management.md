# Ergebniseingabe und Korrekturen

Stand: 7. Oktober 2026. Die Ergebnisverwaltung verwendet für Frontend und
Django-Backend dieselben Services und Sperren.

## Bedienung

Im Backend ein Turnier öffnen und **Ergebnisse verwalten** wählen. Die Seite
zeigt alle Matches mit Eingabeformular, Startaktion und einem konkreten
Sperrgrund. Die bisherigen Matchformulare bleiben nutzbar; der Link
**Ergebnisse verwalten** führt auch von einem FFA-Match zur gemeinsamen
Wertungsmaske. In der Matchliste des Turnierformulars sind die einzelnen
Matchformulare ebenfalls verlinkt.

Mitarbeiter benötigen im Backend Änderungsrechte für Turniere und
Turnier-Matches. Im Frontend behalten Turnieradmin, Support und Mitarbeiter
ihre bisherigen Orga-Rechte. Teilnehmer können weiterhin nur ihre eigene
Niederlage bzw. ein erlaubtes Unentschieden erstmalig bestätigen; Korrekturen,
Matchstart, Phasenfreigabe und Abschlussbestätigung gehören zur Turnierleitung.

Vor dem tatsächlichen Beginn eines Spiels **Match starten** ausführen.
Dadurch werden Änderungen an den Teilnehmern dieses Matches gesperrt. Eine
Ergebniseingabe ohne vorherigen Start bleibt möglich; nach der Wertung greift
dieselbe Sperre für Änderungen an den Teilnehmern. Die Anwendung kann einen
realen Spielbeginn ohne diese Aktion nicht erkennen.

Bei Korrekturen ist eine Begründung erforderlich. Für FFA werden Ränge,
Punktestände, Disqualifikationen und Notizen sämtlicher Teilnehmer gemeinsam
übermittelt. Genau ein aktiver Teilnehmer benötigt Rang 1; geteilte andere
Platzierungen bleiben möglich. Zurückgezogene Teilnehmer bleiben disqualifiziert.

## Grenzen nach Modus

- **Single/Double Elimination:** Punktestände können mit unverändertem Sieger
  auch nach begonnenen Folgematches korrigiert werden. Ein Siegerwechsel setzt
  voraus, dass alle betroffenen Folgematches ungespielt sind. Der Service baut
  die betroffene Folge einschließlich automatischer Freilose, Verliererpfade,
  kleinem Finale und dynamischem Grand-Final-Reset atomar neu auf. Andere Matches
  behalten ihre Ergebnisse. Das betrifft beide Pfade eines DE-Matches.
- **Schweizer System:** Ergebnisse der aktuellen Runde bleiben bis zur
  Veröffentlichung der Folgerunde korrigierbar. Eine Korrektur macht vorhandene
  Auslosungsvorschauen ungültig. Die letzte Runde bleibt während der
  Ergebnisprüfung korrigierbar.
- **Liga:** Frühere Spieltage können bis zur Abschlussbestätigung geändert
  werden. Tabellen, Gleichstandsregeln und Platzierungen werden aus den
  aktuellen Ergebnissen berechnet.
- **Gruppenphase:** Nach allen Gruppenergebnissen stehen die K.-o.-Paarungen zur
  Prüfung bereit. Vor **K.-o.-Phase freigeben** können sie durch Korrekturen noch
  geändert werden. Die Freigabe sperrt Qualifikation und Setzung; spätere
  Gruppenkorrekturen sind nur erlaubt, wenn diese unverändert bleiben.
  K.-o.-Spiele können erst nach dieser Freigabe gestartet oder gewertet werden.
- **FFA:** Vollständige Wertung und Korrektur im Backend und Frontend bis zur
  endgültigen Abschlussbestätigung.

Freilose und kampflose Wertungen können nicht über die reguläre
Ergebniseingabe in ein gespieltes Match umgewandelt werden. Abgesagte Turniere,
beendete/abgesagte Veranstaltungen und bestätigte Endergebnisse bleiben gesperrt.
Eine Veränderung bereits gestarteter Folgespiele wird nicht automatisch
zurückgerollt; für einen vollständigen Neustart gibt es weiterhin die separate
Neustartaktion mit Erhalt des Originals.

## Ergebnisprüfung und Abschluss

Das letzte Ergebnis setzt das Turnier auf **Ergebnisse prüfen**. Die Tabellen
und Ergebnisse sind vorläufig. Die Orga prüft sie und wählt anschließend
**Ergebnisse endgültig bestätigen**. Erst diese Aktion setzt **Beendet**,
speichert Bearbeiter und Zeitpunkt und gibt endgültiges Podium und Urkunden
frei. Auch ein eventuell vorgesehenes kleines Finale und sämtliche Schweizer
Runden müssen gewertet sein. Der Eventabschluss verlangt weiterhin beendete
oder abgesagte Turniere und bleibt während der Ergebnisprüfung gesperrt.

Die reguläre Turnierbearbeitung erlaubt keinen direkten Wechsel auf den
Prüfstatus oder auf Beendet und keine Wiederöffnung bestätigter Turniere. Eine
Absage während der Ergebnisprüfung bleibt möglich.

## Historie und gleichzeitige Aktionen

Die Orga sieht eine Änderungshistorie mit Bearbeiter, Zeitpunkt, Begründung,
altem und neuem Ergebnis. Teilnehmernamen und die vollständige FFA-Wertung
werden mit gespeichert. Änderungen an abhängigen Matches, Matchstarts,
Phasenfreigabe und Abschlussbestätigung werden ebenfalls protokolliert.
Im Django-Admin sind die Ergebnisprotokolle ausschließlich lesbar.

Ergebniseingaben, Matchstarts und K.-o.-Freigaben aus veralteten Formularen werden anhand einer
Prüfsumme abgelehnt. Die Abschlussbestätigung bezieht sich auf die angezeigten
Ergebnisse; zwischenzeitliche Korrekturen erfordern ein Neuladen und erneutes
Prüfen. Schreibaktionen verwenden die bestehende Sperrreihenfolge
**Event → Turnier → Match**. Die Sperrbedingungen werden beim Speichern erneut
geprüft. Schweizer Veröffentlichungen verwenden weiterhin signierte Vorschauen.

## Installation und Bestand

```sh
python manage.py migrate
python manage.py seed_translations
python manage.py collectstatic --noinput
```

Anschließend die Webprozesse neu starten. Erforderlich ist Migration
`tournaments.0014_tournament_playoffs_released_at_and_more`.

Bereits beendete Turniere behalten ihren Status und ihre Sperren. Es werden
keine historischen Bestätigungszeitpunkte oder Bearbeiter erfunden. Bestehende
Gruppenturniere mit bereits besetzten K.-o.-Paarungen behalten diese als
freigegeben; der bisherige Änderungszeitpunkt wird als Bestandsmarkierung
übernommen. Die neue Änderungshistorie beginnt mit der Installation und wird
nicht rückwirkend rekonstruiert.

## Prüfung

Am 7. Oktober 2026 bestanden alle **1.058 Tests** der vollständigen
PostgreSQL-Suite. Der anschließende gezielte Lauf bestand **29 Tests**,
einschließlich zusätzlicher Regressionen für die Sichtbarkeit der
Korrekturaktion, das Schweizer Adminformular während der Ergebnisprüfung und
veraltete K.-o.-Freigaben in beiden Oberflächen und bei gleichzeitigen Änderungen.
Alle **24 JavaScript-Tests**, Django-Systemprüfung und Migrationsabgleich
bestanden ebenfalls, ebenso die **38 zusätzlichen Modusprüfungen** aus
`scripts/tournament_mode_review.py`. Backend-Eingabe, Siegerwechsel, Abschlussbestätigung und
FFA-Korrektur wurden zusätzlich im Browser mit einer isolierten Testdatenbank
geprüft.

Neue Regressionen: `tournaments.test_result_management` und
`tournaments.test_result_concurrency`. Sie prüfen Korrekturen und Finalprüfung,
alle sechs Modi, Backend/Frontend, Rechte und CSRF, historische Sonderfälle,
veraltete Formulare, automatische Freilosketten in ungeraden DE-Feldern,
Walkover-Sperren sowie Parallelität zwischen Korrektur, Matchstart,
Phasenfreigabe und Abschlussbestätigung. Die vorhandenen Tests für Urkunden,
Eventabschluss und komplette Turnierläufe verwenden die ausdrückliche
Abschlussbestätigung.

```sh
python manage.py test --noinput
python manage.py makemigrations --check --dry-run
```
