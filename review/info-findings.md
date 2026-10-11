Verifikationszusammenfassung (9. Oktober 2026): **1 BESTÄTIGT / 0 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Stufe 2: Admin-Eingang, ModelForm/clean/save, beide öffentlichen Info-URLs, Entwurfs-/Loginfilter, Embedding-Schutz und Template nachverfolgt. Der doppelte Sanitizer-Bypass wurde bei CONFIGURATION-01 erneut mit dem identischen Originalhelfer ausgeführt.

Zusammenfassung: 1 Finding — Kritisch: 0, Hoch: 1, Mittel: 0, Niedrig: 0, Info: 0.

Geprüft: EventInfo/EmbedProvider, Views/URLs, Admin, Services, Origin-Validierung, Migrationen, Inhalts-Template und Admin-JavaScript. Login-/Entwurfsfilter, explizit freigegebene HTTPS-Origins, Ausschluss eigener Origin, Frame-CSP, Sandbox und Autoescaping berücksichtigt.

### [INFO-01] Inhaltsredakteure können den HTML-Sanitizer für Stored XSS umgehen
- Schweregrad: Hoch
- Kategorie: Security
- Fundstelle: info/models.py:202, :223; info/admin.py:15, :41; templates/info/event_info_detail.html:45; configuration/sanitizer.py:123
- Beschreibung: Infoinhalte verwenden den in CONFIGURATION-01 belegten fehlerhaften Sanitizer. Der normale Admin erlaubt Staff mit `info.add_eventinfo`/`info.change_eventinfo`, den Inhalt zu bearbeiten; die Beschränkung sensibler HTML-Felder auf Superuser aus der Branding-App gilt hier nicht. `clean` und `save` bereinigen jeweils einmal, das Template gibt das Ergebnis mit `safe` aus.
- Auswirkung / Angriffsszenario: Ein Inhaltsredakteur sendet den Rohwert `<<x><<x>x>img src=x onerror=alert(1)>` im Admin-POST. Nach zwei Bereinigungen bleibt `<img src=x onerror=alert(1)>`; beim Besuch einer veröffentlichten Seite wird JavaScript auf der Anwendungsorigin ausgeführt, auch für Administratoren. TinyMCE als Browsereditor ist keine serverseitige Sicherheitsgrenze. Die zwei Sanitizerdurchläufe wurden isoliert mit dem tatsächlichen Code bestätigt; es wurde kein Inhalt in eine laufende Datenbank geschrieben.
- Betroffener Code:
  ```python
  if self.content:
      self.content = sanitize_html(self.content)
  ```
  ```django
  {{ event_info.content|safe }}
  ```
- Empfehlung: Den zentralen Sanitizer reparieren/ersetzen (CONFIGURATION-01) und gespeicherte Inhalte nach der Korrektur erneut bereinigen. Test den vollständigen Admin-POST bis zur gerenderten Seite.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Hoch (unverändert; Staff mit Info-Schreibpermission erforderlich).**
- **Begründung:** Der registrierte ModelAdmin begrenzt content nicht auf Superuser. TinyMCE-HTMLField übernimmt serverseitig TextField-/CharField-Verhalten, keine zusätzliche HTML-Allowlist. Der Admin-ModelForm-Clean und Model-Save sanitizen jeweils einmal; das doppelt verschachtelte Payload erzeugt nach genau diesen zwei Schritten den aktiven img-Tag. `save` ruft keinen weiteren `clean`-/Sanitizerdurchlauf auf. Beide gemappten Detailpfade rendern den gespeicherten Inhalt mit safe. Ein normaler veröffentlichter TEXT-Datensatz erhält keine Embedding-CSP und liegt nicht innerhalb einer iframe-Sandbox.
- **Belege / Gegenmaßnahmen:** `config/urls.py:18`, `:70`, `info/admin.py:15`, `:41`, `info/models.py:11`, `:65`, `:196`, `:202`, `:219`, `:223`, `info/urls.py:5`, `:6`, `info/views.py:23`, `:55`, `:80`, `templates/info/event_info_detail.html:45`, `configuration/sanitizer.py:123`; Framework-Beleg: [offizielle HTMLField-Dokumentation](https://django-tinymce.readthedocs.io/en/latest/usage.html#the-htmlfield-model-field-type) und [Upstream-HTMLField, master](https://github.com/jazzband/django-tinymce/blob/master/tinymce/models.py) beschreiben TextField-Verhalten und den Widget-Wechsel. Prüfgrenze: `requirements.txt:2` pinnt 5.0.0; das Paket ist lokal nicht installiert und dessen versionsgenauer Quelltext war über den Recherchezugang nicht abrufbar. Der isolierte Sanitizer-Nachweis ersetzt keinen vollständigen Admin-Integrationstest. Staff-/Modellpermission und CSRF sichern den Admin-POST (PROJECT-04 und `config/settings.py:102`), schützen Leser aber nicht vor erlaubten Redaktionseingaben. Entwurfs-/Loginfilter (`info/views.py:36`, `:83`) beschränken das Publikum. CSP `frame-src`/`object-src` (`info/views.py:29`) sowie Sandbox (`templates/info/event_info_detail.html:60`) betreffen externe Frames und setzen keine script-src-Grenze für den HTML-Inhalt. Die Branding-readonly-Regel aus `configuration/admin.py:230` wird hier nicht angewendet.


## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| INFO-01 | bestätigt | Zentraler Sanitizer repariert in CONFIGURATION-01; öffentlicher Info-Inhalt zusätzlich mit safe_html ausgegeben, sodass unsichere Altinhalte ohne Datenmigration geschützt sind. |

**Prüfungen:** 35 Info-/Embeddingtests geprüft: alle unveränderten Tests bestanden; 15 betroffene View-/Regressionstests nach Anpassung zweier Erwartungen an korrekt escaped Ampersands bestanden. Neuer Test verfolgt delegierten Staff-Admin-POST bis zur anonymen Ausgabe; weiterer Test schützt per QuerySet.update eingebrachte Altinhalte. Lokal Django 6.0.7 / django-tinymce 5.0.0 vorhanden, frühere Prüfumgebungsgrenze damit aufgehoben.
