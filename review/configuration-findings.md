Verifikationszusammenfassung (9. Oktober 2026): **2 BESTÄTIGT / 1 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Stufe 2: Alle Befunde einzeln bis zur Formular-/Model-Verarbeitung und Ausgabe geprüft. Sanitizer-Bypass und Kurzfarbenfehler mit den Originalhelfern erneut ohne DB ausgeführt. CONFIGURATION-02 ist für den Clan-Singleton durch einen vorgelagerten Load-/Lock-Pfad abgesichert; die anderen beiden Singleton-Admins bleiben betroffen.

Zusammenfassung: 3 Findings — Kritisch: 0, Hoch: 1, Mittel: 2, Niedrig: 0, Info: 0.

Geprüft: Modelle, Admin, Middleware (zusätzlich im Projektreview), Sanitizer/Validatoren, Cache, Context Processor, Übersetzungs-Tag/-Ladefunktionen, Theme-Erzeugung, Views/URLs, Seeds/Reset, relevante Migrationen und gemeinsame Legal-/Theme-/Navigationstemplates. Kein öffentlicher Schreibendpunkt für Einstellungen. Die Adminbeschränkung der HTML-/CSS-/SVG-Felder auf Superuser wurde berücksichtigt.

### [CONFIGURATION-01] HTML-Sanitizer rekonstruiert ausführbare Tags aus Textfragmenten
- Schweregrad: Mittel
- Kategorie: Security
- Fundstelle: configuration/sanitizer.py:74, :120, :123; configuration/models.py:575; templates/legal.html:11
- Beschreibung: Nicht erlaubte Tags werden entfernt, aber Textknoten werden ungeescaped an das Ergebnis angehängt. Der Python-Parser kann ein einzelnes `<` als Text liefern. Nach Entfernung eines dazwischenliegenden unbekannten Tags entsteht daraus im Ergebnis ein neuer Tag, dessen Attribute die Whitelist nie geprüft hat. Mehrfaches Sanitizing löst das Problem nicht grundsätzlich.
- Auswirkung / Angriffsszenario: `sanitize_html('<<x>img src=x onerror=alert(1)>')` liefert `<img src=x onerror=alert(1)>`. Isolierte Ausführung des tatsächlichen Sanitizers mit `python -B` bestätigte dies ohne DB-Zugriff. Für zweimalige Bereinigung liefert `<<x><<x>x>img src=x onerror=alert(1)>` nach dem zweiten Durchlauf denselben aktiven Tag. Ausgabe mit `|safe` führt im Browser zu Stored XSS. Die Legal-Felder sind im Admin auf Superuser beschränkt, was die unmittelbare Ausnutzbarkeit dort begrenzt; der zentrale Sanitizer wird außerdem von anderen Content-Apps verwendet (siehe deren Dateien).
- Betroffener Code:
  ```python
  if tag not in self.ALLOWED_TAGS:
      return
  def handle_data(self, data):
      if self.drop_depth > 0:
          return
      self.result.append(data)
  ```
- Empfehlung: Textknoten beim Serialisieren HTML-escapen und einen bewährten HTML5-Sanitizer einsetzen; Regressionstests für neu zusammengesetzte Tags und mehrfache Bereinigung hinzufügen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Die Attribute- und URL-Allowlist greift nur für vom Parser als Tags erkannte Eingaben. `handle_data` serialisiert Text ungeescaped. Der isolierte Originalhelfer erzeugte aus `<<x>img src=x onerror=alert(1)>` unmittelbar einen ausführbaren img-Tag. Das doppelt verschachtelte Originalpayload erzeugte nach zwei Durchläufen ebenfalls diesen Tag. Der normale Branding-Admin validiert einmal per ModelForm/clean und erneut per save/clean; die öffentlichen Legal-Views geben genau diesen gespeicherten Inhalt mit safe aus. Keine globale Sanitizer-/CSP-Middleware ergänzt einen dritten wirksamen Schutz.
- **Belege / Gegenmaßnahmen:** `configuration/sanitizer.py:43`, `:74`, `:80`, `:120`, `:123`, `:141`, `configuration/models.py:567`, `:575`, `:581`, `configuration/urls.py:6`, `:7`, `configuration/views.py:48`, `:60`, `templates/legal.html:11`, `config/settings.py:96`. Die serverseitigen readonly-Felder für Nicht-Superuser (`configuration/admin.py:230`) verhindern dort die Eingabe durch gewöhnliche Staff-Konten. Das begrenzt diesen unmittelbaren Einstieg, beseitigt den zentralen Sanitizerfehler und seine Verwendung in anderen Apps aber nicht. Daher kein False Positive; der Originalschweregrad enthält diese Voraussetzung bereits.

