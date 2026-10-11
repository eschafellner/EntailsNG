## Verifikationszusammenfassung

Bestätigt: **1** · Teilweise abgesichert: **0** · False Positive: **0** · Nicht entscheidbar: **0**.

Verifiziert am 2026-10-09. Originalbefund unverändert erhalten; die Bewertung gilt für die im Finding ausdrücklich vorausgesetzte Delegation von Sponsor-Schreibrechten.

Zusammenfassung: 1 Finding — Kritisch: 0, Hoch: 1, Mittel: 0, Niedrig: 0, Info: 0.

Prüfumfang: Modelle/Manager, Services, öffentliche View, URLs, Admin, zugehörige Templates/JavaScript und alle drei Migrationen. Keine eigenen öffentlichen Schreibformulare, Serializer oder zusätzlichen Signale vorhanden. Der aktuelle Uploadpfad erlaubt keine SVGs mehr; Django-ImageField prüft den Bildinhalt, Dateiendungen und 10-MB-Grenze werden zusätzlich validiert. Sponsor-URLs laufen durch URLField-Validierung und werden im Template escaped ausgegeben.

### [SPONSORS-01] Unsanitierte Sponsor-Beschreibung ermöglicht persistentes XSS
- Schweregrad: Hoch
- Kategorie: Security
- Fundstelle: sponsors/models.py:90; sponsors/admin.py:7, :28; sponsors/views.py:5; templates/sponsors/sponsor_list.html:134, :198
- Beschreibung: `beschreibung` ist ein TinyMCE-HTMLField, das serverseitig als TextField gespeichert wird. Weder Model-Clean noch Admin führen eine HTML-Sanitization durch. Die öffentliche Sponsorenliste gibt diesen Inhalt mit `|safe` aus. TinyMCE als Browsereditor begrenzt keine direkt übermittelten Admin-POST-Daten; `truncatechars_html` entfernt ebenfalls keine gefährlichen Attribute.
- Auswirkung / Angriffsszenario: Ein Staff-Konto mit `sponsors.add_sponsor` oder `sponsors.change_sponsor` speichert bei einem aktiven Sponsor beispielsweise `<img src=x onerror=alert(document.domain)>`. Beim Besuch der Sponsorenliste läuft das JavaScript im Ursprung der Anwendung. Auch angemeldete Gäste oder höher privilegierte Administratoren können betroffen sein; JavaScript kann in deren Sitzung Requests mit aus dem DOM gelesenen CSRF-Tokens ausführen. HttpOnly schützt zwar das direkte Auslesen des Session-Cookies, verhindert diese Sitzungsaktionen aber nicht. Sind Sponsor-Redakteure vollständig für beliebiges Website-JavaScript vertrauenswürdig, entfällt die entsprechende Rollengrenze; andernfalls ist sie hier überschreitbar.
- Betroffener Code:
  ```python
  beschreibung = HTMLField(blank=True, ...)
  ```
  ```html
  {{ sponsor.beschreibung|safe }}
  ```
- Empfehlung: Sponsor-HTML serverseitig mit einer erprobten Allowlist sanitizen; Eventhandler, Scripts und gefährliche URL-Schemata entfernen. Vorhandene Daten nachbereinigen. Den gemeinsamen Sanitizer erst nach Behebung von CONFIGURATION-01 einsetzen; eine CSP kann ergänzend Schaden begrenzen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT.**
- **Begründung:** Der Schreibzugriff ist auf aktive Staff-Konten mit passender Django-Modellberechtigung beschränkt und CSRF-geschützt. Das begrenzt den Täterkreis, beseitigt aber die im Original bereits benannte Grenze zwischen Sponsor-Redaktion und beliebigem JavaScript nicht. `SponsorAdmin` stellt `beschreibung` unverändert als schreibbares Feld bereit; `Sponsor.clean()` kontrolliert ausschließlich die Aktivierungsbedingungen. Es gibt im Modul keinen Sanitizer, Save-Hook oder Signal zur HTML-Bereinigung. TinyMCE ist ein Browser-Widget; laut offizieller Dokumentation verhält sich sein `HTMLField` im Übrigen wie `TextField`, dessen Validierung HTML nicht bereinigt. Ein eigener gültiger Admin-POST umgeht daher etwaige Editorfilter.
- **Pfad / Gegenprüfung:** `config/urls.py:18` → Django-Admin/ModelForm → `sponsors/admin.py:28` → `sponsors/models.py:90`, `sponsors/models.py:171` → aktive Sponsor-Datensätze → öffentliche URL `config/urls.py:78` / `sponsors/urls.py:5` → `sponsors/views.py:10` → `sponsors/services.py:10` → Template. Das Aktivitätsqueryset (`sponsors/models.py:23`, `sponsors/models.py:33`) filtert nach Veröffentlichungsvoraussetzungen, nicht nach HTML-Inhalt. Die alternative URL `config/urls.py:79` leitet auf dieselbe öffentliche Ausgabe weiter.
- **Beleg für Schutz und verbleibende Lücke:** Staff-/Modellberechtigungen und CSRF folgen aus dem unveränderten `ModelAdmin` (`sponsors/admin.py:7`) und `config/settings.py:102`; `readonly_fields` umfasst nur Zeitstempel (`sponsors/admin.py:19`). `templates/sponsors/sponsor_list.html:134` und `templates/sponsors/sponsor_list.html:198` deaktivieren Auto-Escaping ausdrücklich mit `safe`; die gekürzten Varianten tun dies ebenfalls (`templates/sponsors/sponsor_list.html:123`, `templates/sponsors/sponsor_list.html:187`). Ein isolierter Render mit Django 6.0.9 ließ `<img src=x onerror=alert(document.domain)>` sowohl bei `safe` als auch bei `truncatechars_html:500|safe` unverändert durch. Die konfigurierte Middleware (`config/settings.py:96`) ergänzt keine CSP mit einer wirksamen `script-src`-Einschränkung. Image-/URLField-Validatoren schützen andere Felder und wirken nicht auf `beschreibung`.
- **Framework-Beleg / Prüfgrenze:** [Offizielle HTMLField-Dokumentation](https://django-tinymce.readthedocs.io/en/latest/usage.html#the-htmlfield-model-field-type) und [Upstream-Implementierung, master, HTMLField.formfield](https://github.com/jazzband/django-tinymce/blob/master/tinymce/models.py) belegen TextField-Vererbung und den reinen Widget-Wechsel. `requirements.txt:2` pinnt 5.0.0; dieses Paket ist lokal nicht installiert und sein versionsgenauer Quelltext war über den Recherchezugang nicht abrufbar. Es wurde kein vollständiger Admin-Integrationstest behauptet.
- **Schweregrad:** **Hoch**, unter der im Original genannten Rechte-/Vertrauensannahme; kein anonymer Schreibzugriff.


## Zusätzliche Beobachtungen

Keine weiteren eigenständigen Probleme während der Verifikation dieses Findings festgestellt.


## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| SPONSORS-01 | bestätigt | Model-clean und save bereinigen Beschreibungen mit dem reparierten gemeinsamen Sanitizer. Alle öffentlichen Lang-/Kurzfassungen sanitizen auch bestehende Datensätze vor der HTML-Kürzung; keine unsichere safe-Ausgabe mehr. |

**Prüfungen:** Alle 25 Sponsortests erfolgreich, darunter echter Admin-POST mit delegiertem add_sponsor und Altbestände in beiden Layouts und allen Kürzungsvarianten. Die historische Einschränkung zur lokal fehlenden TinyMCE-Version entfällt: installiertes django-tinymce 5.0.0 wurde mitgetestet.
