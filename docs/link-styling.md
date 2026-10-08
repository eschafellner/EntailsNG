# Einheitliche Frontend-Links

Die gemeinsamen Link-Regeln liegen in `static/css/links.css`, das von `style.css`
geladen wird. Normale Links und Links aus Rich-Text-Inhalten erhalten automatisch
die Theme-Farbe, eine Unterstreichung und denselben Hover-/Tastaturfokus.
Explizite Komponenten behalten die zu ihrem Zweck passende Darstellung.

| Verwendung | Klasse |
| --- | --- |
| Textlink mit hervorgehobener Beschriftung | `text-link` |
| Primäre Aktion, auch als Formularbutton | `btn-action-primary` |
| Sekundäre Aktion, Abbrechen, Pagination | `btn` oder `btn-action-blue` |
| Aktion über die ganze verfügbare Breite | zusätzlich `btn-block` |
| Verlinkte Überschrift | `link-title` |
| Verlinkte Inhaltskarte | `link-card` |
| Verlinktes Bild oder Logo | `link-media` |
| Seitenauswahl | `link-tab`, aktive Seite mit `aria-current="page"` |
| Sitzplatz- oder vergleichbarer Badge-Link | `link-badge` |

`primary-btn` und `btn-primary` verwenden dieselbe primäre Komponente;
`btn-action-blue-sm` verwendet dieselbe sekundäre Komponente. Damit bleiben
bestehende Auth- und Wissensbasis-Formulare kompatibel. Navigation und Branding
verwenden weiterhin ihre eigenen Layoutklassen und die gemeinsamen Theme-Farben.

Farben, Schriften, Rahmen und Link-Dekorationen gehören in die Stylesheets;
einzelne Templates sollen dafür keine Inline-Regeln setzen. Layoutregeln wie
Abstände und Flex-Breiten ändern die Link-Komponente nicht. Die Standardregeln
haben bewusst geringe Spezifität, damit konfiguriertes Custom-CSS weiterhin wirkt.

Textlinks nutzen `--link-color`, `--link-hover-color` und `--link-focus-color`.
Die Standardfarbe mischt `--signal-deep` mit `--ink`, um auf hellen und dunklen
Themes lesbar zu bleiben. `--signal-ink` wird aus der Akzentfarbe berechnet und
liefert eine kontrastreiche Beschriftung für primäre Aktionen, auch bei eigenen
Farben. Aktionslinks sind mindestens 44 Pixel hoch; lange Beschriftungen und URLs
können umbrechen. Reduzierte Bewegung und ein sichtbarer Tastaturfokus bleiben
berücksichtigt.

`templates/includes/theme.html` stellt die Theme-Variablen und Custom-CSS in
der Hauptansicht und sämtlichen Auth-Seiten bereit. Der eigenständige
Sitzplaneditor lädt nur die gemeinsamen Link-Regeln. Die 500-Fehlerseite hält
die entsprechende Button-Darstellung lokal vor, damit sie ohne Datenbank und
statische Dateien funktioniert.

Für die Bereitstellung `collectstatic` ausführen und die Webprozesse neu starten,
damit gecachte Templates erneuert werden. Keine Datenbankmigration erforderlich.

Prüfstand vom 8. Oktober 2026: 1.206 Python-Tests und 31 JavaScript-Tests
erfolgreich. Im Browser wurden 151 Ansichten mit 612 Links bei 1440, 390 und
320 Pixeln sowie alle neun Themes geprüft, einschließlich Hover, Tastaturfokus,
Kontrast und Erreichbarkeit in horizontal scrollbaren Tabellen. Keine
Prüffehler, JavaScript-Fehler oder fehlenden Assets. 93 Templates kompilieren;
Ziele, Titel und Verhalten von 159 bestehenden Links bleiben unverändert.
Systemprüfung, Migrationsabgleich und `collectstatic` erfolgreich.