### [CONFIGURATION-02] Singleton-Admins umgehen die Modellberechtigung beim Hinzufügen
- Schweregrad: Hoch
- Kategorie: Security
- Fundstelle: configuration/admin.py:101, :224, :357
- Beschreibung: `has_add_permission` für GeneralConfiguration, SiteCustomization und ClanSeatConfiguration prüft ausschließlich, ob bereits irgendein Datensatz existiert. Der Rückgabewert von `super().has_add_permission(request)` bzw. die jeweilige `add_*`-Permission wird nicht geprüft. Djangos Admin-Wrapper verlangt zwar aktiven Staffstatus, setzt die fehlende Modellprüfung aber nicht zusätzlich durch.
- Auswirkung / Angriffsszenario: Bei einer frischen Installation ohne GeneralConfiguration kann jeder aktive Staff über die direkte Add-URL die Konfiguration anlegen, auch ohne Konfigurationsrechte. Dabei kann er insbesondere Kontoinhaber/IBAN für sämtliche Zahlungs-QR-Codes festlegen. Der Angriff hängt vom noch fehlenden Singleton ab; nach dessen Erstellung greift diese Add-Lücke nicht mehr. ClanSeatConfiguration wird gewöhnlich bereits durch eine Migration angelegt.
- Betroffener Code:
  ```python
  def has_add_permission(self, request):
      return not GeneralConfiguration.objects.exists()
  ```
- Empfehlung: Den Existenztest mit `super().has_add_permission(request)` verknüpfen; für besonders sensible Systemeinstellungen ggf. eine explizite Superuserprüfung verlangen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: TEILWEISE ABGESICHERT. Schweregrad: Hoch (beibehalten für GeneralConfiguration; ClanSeatConfiguration-Teilbehauptung entkräftet).**
- **Begründung:** Bei GeneralConfiguration und SiteCustomization liefern die Overrides ohne Add-Permission true, solange kein Datensatz existiert. Die normalen Django-Add-Views vertrauen diesem Override; weder GeneralConfiguration.clean/save noch SiteCustomization.save verlangen einen berechtigten Actor. GeneralConfiguration kann so bei erfüllter Erstinitialisierungsbedingung fremde gültige Bankdaten erhalten. Bei ClanSeatConfiguration dagegen wird jeder Admin-POST schon in `changeform_view` über `lock_configuration` geleitet: `load()` legt einen fehlenden Datensatz an, anschließend ist `.exists()` bei der eigentlichen Add-Prüfung true und die Add-View verweigert den POST. Die Seed-Migration ist somit nicht die einzige Gegenmaßnahme; ein tatsächlicher schreibender Add-Angriff auf diesen dritten Admin scheitert selbst nach fehlendem Singleton.
- **Belege / Gegenmaßnahmen:** Unabgesicherte Overrides: `configuration/admin.py:101`, `:224`; Bankfelder `:73`; normale Model-Verarbeitung `configuration/models.py:359`, `:375`. Aktiver Staff/CSRF: `config/urls.py:18`, `config/settings.py:102`, Framework siehe PROJECT-04. Clan-Schutz: `configuration/admin.py:363`, `:368`, `seating/clan_services.py:33`, `configuration/models.py:259`, `configuration/migrations/0021_clan_seat_configuration.py:7`. Branding-HTML/CSS bleibt für Nicht-Superuser readonly (`configuration/admin.py:230`). GeneralConfiguration.load erzeugt den Singleton bei verschiedenen normalen Zugriffen (`configuration/models.py:392`, `events/views.py:62`); dies verkürzt das Angriffsfenster, ersetzt aber keine Berechtigungsprüfung des direkten Add-POSTs vor der Initialisierung. SiteCustomization.load persistiert seinen Fallback nicht (`configuration/models.py:593`).

