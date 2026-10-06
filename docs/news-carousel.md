# News-Karussell und Titelbilder

> Seit 5. Oktober 2026 verwendet das Projekt ausschließlich PostgreSQL, auch lokal und für Tests. Testbefehle benötigen eine konfigurierte PostgreSQL-Verbindung; erwähnte SQLite-Ergebnisse sind historische Prüfstände vor der Umstellung. Die vollständige PostgreSQL-Suite einschließlich Parallelität und Backups läuft gemeinsam in CI.

Stand: 5. Oktober 2026.

## Darstellung und Bedienung

Das Dashboard zeigt bis zu fünf veröffentlichte News als horizontal scrollbare
Karten. Auf Desktop stehen Bild und Text nebeneinander; bis 900 Pixel Breite
stehen sie untereinander. Ein Ausschnitt der nächsten Karte zeigt die mobile
Scrollrichtung. Vor-/Zurück-Schaltflächen und die Positionsanzeige ergänzen die
native Swipe- und Touchpad-Bedienung.

Auf Desktop mit Maus/Trackpad startet alle acht Sekunden ein automatischer
Wechsel. Smartphones und Geräte ohne präzisen Zeiger verwenden ausschließlich
manuelle Navigation. Die Systemeinstellung für reduzierte Bewegung deaktiviert
Rotation und sanftes Scrollen ebenfalls.

Manuelle Navigation, Tastaturfokus, Berührung und Scrollgesten pausieren die
Rotation dauerhaft, bis „Rotation starten“ gewählt wird. Hover und ein inaktiver
Browser-Tab unterbrechen sie vorübergehend. Nach Rückkehr startet das volle
Intervall neu. Unsichtbare Karten sind mit `inert` aus der Tastaturnavigation
genommen; manuelle Positionsänderungen werden über eine Live-Region angekündigt.
Ohne JavaScript bleiben die Karten nativ horizontal scrollbar. Bei null oder
einem Beitrag gibt es keine Rotationssteuerung.

Die neueste veröffentlichte angepinnte Meldung bleibt als separates Element
oberhalb des News-/Sitzplatzbereichs sichtbar, auch ohne aktives Event. Dieser
Beitrag wird aus dem Karussell ausgeschlossen. Weitere angepinnte Beiträge
erscheinen gemäß bestehender Sortierung zuerst im Karussell. Das News-Archiv
enthält weiterhin sämtliche veröffentlichten Beiträge.

„Weiterlesen“ und „Details lesen“ öffnen direkt `/news/<id>/`. Unveröffentlichte
oder unbekannte Beiträge liefern 404, auch für Mitarbeiter. Das Admin-Formular
bleibt der Ort zur Bearbeitung von Entwürfen.

## Titelbilder im Admin

News-Beiträge haben drei zusätzliche Felder:

- **Titelbild:** optionaler Upload von JPG, PNG oder WebP bis 10 MB.
- **Bildbeschreibung:** alternative Beschreibung für Screenreader.
- **Bilddarstellung:** proportionaler Zuschnitt für Fotos oder vollständige
  Anzeige für Flyer. Die Einstellung betrifft die Dashboard-Vorschau; auf
  Artikelseite und News-Übersicht ist das Titelbild vollständig sichtbar.

Das hochgeladene Titelbild hat Vorrang. Ohne Titelbild wird das erste lokale
Bild unter `/media/` oder `/static/` aus dem Artikeltext als Vorschau verwendet.
Relative `media/`-/`static/`-URLs werden auf die Site-Wurzel bezogen. Externe
URLs und eingebettete Data-URLs werden nicht als Vorschau übernommen, um keine
zusätzlichen externen Abrufe einzuführen. Bilder innerhalb bestehender Artikel
bleiben erhalten. Ohne Vorschaubild oder bei Ladefehler wird die Dashboard-Karte
als Textkarte angezeigt.

Titelbilder werden unter `media/news/` gespeichert. Die normalen Medien-Backups
schließen sie bereits ein. Vorschaubilder werden verzögert geladen; nur das
erste Bild wird sofort geladen. Die Lösung verwendet lokales CSS und Vanilla
JavaScript und benötigt keine zusätzliche Bibliothek.

## Installation

Nach Aktualisierung des Codes in der jeweiligen Deployment-Umgebung:

```bash
python manage.py migrate
python manage.py seed_translations
python manage.py collectstatic --noinput
```

Webprozesse nach dem Update neu starten. Erforderliche Migration:
`news.0004_newsarticle_cover_image_newsarticle_cover_image_alt_and_more`.
Bestehende Artikel bekommen kein Titelbild und standardmäßig den Foto-Zuschnitt;
ihre Inhalte und Veröffentlichungszustände werden nicht verändert.

## Prüfungen

```bash
python manage.py test news events.tests.EventDashboardTests configuration.tests_frontend_security --noinput
node scripts/tests/news-carousel.test.cjs
python manage.py makemigrations news --check --dry-run
```

44 Django-Tests und neun JavaScript-Tests erfolgreich. Abgedeckt sind Upload,
Dateiformat und Größenlimit, bestehende Artikelbilder, Bildbeschreibung,
Entwurfsschutz, direkte Artikellinks, Hinweisbalken ohne Event, Ausschluss des
Bannerbeitrags, die Begrenzung auf fünf News, Textvorschauen sowie die
Rotations-/Pausenregeln. Dashboard-Abfragebudget und bestehende Frontend-Prüfungen
bleiben erfüllt. Die neuen JavaScript-Tests sind in die bestehende CI aufgenommen.

Browserprüfung mit getrennten SQLite-Testdaten: Desktop bei 1280 Pixeln sowie
mobile Darstellung bei 390 Pixeln, geladene Titelbilder, horizontales Scrollen,
manuelle Navigation, Positionsanzeige, Flyer-Darstellung und Artikelseite.
Es wurde kein physisches Smartphone verwendet. Kein vollständiger Projekt- oder
PostgreSQL-Testlauf für diese Änderung; der Migrationscheck für die News-App ist
erfolgreich.
