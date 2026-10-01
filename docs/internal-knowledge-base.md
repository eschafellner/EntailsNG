# Interne Wissensbasis

Die native Django-App `knowledge` ergänzt EntailsNG um einen internen
Dokumentationsbereich unter `/knowledge/`. Sie verwendet vorhandene Logins,
Themes und den lokal mitgelieferten TinyMCE-Editor. Es gibt keine zusätzlichen
Laufzeitdienste oder externen Editor-/Suchanfragen.

## Zugriff

Alle aktiven Konten mit `is_staff=True` können Bereiche und Seiten lesen,
bearbeiten und veröffentlichen. Zusätzliche Django-Modellrechte sind im Frontend
nicht erforderlich. Eine Benutzerrolle oder `is_superuser` ohne Mitarbeiterstatus
gewährt keinen Zugriff. Gelöschte und inaktive Konten sind ausgeschlossen.

Der Menüpunkt ist auf Mitarbeiter beschränkt. Sämtliche Ansichten, Suchergebnisse,
Entwürfe, Versionen und Dateiabrufe prüfen unabhängig davon den Mitarbeiterstatus.
Nicht angemeldete Besucher werden zum Login geleitet; angemeldete Gäste erhalten
403. Interne Antworten verwenden `Cache-Control: private, no-store` und variieren
nach Cookie. Die öffentlichen Infoseiten bleiben das Dokumentationsangebot für
Gäste.

## Arbeiten mit Dokumenten

- Ein **Bereich** bündelt Seiten, zum Beispiel Technik, Einlass oder Turnierleitung.
  Ohne Eventbezug ist er veranstaltungsübergreifend. Optional wird eine konkrete
  Veranstaltung zugeordnet; auch vergangene Veranstaltungen können dokumentiert
  werden. Die Übersicht und Suche bieten passende Filter.
- **Seiten und Unterseiten** bilden einen sortierbaren Baum mit Navigationspfad.
  URLs verwenden stabile IDs und bleiben bei Titeländerungen gültig. Seiten können
  innerhalb ihres Bereichs neu eingeordnet werden. Zyklen und mehr als 20 Ebenen
  einschließlich verschobener Unterbäume werden abgewiesen.
- **Entwurf speichern** legt eine neue Version an. Bei bereits veröffentlichten
  Dokumenten bleibt die freigegebene Fassung in der normalen Leseansicht bestehen.
  Mitarbeiter können den neuen Entwurf ausdrücklich öffnen; reine Entwurfsseiten
  sind ebenfalls intern lesbar.
- **Speichern und veröffentlichen** beziehungsweise **Aktuellen Entwurf
  veröffentlichen** setzt die neue freigegebene Version. Die Suche durchsucht
  freigegebene Titel/Inhalte und noch nicht veröffentlichte Entwurfsseiten.
- Jede Version hält Titel, Inhalt, Autor, Zeitstempel und Änderungsnotiz fest.
  Die Historie zeigt frühere Fassungen und Textunterschiede. Wiederherstellung
  erzeugt einen neuen Entwurf; sie überschreibt weder die Historie noch die
  veröffentlichte Fassung. Bereich, Seitenposition und Anhänge bleiben dabei
  erhalten.
- Der Editor bietet Überschriften, Listen, Tabellen, Links und Bilder. Andere
  Wissensseiten lassen sich aus einer Liste verlinken. Im Admin gibt es eine
  schreibgeschützte Übersicht mit Link zum Frontend-Editor.

Jede Bearbeitung sendet die geladene Versionsnummer mit. Bei zwischenzeitlichen
Änderungen gibt es einen Konflikt mit HTTP 409; die eingegebenen Inhalte und die
ursprüngliche Versionsnummer bleiben im Formular erhalten. Der aktuelle Stand
kann in einem zweiten Tab geöffnet werden. Überschreiben durch erneutes Senden
des veralteten Formulars ist damit nicht möglich. Auch Bereichsänderungen,
Veröffentlichung und Wiederherstellung verwenden Versionsprüfungen.

Die Schreibdienste sperren zuerst das handelnde Benutzerkonto, dann den Bereich
und die Seite. Die Bereichssperre verhindert außerdem konkurrierende
Verschiebungen, die gemeinsam einen Zyklus erzeugen könnten. Berechtigungen
werden unter der Benutzersperre aus dem aktuellen Datenbankstand geprüft.

## Bilder und Anhänge

Neue Seiten zunächst speichern; danach sind Uploads im Editor verfügbar. Anhänge
werden sofort gespeichert, ohne das gerade bearbeitete Dokument neu zu laden.
Datei-Links und Bilder können anschließend in den Inhalt eingefügt werden.

Ein Upload darf höchstens 10 MB groß sein. Erlaubt sind PNG, JPG, WebP, PDF,
TXT, Markdown, CSV, DOCX, XLSX, ODT, ODS und ZIP. Bilder werden mit Pillow auf
tatsächliches Format und Integrität geprüft; maximal 25 Millionen Pixel.
Andere Dateien werden ausschließlich als Download mit
`application/octet-stream` und `nosniff` ausgeliefert. ZIP-Dateien werden nicht
entpackt. SVG und HTML sind nicht zugelassen.

