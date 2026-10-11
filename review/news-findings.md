Verifikationszusammenfassung (9. Oktober 2026): **1 BESTÄTIGT / 0 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Stufe 2: Admin-Schreibpfad, Modellfeld und Rendering einschließlich öffentlicher Liste/Detailseite, Vorschauhelfern und gemeinsamen Middleware-/Settings geprüft.

Zusammenfassung: 1 Finding — Kritisch: 0, Hoch: 1, Mittel: 0, Niedrig: 0, Info: 0.

Geprüft: Models, Admin/TinyMCE, Views, URLs, Services, Bild-/Textvorschauen, Templates und sämtliche Migrationen. Keine eigenen Forms, Serializer oder Signals vorhanden. Unveröffentlichte Artikel werden in öffentlichen Views korrekt ausgeschlossen. Bild-Uploads durchlaufen Django-ImageField-Validierung sowie Erweiterungs- und Größenprüfung.

### [NEWS-01] Gespeicherte Skripte über redaktionelle News-Inhalte
- Schweregrad: Hoch
- Kategorie: Security
- Fundstelle: news/models.py:72, news/models.py:76; news/admin.py:15, news/admin.py:39; templates/news/news_detail.html:23; templates/news/news_list.html:28
- Beschreibung: HTML im Inhalt wird ohne serverseitiges Sanitizing gespeichert und mit `mark_safe` als vertrauenswürdig ausgegeben. Ein TinyMCE-Widget ist keine serverseitige Sicherheitsgrenze: Ein direkter Admin-POST kann beliebige Tags und Event-Handler enthalten. Schon die Rolle mit `news.add_newsarticle` oder `news.change_newsarticle` erhält damit JavaScript-Ausführung in den Sitzungen aller Leser.
- Auswirkung / Angriffsszenario: Ein redaktioneller Mitarbeiter oder dessen kompromittiertes Konto veröffentlicht `<img src=x onerror=alert(document.domain)>`. Das Skript läuft beim Öffnen der öffentlichen Übersicht oder Detailseite im Ursprung der Anwendung. Bei einem angemeldeten Administrator sind authentifizierte Aktionen über denselben Ursprung möglich; HttpOnly-Cookies verhindern deren direktes Auslesen, aber nicht solche Requests. Voraussetzung ist das News-Schreibrecht. Falls diese Rechte ausschließlich uneingeschränkt vertrauten Superusern gegeben werden, ist die zusätzliche Vertrauensgrenze entsprechend geringer.
- Betroffener Code:
  ```python
  if strip_tags(self.content) == self.content:
      return mark_safe(linebreaks(self.content, autoescape=True))
  return mark_safe(self.content)
  ```
- Empfehlung: Artikel-HTML serverseitig mit einer erprobten Allowlist-Bibliothek bereinigen; bestehende Inhalte ebenfalls prüfen. Der in CONFIGURATION-01 dokumentierte eigene Sanitizer ist vor einer Wiederverwendung zu reparieren. Skriptfähige Inhalte nur dann zulassen, wenn hierfür ausdrücklich eine separate, voll vertrauenswürdige Berechtigung vorgesehen ist.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Hoch (unverändert; delegierte News-Schreibrechte vorausgesetzt).**
- **Begründung:** Das tatsächliche content-Feld ist ein gewöhnliches TextField, das serverseitig beliebiges HTML akzeptiert; TinyMCE wird ausschließlich als Admin-Widget eingesetzt. Keine Model-clean/save-, Admin-save- oder Signal-Sanitization verändert den Wert. `strip_tags` dient nur einem Vergleich für die Wahl des Klartextzweigs; sobald HTML enthalten ist, wird der vollständige Originalwert mark_safe. Die Django-Templateengine escapet SafeString nicht erneut. Beide öffentlichen URLs verwenden `rendered_content`, sodass img/onerror unmittelbar ausgegeben wird. Preview-Text-/Bildfilter werden dort für den Inhalt nicht verwendet.
- **Belege / Gegenmaßnahmen:** `config/urls.py:18`, `:72`, `news/admin.py:7`, `:13`, `:15`, `:20`, `:39`, `news/models.py:13`, `:72`, `:74`, `:76`, `news/urls.py:5`, `:6`, `news/views.py:6`, `:12`, `templates/news/news_detail.html:23`, `templates/news/news_list.html:28`, `news/services.py:7`, `config/settings.py:96`. Geerbte Admin-Modellpermissions und CSRF sichern den Bearbeitungszugang; veröffentlicht=False verhindert die öffentliche Anzeige. Der Klartextzweig escapet korrekt (`news/models.py:75`), schützt aber keinen HTML-Artikel. Clickjacking-/nosniff-/HttpOnly-Schutz verhindert weder gleichursprüngliche Skriptausführung noch Requests aus einer kompromittierten Lesersitzung. Keine script-src-CSP ist in Settings/Middleware oder Nginx vorhanden. Die geringere Rollengrenze bei ausschließlich voll vertrauenswürdigen Autoren ist eine Betriebsbedingung, kein belegter serverseitiger XSS-Schutz.



## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| NEWS-01 | bestätigt | Artikel-HTML wird beim clean/save und erneut bei rendered_content bereinigt. News-Allowlist baut auf repariertem Basissanitizer auf und erhält sichere Bilder, Tabellen und Klartext-Zeilenumbrüche; Eventhandler, Skripte und gefährliche Bild-URLs entfallen. Bestehende Rows sind bei Ausgabe geschützt. |

**Prüfungen:** Alle 22 Newstests und Carousel-JavaScript-Test bestanden, einschließlich 2 neuer XSS-Regressionstests für delegierten Admin-POST und Altinhalte.

Inline-Styles bleiben außerhalb der HTML-Allowlist. Erlaubte Textformatierung und bestehende Bildvorschauen sind getestet; skriptfähiger Roh-HTML-Inhalt erhält keine Sonderberechtigung.