### [CONFIGURATION-03] Zulässige Kurzfarben legen das Frontend mit ValueError lahm
- Schweregrad: Mittel
- Kategorie: Bug
- Fundstelle: configuration/validators.py:89; configuration/themes.py:333, :343; configuration/context_processors.py:76
- Beschreibung: Der Farbvalidator akzeptiert drei-, sechs- und achtstellige Hexfarben. Die Kontrastberechnung zerlegt Farben dagegen ausschließlich in drei Zweiergruppen. Bei `#fff` ist die dritte Gruppe leer und `int('', 16)` wirft einen ungefangenen ValueError. Der Fehler tritt im globalen Context Processor auf.
- Auswirkung / Angriffsszenario: Im normalen Branding-Admin `#fff` als Primär- oder Sekundärfarbe speichern. Das Formular akzeptiert den Wert; danach scheitern alle Seiten mit diesem Context Processor. Isolierte Ausführung von `build_css_variables` mit beiden Feldern bestätigte jeweils `ValueError: invalid literal for int() with base 16: ''`. Zur Wiederherstellung kann die Farbe über den Admin korrigiert werden, soweit dessen Seite ohne den Frontend-Context gerendert wird.
- Betroffener Code:
  ```python
  channels = [int(hex_color.lstrip('#')[i:i + 2], 16) / 255
              for i in (0, 2, 4)]
  ```
- Empfehlung: Kurzfarben vor der Kontrastberechnung zu sechsstelligen Werten expandieren und Alpha konsistent behandeln; alternativ Validator und Berechnung auf dieselben unterstützten Formate beschränken.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Der serverseitige Validator akzeptierte #fff im isolierten Test; die Originalfunktion `build_css_variables` warf damit sowohl für primary_color als auch secondary_color ValueError. Form-/Modelvalidierung normalisiert die Farbe nicht auf sechs Stellen. Der globale Context Processor ruft die Funktion ohne Ausnahmebehandlung auf, bevor Theme/Base-Templates gerendert werden. Der try-Block für Hintergrundhelligkeit folgt erst später und fängt diesen Kontrastfehler nicht ab.
- **Belege / Gegenmaßnahmen:** `configuration/validators.py:89`, `:92`, `configuration/models.py:511`, `:527`, `:567`, `:606`, `configuration/themes.py:321`, `:333`, `:343`, `:347`, `configuration/context_processors.py:75`, `config/settings.py:122`, `templates/base.html:8`, `templates/includes/theme.html:3`. Autoescaping und Cachefehler-Fallbacks behandeln keinen Konvertierungsfehler. Eine kurze Hintergrundfarbe allein durchläuft nicht den betroffenen Kontrastpfad. Präzisierung: Auch gewöhnliche Admin-Templateantworten verwenden die konfigurierten Context Processor; eine Korrektur über die Admin-GET-Seite ist daher nicht zuverlässig möglich. Ein gültiger korrigierender POST oder operativer DB-Eingriff kann weiterhin helfen.



## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| CONFIGURATION-01 | bestätigt | HTML-Textknoten werden escaped und Parser-Eingabe finalisiert. safe_html-Templatefilter bereinigt zusätzlich Altinhalte bei Ausgabe; Legal-Template verwendet diesen Filter. |
| CONFIGURATION-02 | teilweise abgesichert | Clan-Singleton war beim Schreiben durch vorgelagertes Load/Lock abgesichert. Alle drei Singleton-Admins verlangen nun zusätzlich die Modell-Add-Permission. |
| CONFIGURATION-03 | bestätigt | RGB-Berechnung expandiert Kurzfarben und berücksichtigt Alpha durch Komposition auf dem Hintergrund. Hintergrundhelligkeit nutzt denselben Parser. |

**Prüfungen:** 69 bestehende Konfigurationstests bestanden; 4 neue Regressionstests nach Korrektur der Testargumente/Farbäquivalenz bestanden. Django check ohne Fehler.

Es wurde gezielt der belegte Sanitizerfehler behoben; keine neue HTML5-Parser-Abhängigkeit eingeführt. Folgemodule verwenden den gemeinsamen Sanitizer und schützen jeweils auch gespeicherte Inhalte.