Private Dateien liegen standardmäßig in `private_media/`, **außerhalb** von
`MEDIA_ROOT` und den Static-Verzeichnissen. Abrufe erfolgen nur über geschützte
`/knowledge/attachments/<uuid>/`-Routen. Nur geprüfte Bilder werden auf Wunsch
inline ausgeliefert. Die Storage-Klasse bietet keine öffentliche `.url`.
`knowledge.E001` verhindert eine Konfiguration des privaten Speicherorts innerhalb
öffentlicher Medien- oder Static-Verzeichnisse.

HTML wird beim Speichern und Anzeigen bereinigt. Inline-Skripte, Event-Handler,
gefährliche URLs und extern geladene Bilder werden entfernt. Bildquellen im
Dokument dürfen nur auf geschützte interne Bildrouten zeigen. Bestehende Anhänge
bleiben für die historischen Versionen verfügbar; eine Löschoberfläche für
Seiten, Versionen oder Anhänge ist in dieser ersten Version nicht vorgesehen.

## Einführung und Betrieb

```bash
python manage.py migrate
python manage.py seed_translations
python manage.py seed_features
python manage.py collectstatic --noinput
```

`knowledge.0001` legt die vier Modelle an; `knowledge.0002` ergänzt den internen
Menüpunkt. `seed_features` ergänzt ihn idempotent auch nach einem Demo-Reset. Die
Konfiguration und die Gast-Infoseiten werden nicht in die Wissensbasis migriert.

Docker: Die aktualisierte Compose-Konfiguration bindet das persistente Volume
`private_media_data` **nur im Web-Container** ein. Nginx erhält keinen Zugriff auf
dieses Volume. Das Dockerfile erzeugt das Verzeichnis mit passenden Rechten für
`appuser`; `.dockerignore` nimmt private Uploads, Datenbanken und lokale
Zugangsdaten aus dem Build-Kontext. Neue Container mit der aktuellen
Compose-Konfiguration erstellen:

```bash
docker compose up -d --build --force-recreate web
```

Der vorhandene Entrypoint führt Migrationen, Static-Sammlung und Seeds aus.
Bei Betrieb außerhalb von Docker kann `PRIVATE_MEDIA_ROOT` auf einen anderen
privaten, beschreibbaren Speicherort gesetzt werden. Für Backups gehören die
Datenbank und `private_media/` beziehungsweise `private_media_data` zusammen;
öffentliche Medien müssen weiterhin separat gesichert werden.

## Prüfungen und Grenzen

Die Regressionstests prüfen Mitarbeiterzugriff auf alle Routen, Entwurf und
Veröffentlichung, Versionen und Wiederherstellung, Konflikte und Rollback,
Bereichsfilter, Suche, Seitenbaum und Tiefengrenze, HTML-Bereinigung,
Dateivalidierung, geschützte Downloads, Cache-Header, CSRF und Navigation.

Drei zusätzliche PostgreSQL-Tests prüfen konkurrierende Bearbeitungen,
Veröffentlichung während einer Bearbeitung und konkurrierende Verschiebungen.
Sie sind im PostgreSQL-16-CI-Job enthalten; lokal auf SQLite werden sie
übersprungen. Es gibt keine Echtzeit-Zusammenarbeit, Kommentare oder
Benachrichtigungen in dieser Version.

Die Browserprüfung verwendet eine getrennte SQLite-Datenbank und einen separaten
privaten Dateispeicher; vorhandene Veranstaltungsdaten werden dabei nicht
verändert. Verifiziert wurden Anmeldung als Mitarbeiter, Navigation und Editor,
Entwurf mit Tabelle, Erhalt der veröffentlichten Fassung, Veröffentlichung und
Wiederherstellung einer früheren Fassung.
Ein geschützter Bildanhang wurde über den Upload-Dienst als Testdatei angelegt
und anschließend im Frontend eingefügt und veröffentlicht. Die Browserprüfung
verifiziert damit die Bildanzeige und das Einfügen; HTTP-Uploads einschließlich
JSON-Antworten, Validierungsfehlern und CSRF sind durch die Regressionstests
abgedeckt. Die Desktop-Darstellung wurde visuell geprüft; ein separater mobiler
Browserlauf wurde nicht durchgeführt.

Verifikation am 1. Oktober 2026:

- Vollständiger Projektlauf: **715 Tests, 695 bestanden, 20 übersprungen**, keine
  Fehler. Alle übersprungenen Fälle benötigen echte PostgreSQL-Zeilensperren.
- Darin die ersten 37 Knowledge-Fälle: 34 bestanden, 3 PostgreSQL-Fälle
  übersprungen. Anschließend wurde ein zusätzlicher Fall für die erste
  Versionsvergleichsauswahl ergänzt und geprüft: **38 Knowledge-Fälle,
  35 bestanden, 3 übersprungen**.
- Integrationsprüfung mit `knowledge`, `configuration`, `info` und
  `users.test_account_deletion`: 152 Tests, 144 bestanden, 8 übersprungen.
- `manage.py check`, `makemigrations knowledge --check --dry-run`,
  `node --check static/js/knowledge.js` und `git diff --check` erfolgreich.
- Beide Knowledge-Migrationen wurden in der getrennten Preview-Datenbank
  erfolgreich angewendet.

Der globale Migrationscheck meldet weiterhin die zuvor dokumentierten
Farbdefault-Abweichungen in `configuration.SiteCustomization`. Die neue
Knowledge-App benötigt darüber hinaus keine fehlenden Migrationen. PostgreSQL
und Docker stehen lokal nicht für einen vollständigen Betriebsnachweis zur
Verfügung.
