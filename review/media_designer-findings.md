Verifikationszusammenfassung (9. Oktober 2026): **1 BESTÄTIGT / 0 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Stufe 2: URL-/Staff-/CSRF-Grenze, Editorformular, Django-JSONField, Model-clean und Schema-Prüfung nachverfolgt. Der unveränderte Schema-Validator wurde isoliert mit Listen-/Objekt-Datenquellen ausgeführt.

Zusammenfassung: 1 Finding — Kritisch: 0, Hoch: 0, Mittel: 0, Niedrig: 1, Info: 0.

Prüfumfang: Modelle, Admin, Views, URLs, Formulare, JSON-Schema, Uploadvalidatoren, Badge-/Urkundendaten, Pillow-/PDF-Rendering, Schrift-Löschsignal, beide Migrationen, Templates und Editor-JavaScript. Frontendaktionen erfordern Login und Staff; diese gemeinsame Staff-Berechtigung entspricht auch den vorhandenen Tests. Empfängerauswahl wird gegen das jeweilige Event/Turnier geprüft. Uploads besitzen Größen-, Format- und Pixelgrenzen; Ausgaben verwenden Auto-Escaping/`json_script` und DOM-`textContent`. PDF-Inhalte werden als Rastergrafik erzeugt, ohne externe Ressourcen abzurufen.

### [MEDIA-DESIGNER-01] Ungültiger Typ der JSON-Datenquelle umgeht die Formularfehlerbehandlung
- Schweregrad: Niedrig
- Kategorie: Bug
- Fundstelle: media_designer/schema.py:88; media_designer/models.py:62; media_designer/views.py:56
- Beschreibung: Der Schema-Validator prüft vor dem Wörterbuchzugriff nicht, ob `source` eine Zeichenkette ist. Bei einer Liste oder einem Objekt löst `source not in allowed` eine `TypeError` aus, weil der Schlüssel nicht hashbar ist. Model-Clean und Django-ModelForm behandeln `ValidationError`, nicht diese Ausnahme.
- Auswirkung / Angriffsszenario: Ein Staff-Nutzer kann beim Speichern einer Vorlage `elements=[{"source":[]}]` übertragen. Das JSON ist syntaktisch gültig, führt aber statt einer Feldfehlermeldung zu HTTP 500. Normale Gäste haben keinen Zugriff auf diesen Endpunkt; die Auswirkung ist auf den betreffenden Bearbeitungsrequest begrenzt.
- Betroffener Code:
  ```python
  source = element.get('source')
  if source != 'static' and source not in allowed:
      raise ValidationError(...)
  ```
- Empfehlung: `source` vor der Mitgliedschaftsprüfung ausdrücklich als `str` validieren und bei abweichendem Typ `ValidationError` auslösen.
- Konfidenz: Hoch. Der originale Validator wurde isoliert ohne Datenbankzugriff mit `source=[]` ausgeführt und löste `TypeError: cannot use 'list' as a dict key (unhashable type: 'list')` aus.

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Niedrig (unverändert).**
- **Begründung:** Ein angemeldeter Staff erreicht den normalen Editor und übermittelt elements über das ModelForm. Das Django-JSONField prüft JSON-Syntax, garantiert aber keine Schema-Typen für innere Werte. Im Model-Clean wird nur ValidationError abgefangen; `source not in allowed` prüft einen Dictionary-Key und wirft bei [] oder {} TypeError, wie mit dem Originalvalidator erneut reproduziert. Dieser Fehler wird weder von ModelForm._post_clean noch der View als Formularfehler behandelt. Die davor bestehenden Array-/Elementtypgrenzen greifen für `[{'source':[]}]` nicht, weil äußere Liste und inneres Dictionary korrekt sind.
- **Belege / Gegenmaßnahmen:** `config/urls.py:76`, `media_designer/urls.py:9`, `media_designer/views.py:20`, `:51`, `:55`, `:56`, `media_designer/forms.py:45`, `:48`, `media_designer/models.py:43`, `:54`, `:62`, `:63`, `media_designer/schema.py:80`, `:86`, `:88`, `:89`, `media_designer/templates/media_designer/edit.html:26` (elements-Hidden-Input) und `media_designer/templates/media_designer/edit.html:16` (CSRF). ModelForm fängt nur ValidationError (`/tmp/breakpoint-review-20261007/lib/python3.14/site-packages/django/forms/models.py:502`, Django 6.0.9). Login, Staff und globale CSRF (`config/settings.py:102`) begrenzen den Fehler auf berechtigte Requests; browserseitiger Editor/HiddenInput ist kein serverseitiger Typschutz. Derselbe Model-Clean läuft auch im registrierten ModelAdmin (`media_designer/admin.py:12`).



## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| MEDIA-DESIGNER-01 | bestätigt | source wird vor jedem Dictionary-Zugriff als str geprüft. Listen, Objekte, null, bool und Zahlen erzeugen Feldfehler statt TypeError; Editor und Admin speichern keine ungültigen Daten. |

**Prüfungen:** Alle 18 Media-Designer-Tests einschließlich Editor-/Admin-Regression erfolgreich.
