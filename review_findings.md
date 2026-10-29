# Code-Review EntailsNG – Befunde

Repo-Stand: `85ba422` · Fortschritt: [review_progress.md](review_progress.md)

Schweregrade: **kritisch** (akute Sicherheits-/Datenverlustgefahr) · **hoch** (realistischer Fehler/Missbrauch mit spürbarer Wirkung) · **mittel** (Fehler unter bestimmten Bedingungen, Wartungsrisiko) · **niedrig** (Qualität, Doku, Kosmetik).
Sicherheit des Befunds: **bestätigt** (im Code/Lauf nachvollzogen) · **Vermutung** (plausibel, nicht reproduziert).

## Zusammenfassung

**40 Befunde:** 2 hoch · 9 mittel · 29 niedrig · 0 kritisch. Lauffähigkeit ist gegeben: `check`, Deploy-Check, Migrations-Dry-Run sauber, **1335/1335 Django-Tests und 31/31 Node-Tests grün**.

Der Code ist insgesamt sorgfältig gebaut. Durchgängige Zeilensperren, Transactional Outbox, HTML-Sanitizer mit Ausgabe-Bereinigung, sauber abgesicherte Backups und Uploads, umfangreiche Nebenläufigkeitstests. Die schwersten Befunde betreffen **Rechteausweitung innerhalb der Staff-Rollen**: Bestimmte Einzelrechte (Texte pflegen, Mailprotokoll lesen, Sitzplan bearbeiten) führen faktisch zu Superuser-Rechten.

| Prio | ID | Modul | Kurzbeschreibung | Sicherheit |
|---|---|---|---|---|
| hoch | F-009 | configuration | Übersetzungstexte per `str.format` → `SECRET_KEY` auslesbar (Redakteursrecht reicht) | bestätigt (PoC) |
| hoch | F-020 | emails | Passwort-Reset-Links im Klartext in Outbox, mit `view_outgoingemail` lesbar → Superuser-Übernahme | bestätigt (PoC) |
| mittel | F-034 | static | DOM-XSS im Admin-Sitzplatz-Picker über `seat_label` (Sitzplan-Recht → Admin-Session) | bestätigt (Markup), Browser n. getestet |
| mittel | F-011 | configuration | SVG-Validator gibt Rohstring zurück → Processing-Instruction-Bypass (nur Superuser) | bestätigt (Validator), Browser n. getestet |
| mittel | F-024 | events | Admin-Löschen von User/Event vernichtet bezahlte Anmeldungen (CASCADE) | bestätigt |
| mittel | F-015 | users | Benutzernamen nur in Groß-/Kleinschreibung verschieden → Login-Kollision | bestätigt |
| mittel | F-036 | Deployment | Redis ohne Passwort am Host veröffentlicht + Pickle-Cache → RCE-Pfad | Konfig. bestätigt |
| mittel | F-031 | tournaments | `seed_tournaments` setzt `password123`, ohne DEMO_MODE-Schutz | bestätigt |
| mittel | F-004 | config | Öffentliche TinyMCE-Routen erzeugen anonym 500er + DB-Fehlerprotokoll | bestätigt |
| mittel | F-010 | configuration | Fehlerprotokoll unbegrenzt, ohne Dedup/Löschfrist (inkl. IP) | bestätigt |
| mittel | F-037 | Deployment | `nginx:1.27` vermutlich ohne Sicherheitsupdates; Basisimages ungepinnt | Vermutung |
| niedrig | F-001–F-003, F-005–F-008, F-012–F-014, F-016–F-019, F-021–F-023, F-025–F-030, F-032, F-033, F-035, F-038–F-040 | diverse | siehe Einzelbefunde | überw. bestätigt |

**Empfohlene Reihenfolge:** F-009 und F-020 sofort (kleiner Code-Umfang, hohe Wirkung). Danach F-034, F-036, F-031 (Kommando löschen), F-024, F-015, F-004+F-010 (zusammen), F-037. Die niedrigen Befunde können gebündelt über Linter/Aufräum-PRs erledigt werden.

---

## M00 Baseline

Ergebnis Lauffähigkeit (Wegwerf-venv mit exakt `requirements.txt`, Django 6.0.9, Python 3.14.8, PostgreSQL 18.6):
- `python -m compileall`: keine Syntaxfehler.
- `manage.py check`: keine Befunde. `check --deploy` mit Produktionswerten aus `.env.example`: keine Befunde aus den Code-Defaults (Warnungen W004/W005/W008/W012/W016/W021 entstehen nur durch die lokale `.env`, die HSTS/Secure-Flags abschaltet – für Entwicklung beabsichtigt).
- `makemigrations --check --dry-run`: „No changes detected“.
- `pyflakes`: keine undefinierten Namen; ~70 ungenutzte Importe/Variablen in Produktivcode (siehe F-003).
- Testlauf: siehe Abschnitt M20 bzw. Protokoll.

### F-001 · Umgebung · `.venv` (lokal) ↔ `requirements.txt:1,8`
- **Schweregrad:** niedrig
- **Beschreibung:** Die lokale `.venv` enthält Django 6.0.7 und python-dotenv 1.0.1, gepinnt sind Django 6.0.9 und python-dotenv 1.2.4. Das Handover (Zeile 32, 146) nennt 6.0.9 als Sicherheitsuntergrenze (B1).
- **Auswirkung:** Lokale Läufe/Tests prüfen einen Stand ohne die B1-Sicherheitskorrekturen; Ergebnisse sind nicht mit CI vergleichbar.
- **Lösungsvorschlag:** `.venv/bin/python -m pip install -r requirements.txt` (bzw. venv neu anlegen). Optional `pip check` + Versionsprüfung in `start.sh` aufnehmen.
- **Sicherheit des Befunds:** bestätigt (`.venv/bin/pip list`).

### F-002 · Doku · `DEVELOPER_HANDOVER.md`
- **Schweregrad:** niedrig
- **Beschreibung:** Der Auftrag nennt `developers_handover.md`, im Repo existiert `DEVELOPER_HANDOVER.md`. Außerdem liegt im Root ein `AUDIT_BERICHT.md` (18.10.), der im Handover nicht referenziert wird.
- **Auswirkung:** Verweise in Prozessen/Tickets laufen ins Leere; unklar, welcher Bericht maßgeblich ist.
- **Lösungsvorschlag:** Dateinamen vereinheitlichen; `AUDIT_BERICHT.md` im Handover verlinken oder nach `docs/` verschieben.
- **Sicherheit des Befunds:** bestätigt.

### F-003 · Code-Qualität · projektweit (Beispiele: `configuration/models.py:2,15-16,26`, `configuration/context_processors.py:6,11`, `users/views.py:2-3,13-14,24`, `tournaments/views.py:6,26,34`)
- **Schweregrad:** niedrig
- **Beschreibung:** pyflakes meldet ca. 70 ungenutzte Importe/lokale Variablen im Produktivcode, dazu eine Neudefinition (`configuration/admin.py:40` überschreibt `mark_safe` aus Zeile 6). Ausgenommen sind beabsichtigte Side-Effect-Importe in `apps.py` (Checks/Signals), die aber mit `# noqa: F401` markiert werden sollten. Laut Handover (Zeile 144) ist kein Linter konfiguriert.
- **Auswirkung:** Erschwert Wartung; einige Importe sind evtl. bewusste Re-Exports (z. B. `configuration/models.py` re-exportiert Sanitizer-Konstanten), was ohne Kennzeichnung beim Aufräumen zu Importbrüchen führt.
- **Lösungsvorschlag:** `ruff` (Regeln F, E9, B) in CI aufnehmen; Re-Exports über `__all__` kennzeichnen, Side-Effect-Importe mit `# noqa: F401`.
- **Sicherheit des Befunds:** bestätigt (pyflakes-Lauf).

## M01 config

### F-004 · config · `config/urls.py:69`
- **Schweregrad:** mittel
- **Beschreibung:** `path('tinymce/', include('tinymce.urls'))` bindet alle Views von django-tinymce öffentlich und ohne Authentifizierung ein. Zwei davon sind in diesem Projekt nicht lauffähig: `/tinymce/flatpages_link_list/` (benötigt `django.contrib.flatpages`/`sites`, nicht installiert → `RuntimeError`) und `/tinymce/filebrowser/` (kein Filebrowser installiert → `NoReverseMatch`). Das TinyMCE-Widget benötigt diese Routen nicht (Compressor ist nicht aktiviert: kein `TINYMCE_COMPRESSOR` in den Settings).
- **Auswirkung:** Jeder anonyme GET erzeugt HTTP 500 **und einen DB-Eintrag mit vollständigem Traceback** in `configuration_systemerrorlog` (im Probelauf: 2 Aufrufe → 2 Zeilen). Ein Angreifer kann damit das Fehlerprotokoll beliebig fluten (DB-Wachstum, echte Fehler gehen unter). Details zur Protokollierung: siehe M02.
- **Lösungsvorschlag:** Include entfernen (das Widget lädt nur Static-Dateien) oder nur benötigte Route gezielt und für Staff einbinden:
  ```python
  # config/urls.py – Zeile 69 ersatzlos streichen
  # path('tinymce/', include('tinymce.urls')),
  ```
  Vorher prüfen, ob irgendwo `{% url 'tinymce-...' %}` verwendet wird (aktuell: keine Fundstelle außer dem Include).
- **Sicherheit des Befunds:** bestätigt (Testclient gegen Wegwerf-DB: beide Routen 500, 2 neue `SystemErrorLog`-Zeilen).

### F-005 · config · `config/settings.py:159-169`
- **Schweregrad:** niedrig
- **Beschreibung:** Persistente DB-Verbindungen (`CONN_MAX_AGE` Default 600) ohne `CONN_HEALTH_CHECKS`.
- **Auswirkung:** Nach DB-Neustart, Failover oder Restore (Handover Z. 154) schlägt pro Gunicorn-Worker die erste Anfrage mit `OperationalError` fehl, bevor Django die Verbindung verwirft – das erzeugt 500er und Fehlerprotokolleinträge.
- **Lösungsvorschlag:** `'CONN_HEALTH_CHECKS': env_bool('DB_CONN_HEALTH_CHECKS', default=True),` im `DATABASES['default']`-Block ergänzen.
- **Sicherheit des Befunds:** bestätigt (Einstellung fehlt); Auswirkung = dokumentiertes Django-Verhalten, im Projekt nicht reproduziert.

### F-006 · config · `config/settings.py:308-321` (globale Header)
- **Schweregrad:** niedrig (Vorbehalt bis M19/Nginx geprüft)
- **Beschreibung:** Keine projektweite Content-Security-Policy. Django 6.0 bietet `SECURE_CSP` + `ContentSecurityPolicyMiddleware`; gesetzt wird CSP nur punktuell (`info/views.py:31`, `knowledge/views.py:270`).
- **Auswirkung:** Fehlende zweite Verteidigungslinie gegen XSS (CMS-/News-HTML wird an mehreren Stellen gerendert).
- **Lösungsvorschlag:** Report-Only-Policy einführen und schrittweise schärfen, z. B. `SECURE_CSP_REPORT_ONLY = {"default-src": [CSP.SELF], "img-src": [CSP.SELF, "https:", "data:"], "frame-src": [...]}`; Inline-Skripte vorher inventarisieren (M16/M17).
- **Sicherheit des Befunds:** bestätigt für Django-Ebene; ob Nginx CSP setzt, wird in M19 geprüft.

### F-007 · config · `config/settings.py:40,146,176-179,234`
- **Schweregrad:** niedrig
- **Beschreibung:** Umgebungsabhängiges Verhalten wird über `sys.argv` erkannt (`'test' in sys.argv`, `CLI_COMMANDS_FALLBACK`). Das betrifft Pflichtprüfungen (DB-Variablen, Redis-Pflicht, Manifest-Storage). Es gibt keine getrennten Settings-Module für dev/test/prod.
- **Auswirkung:** Andere Testrunner (z. B. pytest-django) oder Kommandos mit einem Argument `check`/`help`/`test` umgehen die Fail-Fast-Prüfungen bzw. erhalten LocMemCache statt Redis, ohne dass es auffällt. Aktuell nur ein Wartungsrisiko, kein beobachteter Fehler.
- **Lösungsvorschlag:** Explizite Variable statt argv-Heuristik, z. B. `DJANGO_ENV=test|dev|prod`, oder `config/settings/{base,test,prod}.py` mit `DJANGO_SETTINGS_MODULE`.
- **Sicherheit des Befunds:** bestätigt (Code); Auswirkung Vermutung.

### F-008 · config · `requirements.txt`
- **Schweregrad:** niedrig
- **Beschreibung:** Direkte Abhängigkeiten sind gepinnt, transitive (asgiref, sqlparse, cffi, pycparser, packaging, …) nicht, und es gibt keine Hashes.
- **Auswirkung:** Builds sind nicht vollständig reproduzierbar; ein neues transitive Release kann Image und CI unbemerkt verändern.
- **Lösungsvorschlag:** Lockfile mit `pip-compile --generate-hashes` (oder `uv pip compile`) erzeugen und im Dockerfile `pip install --require-hashes -r requirements.lock` verwenden.
- **Sicherheit des Befunds:** bestätigt.

Geprüft ohne Befund: `config/wsgi.py`, `config/asgi.py`, `manage.py`; URL-Konfiguration ohne doppelte Namen/Muster (Auswertung aller 389 Routen); Secrets kommen ausschließlich aus Umgebung (`SECRET_KEY` Pflicht, Fail-Fast); `ALLOWED_HOSTS` Pflicht bei `DEBUG=False`; Cookie-/HSTS-/SSL-Defaults sicher; `.env` ist per `.gitignore`/`.dockerignore` ausgeschlossen und nicht versioniert.
Offen zur Prüfung in späteren Modulen: `custom_500_handler` (`config/urls.py:89-94`) rendert mit Context-Processors – Robustheit bei DB-Ausfall → M02; unbenannte Alias-Route `events/api/event/<id>/update-payment-check/` (`events/urls.py:17`) → M05.

## M02 configuration

### F-009 · configuration · `configuration/translations.py:1368-1372` (+ `templates/tournaments/tournament_detail.html:230`, `configuration/admin.py:12-15`)
- **Schweregrad:** hoch
- **Beschreibung:** `get_translation()` formatiert den im Admin editierbaren Übersetzungstext mit `text.format(**kwargs)`. Python-Format-Strings erlauben Attribut- und Indexzugriffe (`{x.attr[key]}`). Sobald ein kwarg kein primitiver Wert ist, kann der Übersetzungstext beliebige Attribute traversieren. Das passiert konkret in `tournament_detail.html:230`: `team_name=user_member_team` übergibt ein `Team`-Model-Objekt. `SystemTranslationAdmin` hat keine besonderen Rechte, also kann jeder Staff-Account mit `configuration.change_systemtranslation` (eine typische Redakteursrolle) den Text ändern.
- **Auswirkung:** Rechteausweitung von „darf Texte pflegen“ auf Geheimnisse und Daten. Nachgewiesen mit dem Text `Leak: {team_name.save.__globals__[settings].SECRET_KEY}`: Das Template gibt den `SECRET_KEY` aus. Mit dem `SECRET_KEY` lassen sich u. a. Passwort-Reset-Tokens fälschen, und damit kann ein Superuser-Konto übernommen werden. Ebenso abrufbar wären z. B. `{team_name.captain.password}` (Hash) oder `{team_name.captain.email}`. Die Ausgabe wird zwar HTML-escaped, bleibt aber lesbar.
- **Lösungsvorschlag:** Formatierung auf einfache Platzhalter beschränken und kwargs vorher in Strings umwandeln:
  ```python
  import string

  class _PlainFormatter(string.Formatter):
      def get_field(self, field_name, args, kwargs):
          if not field_name.isidentifier():          # verbietet '.', '[', Positionsindizes
              raise KeyError(field_name)
          return kwargs[field_name], field_name

  _FORMATTER = _PlainFormatter()

  def get_translation(key, default=None, request=None, **kwargs):
      ...
      if kwargs and isinstance(text, str):
          safe_kwargs = {k: str(v) for k, v in kwargs.items()}
          try:
              return _FORMATTER.vformat(text, (), safe_kwargs)
          except (KeyError, IndexError, ValueError):
              return text
  ```
  Zusätzlich `tournament_detail.html:230` auf `team_name=user_member_team.name` ändern und einen Regressionstest ergänzen (Text mit `{x.__class__}` darf keine Attributauflösung bewirken).
- **Sicherheit des Befunds:** bestätigt (Template-Rendering gegen Wegwerf-DB gab den Dummy-`SECRET_KEY` aus).

### F-010 · configuration · `configuration/middleware.py:55-84`, `configuration/models.py:626-649`
- **Schweregrad:** mittel
- **Beschreibung:** `DynamicDebugMiddleware.process_exception` legt für **jede** unbehandelte Exception eine `SystemErrorLog`-Zeile mit vollem Traceback, Fehlermeldung, Benutzer und Client-IP an. Es gibt weder Deduplizierung, Rate-Limit noch eine Aufbewahrungsfrist. Gelöscht wird nur manuell (Adminaktion für erledigte Einträge) bzw. bei Kontolöschung (`users/services.py:372`).
- **Auswirkung:** In Verbindung mit anonym auslösbaren 500ern (F-004) kann ein Angreifer die Tabelle unbegrenzt füllen (DB-Wachstum, Backups werden größer, echte Fehler gehen unter). Gespeicherte IP-Adressen ohne Löschfrist sind datenschutzrechtlich problematisch (DSGVO Art. 5 Abs. 1 e, Speicherbegrenzung).
- **Lösungsvorschlag:** (1) Deduplizieren über Hash aus `exception_type`+`path`+letzter Traceback-Zeile mit Zähler/`last_seen`, z. B. `SystemErrorLog.objects.filter(fingerprint=fp, resolved=False).update(count=F('count')+1, last_seen=now)`, sonst `create`; (2) Aufbewahrungs-Command (`purge_error_logs --days 30`) im Worker oder Cron; (3) Obergrenze pro Zeitfenster über Cache-Zähler.
- **Sicherheit des Befunds:** bestätigt (Code, Probe mit F-004: 2 anonyme Requests → 2 Zeilen).

### F-011 · configuration · `configuration/sanitizer.py:161-200`, `configuration/models.py:155-156,175-180`, `templates/base.html:90,177,224`
- **Schweregrad:** mittel
- **Beschreibung:** `sanitize_and_validate_svg()` validiert den mit ElementTree geparsten Baum, **gibt aber den unveränderten Originalstring zurück**. ElementTree verwirft Processing Instructions/Kommentare beim Parsen, der HTML-Parser des Browsers liest `<?…>` aber als Bogus-Kommentar bis zum ersten `>`. Dadurch passiert z. B. `<svg xmlns="http://www.w3.org/2000/svg"><?x </svg><img src=x onerror=alert(1)>?></svg>` die Prüfung. Im HTML-Kontext endet der Kommentar bei `</svg>`, und `<img onerror>` bricht aus dem SVG-Fremdinhalt aus. `base.html` gibt `item.icon_svg|safe` auf jeder Seite aus. Außerdem wird nur in `clean()` geprüft, `save()` speichert bei `icon_name=CUSTOM` ungeprüft (z. B. Shell, Fixtures, Datenmigration).
- **Auswirkung:** Gespeichertes XSS auf allen Seiten für alle Besucher. Voraussetzung ist ein Superuser-Konto (`configuration/admin.py:27-33` sperrt das Feld für Staff), deshalb nicht „hoch“. Die Schutzmaßnahme, die laut Docstring Stored XSS verhindern soll, ist aber umgehbar (Defense-in-Depth-Bruch, z. B. bei übernommener Superuser-Session).
- **Lösungsvorschlag:** Den validierten Baum neu serialisieren statt `raw` zurückzugeben, und in `save()` erneut prüfen:
  ```python
  # sanitizer.py, Ende von sanitize_and_validate_svg
  return ET.tostring(root, encoding='unicode', method='xml')
  # models.py NavigationItem.save
  elif self.icon_svg:
      self.icon_svg = sanitize_and_validate_svg(self.icon_svg)
  ```
  Zusätzlich `style`-Attribute und `use`-Verweise auf externe URLs ablehnen.
- **Sicherheit des Befunds:** bestätigt, dass der Validator die Payload akzeptiert (direkter Funktionsaufruf). Die Ausführung im Browser folgt aus der HTML-Parsing-Spezifikation und wurde nicht im Browser nachgestellt.

### F-012 · configuration/config · `config/urls.py:89-94`, `configuration/context_processors.py:59-75`
- **Schweregrad:** niedrig
- **Beschreibung:** `custom_500_handler` rendert `500.html` mit `request=request`. Dadurch laufen alle Context-Processors, und `feature_flags` führt ungeschützte DB-Abfragen aus (`NavigationItem`, `GeneralConfiguration`, `SiteCustomization`). `500.html` selbst braucht nur `error_id`.
- **Auswirkung:** Gerade bei DB-Ausfall (häufigste 500-Ursache) wirft der Handler selbst eine Exception. Statt der gestalteten Fehlerseite liefert Gunicorn eine nackte Fehlerantwort. Nachgewiesen mit `DB_PORT=1`: `OperationalError` aus dem Handler.
- **Lösungsvorschlag:**
  ```python
  def custom_500_handler(request):
      error_id = getattr(request, 'system_error_id', None)
      try:
          content = render_to_string('500.html', {'error_id': error_id})   # ohne request
      except Exception:
          content = '<h1>Serverfehler (500)</h1>'
      return HttpResponseServerError(content)
  ```
- **Sicherheit des Befunds:** bestätigt (direkter Aufruf mit unerreichbarer DB).

### F-013 · configuration · `configuration/management/commands/seed_features.py:67-79`, `configuration/models.py:53-66`
- **Schweregrad:** niedrig
- **Beschreibung:** `seed_features` legt den Menüpunkt „Gäste“ mit `icon_name='guests'` an (per `get_or_create`, also ohne Validierung). `NavigationItem.IconChoices` enthält `guests` nicht (wohl aber `SYSTEM_ICONS`).
- **Auswirkung:** Der Menüpunkt kann im Admin nicht gespeichert werden, ohne das Icon zu ändern (`full_clean` → „Wert 'guests' ist keine gültige Option“). Das gilt auch für `list_editable` (Reihenfolge/aktiv) in der Liste.
- **Lösungsvorschlag:** `GUESTS = 'guests', 'Gäste (Personen)'` in `IconChoices` ergänzen und `makemigrations` ausführen (Choices-Änderung erzeugt eine Migration).
- **Sicherheit des Befunds:** bestätigt (`full_clean` im Probelauf).

### F-014 · configuration · `configuration/models.py:394-395,652-677`, `configuration/cache.py:111-113`
- **Schweregrad:** niedrig
- **Beschreibung:** Doppelte Cache-Invalidierung (in `save()`/`delete()` **und** in `post_save`/`post_delete`-Receivern), `post_delete`-Receiver für Singletons, deren `delete()` ohnehin eine Exception wirft (toter Code), und ein Modul-Import mitten in `cache.py`. `configuration/translations.py:1310` importiert ungenutzte Funktionen nach dem 1.300-zeiligen Datenblock.
- **Auswirkung:** Wartungsaufwand und schwer nachvollziehbare Invalidierungslogik, aber kein Funktionsfehler.
- **Lösungsvorschlag:** Invalidierung an einer Stelle bündeln (nur Receiver oder nur `save()`), Importe an den Dateianfang, `DEFAULT_TEXTS` in ein eigenes Datenmodul auslagern.
- **Sicherheit des Befunds:** bestätigt.

Geprüft ohne Befund: `SafeHTMLSanitizer` (Whitelist, Attribut-Escaping, URL-Schemata inkl. Entity-/Steuerzeichen-Tricks), `validate_custom_css` (blockiert `</style`, `@import`, `javascript:`), Hex-/IBAN-/BIC-Validatoren, `theme_css_vars` (nur validierte Werte), Health-Endpoint `/api/health/` (keine sensiblen Details), `runtime.py`/`check_runtime`, Demo-Service (DEMO_MODE-Pflicht, Advisory-Lock, Leerheitsprüfung), Seeds, Admin-Schutz für `custom_css`/Impressum/Datenschutz/`icon_svg` (nur Superuser), Datenmigrationen aller Apps (alle mit Rückwärtsoperation, außer der im Handover als irreversibel dokumentierten `tournaments/0017`).
Testlücken: kein Test zu Format-String-Platzhaltern (F-009), zu SVG-Processing-Instructions (F-011) und zum 500-Handler bei DB-Ausfall (F-012).

## M03 users

Bereits bekannt und im Repo dokumentiert (nicht erneut als Befund gezählt): **USERS-03** – Staff mit `users.change_user` kann über die Felder von Djangos `UserAdmin` privilegierte Konten und Rechte ändern (`users/admin.py:34-39`, `docs/security-backlog.md:5-19`, bewusst zurückgestellt).

### F-015 · users · `users/forms.py:83-89`, `users/auth_backends.py:131-134`
- **Schweregrad:** mittel
- **Beschreibung:** `CustomUserCreationForm.clean_username` überschreibt `UserCreationForm.clean_username`, ohne `super()` aufzurufen. Damit entfällt Djangos Prüfung auf Benutzernamen, die sich nur in Groß-/Kleinschreibung unterscheiden (Django `contrib/auth/forms.py:255-267`). Das Datenbank-Unique auf `username` ist case-sensitiv. Das Login sucht dagegen mit `username__iexact` und nimmt `.first()`.
- **Auswirkung:** Es können `ReviewBob` und `reviewbob` parallel existieren (im Probelauf bestätigt). Danach kann sich eines der beiden Konten nicht mehr per Benutzername anmelden, weil immer das in der Sortierung erste Konto geprüft wird und sein Passwort nicht passt. Fehlversuche zählen dann auf das **fremde** Konto und sperren es nach 5 Versuchen. Außerdem sind die Namen in Team-/Clanlisten verwechselbar (Impersonation).
- **Lösungsvorschlag:**
  ```python
  def clean_username(self):
      username = (super().clean_username() or '').strip()   # Django-Prüfung erhalten
      if '@' in username: ...
  ```
  Dauerhaft absichern mit `models.UniqueConstraint(Lower('username'), name='unique_lower_username')` (vorher Bestandsdaten auf Kollisionen prüfen: `User.objects.annotate(l=Lower('username')).values('l').annotate(c=Count('id')).filter(c__gt=1)`).
- **Sicherheit des Befunds:** bestätigt (Formular mit `reviewbob` gültig, obwohl `ReviewBob` existiert; Probe in zurückgerollter Transaktion).

### F-016 · users · `users/models.py:195-197`, `users/auth_backends.py:176-182`, `users/forms.py:254-257`
- **Schweregrad:** niedrig
- **Beschreibung:** Die Kontosperre (15 min nach 5 Fehlversuchen) hängt nur am Konto, nicht an der Quelle. Das IP-Limit (25 Fehlversuche/5 min) erlaubt einer einzelnen IP, 5 beliebige Konten pro 5 Minuten zu sperren. Das Passwort-Reset-Limit pro E-Mail (3/h) greift vor der Existenzprüfung und verwirft weitere Anfragen stillschweigend.
- **Auswirkung:** Ein Angreifer, der Benutzernamen kennt (z. B. aus Team-/Gästelisten), kann Gäste oder Orga-Accounts dauerhaft aussperren und mit 3 Reset-Anfragen pro Stunde auch die im Sperrtext empfohlene Selbsthilfe („Passwort zurücksetzen“) blockieren. Gerade während einer LAN mit vielen Logins ist das störend.
- **Lösungsvorschlag:** Sperre nach (Konto, IP) schlüsseln oder statt harter Sperre progressive Verzögerung verwenden. Ein Login mit korrektem Passwort aus einer bislang unauffälligen IP trotz Sperre erlauben. Das Reset-Limit pro E-Mail erst **nach** dem Versand zählen bzw. höher ansetzen.
- **Sicherheit des Befunds:** bestätigt (Code); Missbrauch nicht praktisch nachgestellt.

### F-017 · users · `users/rate_limits.py:15-35`
- **Schweregrad:** niedrig
- **Beschreibung:** `reserve_rate_limit` greift auf private Django-Interna zu (`cache._connections[cache._alias]`, `backend._cache.get_client`) und blockiert bei **jedem** Fehler (`return False`, fail-closed). Andere Limits im selben Modulbereich sind fail-open (`auth_backends.py:66-76`, `views.py:107-120`).
- **Auswirkung:** Bei Redis-Ausfall oder nach einem Django-Update mit geänderten Interna werden Passwort-Reset-Mails (`forms.py:250-257`) und Aktivierungscode-Anfragen (`views.py:217`) **stillschweigend** nicht mehr versendet. Der Nutzer sieht trotzdem eine Erfolgsmeldung. Das uneinheitliche Fail-Verhalten erschwert die Betriebsdiagnose.
- **Lösungsvorschlag:** Öffentliche Cache-API verwenden (`cache.add` + `cache.incr`, beide bei Redis atomar) und eine bewusste, dokumentierte Fail-Policy pro Aufrufer festlegen. Fail-closed-Fälle zusätzlich als Warnung loggen bzw. in `check_runtime` sichtbar machen.
- **Sicherheit des Befunds:** bestätigt (Code); Ausfall nicht nachgestellt (kein Redis lokal).

### F-018 · users · `users/services.py:374-387`
- **Schweregrad:** niedrig
- **Beschreibung:** `_erase_account_sessions` lädt und dekodiert **alle** nicht abgelaufenen Sessions, um die eines Benutzers zu finden. Das passiert bei Kontolöschung und Orga-Sperre (`moderation.py:136`) innerhalb der Transaktion, die Benutzer-, Event- und Anmeldezeilen sperrt.
- **Auswirkung:** Die Laufzeit wächst linear mit der Session-Anzahl (2 Wochen Lebensdauer × 1.000+ Gäste). Währenddessen bleiben die Zeilensperren gehalten, sodass parallele Buchungen/Check-ins für die betroffenen Events warten.
- **Lösungsvorschlag:** Da `session_version` bereits in den Session-Hash eingeht (`models.py:74-79`), genügt fachlich das Hochzählen. Das Aufräumen kann nach dem Commit erfolgen (`transaction.on_commit`) oder über eine eigene Tabelle `UserSession(user, session_key)`, die per Signal `user_logged_in` gepflegt wird.
- **Sicherheit des Befunds:** bestätigt (Code); Laufzeit nicht gemessen.

### F-019 · users · `users/forms.py:267-269`
- **Schweregrad:** niedrig
- **Beschreibung:** Der Passwort-Reset-Link wird aus `request.get_host()` und `use_https` (abhängig von `X-Forwarded-Proto`) gebaut, obwohl `PUBLIC_BASE_URL` für genau diesen Zweck existiert (`config/settings.py:367-368`).
- **Auswirkung:** Da `ALLOWED_HOSTS` laut Handover den Loopbackhost enthalten muss, kann ein Angreifer per `Host: 127.0.0.1` Reset-Mails mit unbrauchbaren Links an Opfer auslösen. Kommt die Anfrage über einen Pfad ohne korrektes `X-Forwarded-Proto`, entstehen `http://`-Links (Vermutung, Abhängigkeit zu M19/Nginx).
- **Lösungsvorschlag:** `reset_link = f"{settings.PUBLIC_BASE_URL}{reverse('password_reset_confirm', args=[uid, token])}"`.
- **Sicherheit des Befunds:** bestätigt (Code); Auswirkung über den Proxy-Pfad = Vermutung.

Geprüft ohne Befund: Verifizierungscodes (CSPRNG, 6 Stellen, 5 Versuche/Code, 5 Codes/h, `compare_digest`, Zeilensperren), Konto-Löschung (Sperrreihenfolge, Anonymisierung, Nachfolgeregelung Clan/Team, Mail- und Fehlerprotokoll-Bereinigung), Orga-Sperren (HMAC-Fingerprints statt Klartext, Advisory-Locks, Staleness-Check, Superuser-Schutz), Session-Invalidierung über `session_version` + Token-Generator, Passwort-Reset-Bestätigung (Ban-/Löschprüfung unter Zeilensperre), CSRF in allen Formularen, `sensitive_post_parameters` bei Kontolöschung, Timing-Ausgleich bei unbekanntem Benutzer, Audit-Kommando (0600, keine Rechteänderung).
Abhängigkeit zu M19: `get_client_ip` vertraut bei `BEHIND_PROXY=True` `X-Real-IP`/`X-Forwarded-For` (`auth_backends.py:24-56`). Ob Nginx diese Header auf allen Eingängen überschreibt, wird dort geprüft.
Testlücke: kein Test für Benutzernamen, die sich nur in der Schreibweise unterscheiden (F-015).

## M04 emails

### F-020 · emails · `emails/admin.py:336-340,449-451`, `emails/services.py:97-108`, `users/forms.py:269-276`
- **Schweregrad:** hoch
- **Beschreibung:** Die Outbox speichert den fertig gerenderten Mailtext (`body_text`, `body_html`) dauerhaft, auch bei sicherheitskritischen Vorlagen: `password_reset` mit gültigem Reset-Link (Standardlaufzeit 3 Tage, `PASSWORD_RESET_TIMEOUT` nicht gesetzt), `email_verification` (Aktivierungscode) und `email_change_verification`. `OutgoingEmailAdmin` zeigt beide Felder jedem Staff-Konto mit `emails.view_outgoingemail` an (typische Support-Rolle, um Zustellprobleme zu prüfen). Der Passwort-Reset ist öffentlich auslösbar.
- **Auswirkung:** Kontoübernahme bis hin zum Superuser. Ablauf: (1) Reset für die bekannte Admin-Adresse über `/password-reset/` anfordern, (2) Link im Admin unter „Ausgehende E-Mails“ lesen, (3) Passwort setzen. Im Probelauf lag der Link `https://testserver/password-reset-confirm/Mw/…/` in `body_text`, und ein Staff-Konto mit nur `view_outgoingemail` hatte Leserecht. Zusätzlich landen die Links in jedem DB-Backup. Verwandter Pfad: Wer `emails.change_generalemailsettings` hat, kann den Testmodus mit eigener `sandbox_redirect_email` aktivieren und erhält dann **alle** Mails inklusive Reset-Links. Diese Berechtigung ist damit superuser-äquivalent, das ist nicht dokumentiert.
- **Lösungsvorschlag:**
  1. Sensible Vorlagen kennzeichnen und deren Inhalt nach Versand/Ablauf leeren:
     ```python
     SENSITIVE_TEMPLATES = {'password_reset', 'email_verification', 'email_change_verification'}
     # OutgoingEmail.mark_sent / mark_expired / mark_failed_attempt(final)
     if self.template_key in SENSITIVE_TEMPLATES:
         values.update(body_text='', body_html='')
     ```
  2. Im Admin für diese Vorlagen den Inhalt nicht anzeigen:
     ```python
     def get_fieldsets(self, request, obj=None):
         fs = super().get_fieldsets(request, obj)
         if obj and obj.template_key in SENSITIVE_TEMPLATES:
             return [f for f in fs if f[0] != 'Inhalt']
         return fs
     ```
  3. `PASSWORD_RESET_TIMEOUT` z. B. auf 1 Stunde setzen und Reset-Mails mit `expires_at` einreihen.
  4. Im Handover/Sicherheitsbacklog festhalten, dass `change_generalemailsettings` nur Superusern gegeben werden darf.
- **Sicherheit des Befunds:** bestätigt (Probelauf in zurückgerollter Transaktion: Link in `body_text`, `has_view_permission=True` für ein Konto nur mit `view_outgoingemail`).

### F-021 · emails · `emails/services.py:117-132`
- **Schweregrad:** niedrig
- **Beschreibung:** Nach jedem eingereihten Mailauftrag startet `trigger_queue_processing()` im **Webprozess** einen Daemon-Thread, der `process_email_queue(limit=25)` ausführt, also SMTP-Versand mit bis zu `smtp_timeout` Sekunden. Laut Handover (Architekturdiagramm, Z. 17 und 101-105) übernimmt das ein separater Mail-Worker. Diese zweite Verarbeitungsstelle ist dort nicht erwähnt.
- **Auswirkung:** SMTP-Verbindungen und DB-Verbindungen (thread-lokal, nie explizit geschlossen) entstehen in jedem Gunicorn-Worker. Bei Lastspitzen (z. B. Anmeldeöffnung) laufen viele parallele Threads. Bei Gunicorn-Neustarts werden Daemon-Threads mitten im Versand beendet. Die Leases verhindern Doppelverarbeitung weitgehend, die im Handover beschriebene Unsicherheit „Zustellung ohne DB-Bestätigung“ tritt dadurch aber häufiger auf.
- **Lösungsvorschlag:** Den Thread-Trigger entfernen bzw. per Setting standardmäßig abschalten (`EMAIL_INLINE_TRIGGER=False`) und nur den dedizierten Worker verarbeiten lassen. Falls Latenz wichtig ist: Worker-Intervall senken oder `LISTEN/NOTIFY` nutzen. Im Thread mindestens `django.db.connection.close()` im `finally`.
- **Sicherheit des Befunds:** bestätigt (Code); Lastverhalten nicht gemessen.

### F-022 · emails · `emails/management/commands/process_email_queue.py:61-70`
- **Schweregrad:** niedrig
- **Beschreibung:** Die Daemon-Schleife fängt nur `KeyboardInterrupt`. Jede Exception außerhalb des Pro-Mail-`try` (z. B. DB-Verbindungsabbruch in `recover_stale_processing_emails` oder `GeneralEmailSettings.load()`) beendet den Worker. Ein SIGTERM-Handler für geordnetes Beenden fehlt ebenfalls.
- **Auswirkung:** Nach einem kurzen DB-Aussetzer läuft der Mailversand nur weiter, wenn die Container-Restart-Policy greift (Prüfung in M19). Bei manuellem Start nach Handover Z. 104 bleibt der Versand stehen, ohne dass es auffällt.
- **Lösungsvorschlag:**
  ```python
  from django.db import close_old_connections
  while not stop.is_set():
      try:
          close_old_connections()
          sent, failed = process_email_queue(limit=limit)
      except Exception:
          logger.exception('Queue-Durchlauf fehlgeschlagen; neuer Versuch nach Intervall')
      stop.wait(interval)
  ```
  mit `signal.signal(signal.SIGTERM, lambda *_: stop.set())`.
- **Sicherheit des Befunds:** bestätigt (Code); Absturz nicht nachgestellt.

### F-023 · emails · `emails/backends.py:230-233`
- **Schweregrad:** niedrig
- **Beschreibung:** Der Absender wird per f-String `f"{sender_name} <{sender_email}>"` gebaut, und `sender_name` wird nicht validiert.
- **Auswirkung:** Ein Name mit Komma (z. B. „Orga, LAN e.V.“) ergibt den Header `From: Orga, "LAN e.V." <orga@…>`, also zwei Mailboxen, eine davon ohne Domain. Das ist laut RFC 5322 ohne `Sender:` ungültig, viele Server weisen solche Mails ab oder stufen sie als Spam ein.
- **Lösungsvorschlag:** `from email.utils import formataddr; sender = formataddr((cfg.sender_name, cfg.sender_email))`.
- **Sicherheit des Befunds:** bestätigt (Header-Erzeugung mit Django nachgestellt); Zustellverhalten von Mailservern nicht getestet.

Geprüft ohne Befund: SMTP-Passwort-Verschlüsselung (Fernet, getrennter Schlüssel, kein Klartext-Echo im Formular), Kill-Switch/Sandbox/Mail-Pause bei Restore, Single-Pass-Platzhalterersetzung mit HTML-Escaping (`safe_format`), Outbox-Leases mit `skip_locked` und Worker-ID-Prüfung, Admin-Bereinigung (signiertes, benutzergebundenes Token, CSRF, Rechteprüfung), Status-Panel (`format_html`), DNS-Check (nur Admin, Domain aus Einstellungen).

## M05 events

### F-024 · events · `events/models.py:318-329` (`EventRegistration.user`/`.event` mit `CASCADE`), `users/admin.py:58-59`, `events/admin.py:100-117`
- **Schweregrad:** mittel
- **Beschreibung:** Das Projekt hat einen sorgfältigen Löschservice, der Konten anonymisiert und die Zahlungshistorie erhält (`users/services.py:213-286`). Die Admin-Löschfunktion für Benutzer (nur gesperrte Konten sind ausgenommen) und für Events umgeht ihn aber. Da `EventRegistration.user` und `EventRegistration.event` mit `on_delete=CASCADE` definiert sind, werden dabei auch **bezahlte** Anmeldungen gelöscht. Weitere Kaskaden betreffen u. a. `ClanSeatAllocation`, `MediaTemplate` und `ExternalTournament` am Event.
- **Auswirkung:** Ein Klick im Admin (Bestätigungsseite listet die Objekte zwar auf) vernichtet Zahlungs- und Check-in-Nachweise. Das betrifft Kassenabgleich, Rückerstattungen und Aufbewahrungspflichten, und ein Datenbank-Restore ist dann die einzige Rettung. Im Probelauf: Nach `user.delete()` waren 0 bezahlte Anmeldungen übrig, und das Event-Löschen war nicht durch `PROTECT` blockiert.
- **Lösungsvorschlag:** `on_delete=models.PROTECT` für `EventRegistration.user` und `.event` (Migration). Im `CustomUserAdmin` `has_delete_permission` auf `False` setzen und stattdessen eine Admin-Aktion „Konto anonymisieren“ anbieten, die `UserService.delete_account`-Logik ohne Passwortprüfung nutzt. Im `EventAdmin` Löschen nur für Events ohne Anmeldungen erlauben:
  ```python
  def has_delete_permission(self, request, obj=None):
      return super().has_delete_permission(request, obj) and not (obj and obj.registrations.exists())
  ```
- **Sicherheit des Befunds:** bestätigt (Probelauf in zurückgerollter Transaktion).

### F-025 · events · `events/views.py:675-681`, `events/templates/events/guest_list.html:158,217`
- **Schweregrad:** niedrig (fachliche/datenschutzrechtliche Entscheidung erforderlich)
- **Beschreibung:** `guest_list_view` ist ohne Anmeldung erreichbar und lädt bei Angabe eines Slugs **jedes** Event (`get_object_or_404(Event, slug=slug)`), auch Entwürfe sowie beendete und abgesagte Events. Angezeigt werden Benutzername, Clan, Sitzplatz und Bezahlstatus aller nicht stornierten Anmeldungen.
- **Auswirkung:** Personenbezogene Daten (Pseudonym + Zahlungsstatus + Sitzplatz) vergangener Veranstaltungen bleiben dauerhaft öffentlich abrufbar, ebenso Gästelisten nicht veröffentlichter Entwürfe (im Probelauf: Entwurf „Geheimer Entwurf“ anonym mit HTTP 200 und sichtbarem Benutzernamen). Die Datenschutzerklärung müsste diese Veröffentlichung abdecken. Das Handover erwähnt die Öffentlichkeit der Gästeliste nicht.
- **Lösungsvorschlag:** Slug-Zugriff auf veröffentlichte Status beschränken (`status__in=[OPEN, RUNNING]` bzw. `is_active=True`) oder für Nicht-Staff nur das aktive Event zulassen. Bezahlstatus nur für Staff oder die eigene Anmeldung anzeigen. Optional: Opt-out „in Gästeliste anzeigen“.
- **Sicherheit des Befunds:** bestätigt (anonymer Probeaufruf in zurückgerollter Transaktion).

### F-026 · events · `events/urls.py:17`, `events/views.py:829,851`, `events/admin.py:626-633`
- **Schweregrad:** niedrig
- **Beschreibung:** Sammelbefund kleinerer Korrektheitsmängel:
  1. Unbenannte Alias-Route `events/api/event/<id>/update-payment-check/`, nur von einem Test genutzt (`events/tests.py:1940`). Kein Frontend-Aufrufer gefunden, also toter Code.
  2. `redirect(request.META.get('HTTP_REFERER') or 'guest_list')`, Referer ungeprüft. Wegen POST + CSRF + Staff-Pflicht praktisch kaum ausnutzbar, aber ein Open-Redirect-Muster.
  3. `_check_overbooking` zählt mit `event.registrations.count()` auch **stornierte** Anmeldungen und meldet deshalb fälschlich Überbuchung.
- **Auswirkung:** Wartungsballast bzw. irreführende Admin-Warnung („Achtung! Es wurden mehr Plätze gebucht…“) nach Stornierungen.
- **Lösungsvorschlag:** Alias-Route und Test entfernen. Für den Redirect `url_has_allowed_host_and_scheme(ref, {request.get_host()}, require_https=request.is_secure())` verwenden. Beim Zählen `event.active_registrations_count` nutzen (schließt `CANCELLED` aus und berücksichtigt `reserved_ticket_count` analog zu `is_full`).
- **Sicherheit des Befunds:** bestätigt (Code).

Geprüft ohne Befund: Anmeldung/Reaktivierung (Kapazitätsprüfung unter Event-Zeilensperre, konsistente Sperrreihenfolge User → Event → Anmeldung), Zahlungs-/Stornoservice inkl. Clan-Finanzierung, Check-in (nur Staff, nur POST zustandsändernd, UUID- oder 8-stelliger CSPRNG-Code, kein PK-Fallback, Rate-Limit), QR-Endpunkte (nur Eigentümer/Staff, `no-store`), EPC-Payload (Zeilenumbrüche entfernt, Längen begrenzt), Scanner-Pagination mit `Prefetch` (keine N+1), Admin-Zahlungsübergang über Service, CSV-Export nur mit `view`-Recht (Formel-Injection geprüft: Benutzernamen erlauben nur `[\w.@+-]`, Vor-/Nachname sind nur durch Staff editierbar, daher kein praktischer Angriffsweg).
Weitergereicht an M17: `guest_list.html:381` setzt API-Meldungen per `innerHTML`; `scan_qr_api` gibt den gescannten Rohtext in `message` zurück (`events/views.py:592`). Geprüft wird dort, ob `checkin-scanner.js` diesen Text ungefiltert einfügt.

## M06 clans

### F-027 · clans · `clans/views.py:151-176`, `clans/admin.py:40-42`
- **Schweregrad:** niedrig
- **Beschreibung:** (1) `clan_create_view` prüft „bereits in einem Clan?“ außerhalb der Transaktion und ohne Sperre. Bei Doppel-Submit oder zwei Tabs laufen beide Requests an der Prüfung vorbei. Der zweite scheitert dann am DB-Constraint `unique_active_clan_membership_per_user` bzw. am eindeutigen Clannamen mit einer unbehandelten `IntegrityError`. (2) `ClanAdmin.member_count` führt pro Listenzeile eine eigene `COUNT`-Abfrage aus (N+1). (3) Beim Ersetzen des Logos bleibt die alte Datei in `media/clan_logos/` liegen.
- **Auswirkung:** (1) HTTP 500 und ein Eintrag im Fehlerprotokoll statt einer Meldung. Die Daten bleiben konsistent, da die Transaktion zurückrollt. (2) Langsamere Admin-Liste bei vielen Clans. (3) Verwaiste Dateien wachsen unbegrenzt und landen in Medien-Backups.
- **Lösungsvorschlag:** (1) Prüfung in `transaction.atomic()` nach `select_for_update()` auf den eigenen User verlegen bzw. `IntegrityError` abfangen und eine Meldung ausgeben. (2) `get_queryset` mit `.annotate(member_count=Count('memberships', filter=Q(memberships__status='ACCEPTED')))`. (3) Alte Datei per `transaction.on_commit(lambda: storage.delete(old_name))` entfernen, wie es `users/services.py:302-305` bereits macht.
- **Sicherheit des Befunds:** bestätigt (Code); (1) Race nicht praktisch nachgestellt.

Geprüft ohne Befund: Clan-Passwort (Django-Hasher, `validate_password`, Neu-Hashing von Klartext in `save()`), Beitritt per Passwort (Rate-Limits pro User/IP/Clan, Prüfung unter Sperre), Admin-Verwaltung (Rechte und Identität nach Sperre neu geprüft, Schutz des letzten aktiven Admins, Nachfolge), Logo-Upload (Endung, 2 MB, Pillow-`verify`, max. 500×500 px), Website-Links (`URLField` erlaubt nur http/https/ftp, `rel="noopener"`), Annotationen in der Clanliste (keine N+1), CSRF/POST-Pflicht für alle Änderungen.

## M07 seating

### F-028 · seating · `seating/views.py:244-257`
- **Schweregrad:** niedrig
- **Beschreibung:** `reserve_seat_api` sperrt `Event.objects.select_for_update().get(pk=event_id)` im selben `try`-Block, fängt aber nur `EventRegistration.DoesNotExist`. Bei einer nicht existierenden Event-ID entsteht eine unbehandelte `Event.DoesNotExist`.
- **Auswirkung:** Jeder eingeloggte Benutzer kann per `POST /seating/api/reserve/<beliebige-ID>/` HTTP 500 und je einen `SystemErrorLog`-Eintrag erzeugen (Probelauf: 1 Request → 1 Eintrag). Das verstärkt F-010.
- **Lösungsvorschlag:** `except (EventRegistration.DoesNotExist, Event.DoesNotExist):` mit 404/403-JSON, analog zu `clan_seat_update` (`seating/views.py:722`).
- **Sicherheit des Befunds:** bestätigt (Probelauf in zurückgerollter Transaktion).

### F-029 · seating · `seating/clan_services.py:38-44` (`seating_write`)
- **Schweregrad:** niedrig (Vermutung, Messung empfohlen)
- **Beschreibung:** Jeder schreibende Sitzplatz-Endpunkt (Gast-Reservierung, -Freigabe, Admin-Zuweisung/-Sperre/-Freigabe) läuft über `seating_write`. Das holt zuerst `lock_configuration()`, also eine `SELECT … FOR UPDATE`-Sperre auf die eine `ClanSeatConfiguration`-Zeile. Damit werden **alle** Sitzplatzänderungen aller Gäste global serialisiert, auch ohne Clan-Bezug.
- **Auswirkung:** Bei Ansturm (Öffnung der Sitzplatzwahl, 1.000+ Gäste laut Handover) warten Requests aufeinander. Gunicorn-Worker blockieren, und Timeouts werden wahrscheinlicher. Die Korrektheit ist gesichert (Nebenläufigkeitstests vorhanden), der Durchsatz nicht gemessen. `docs/performance-smoke-2026-09-26.md` liegt vor der Einführung der Clan-Holds.
- **Lösungsvorschlag:** Lastmessung mit parallelen Reservierungen (`scripts/http_performance_smoke.py` erweitern). Falls nötig, die globale Sperre nur nehmen, wenn das Event Clan-Allocations hat, oder auf eine Advisory-Lock pro Event (`pg_advisory_xact_lock(event_id)`) umstellen.
- **Sicherheit des Befunds:** Code bestätigt, Auswirkung Vermutung.

### F-030 · seating · `templates/seating/seating_plan.html`, `seating/views.py:59-62`
- **Schweregrad:** niedrig
- **Beschreibung:** `templates/seating/seating_plan.html` wird von keiner View und keinem Template referenziert (verwendet wird `seating/templates/seating/seating.html`). `cells_json` wird im Editor-Kontext berechnet, das Template nutzt aber `cells_data|json_script`.
- **Auswirkung:** Toter Code. Bei Änderungen an Sitzplan-Templates besteht Verwechslungsgefahr.
- **Lösungsvorschlag:** Datei und Kontextvariable entfernen.
- **Sicherheit des Befunds:** bestätigt (grep über `*.py`/`*.html`).

Geprüft ohne Befund: Reservierung/Freigabe (Zeilensperren, eine Reservierung pro Anmeldung per Constraint, Status-/Bann-/Storno-/Clan-Prüfungen), Admin-Endpunkte (Staff + `change_seatingcell`/`change_seatingplan`), Editor-Speichern (Typ-, Bereichs- und Versionsprüfung), öffentliche Sitzplan-API (Personendaten nur für eingeloggte Benutzer), Clan-Sammelzahlungen (Berechtigung Clan-Admin oder Orga-Recht, Referenz aus UUID, QR nur für offene Zahlungen), Clan-Hold-Worker (Exception-Handling, `connections.close_all()`), `json_script` statt `|safe` für eingebettete Daten.

## M08 tournaments

### F-031 · tournaments · `tournaments/management/commands/seed_tournaments.py:14-24,66-82`
- **Schweregrad:** mittel
- **Beschreibung:** Das Management-Command legt die Konten `gamer_1` bis `gamer_8` mit dem festen Passwort `password123` an. Für **bereits existierende** Konten dieses Namens setzt es das Passwort per `set_password` neu (`get_or_create` + `set_password` + `save`). Außerdem markiert es deren Anmeldung im aktiven Event als `PAID` und eingecheckt und erzeugt ohne aktives Event ein neues, aktives Event im Status `RUNNING`. Es gibt keine `DEMO_MODE`-Prüfung (anders als `seed_demo_data`, `configuration/demo.py:109-110`).
- **Auswirkung:** Ein versehentlicher Aufruf auf Produktion erzeugt bekannte Zugangsdaten mit Turnierberechtigung, verfälscht Zahlungs- und Check-in-Daten und übernimmt ggf. reale Konten namens `gamer_N`. Das widerspricht der Zusage im Handover Z. 79 („Keine Standardkonten oder Standardpasswörter“). `AUDIT_BERICHT.md:100` stuft das Kommando bereits als veraltet ein und empfiehlt die Löschung, umgesetzt ist das nicht.
- **Lösungsvorschlag:** Kommando löschen (abgelöst durch `seed_demo_data`). Falls es für Entwicklung gebraucht wird: `if not settings.DEMO_MODE: raise CommandError(...)`, keine Passwörter setzen (`password=None` wie in `configuration/demo.py:77-79`) und nie bestehende Konten verändern.
- **Sicherheit des Befunds:** bestätigt (Code); nicht ausgeführt.

Geprüft ohne Befund (Schwerpunkt Berechtigungen und Datenintegrität): Leitungsaktionen (Öffnen/Schließen, Auslosung, Swiss, Ergebnisse bestätigen, Playoffs freigeben, Match starten) prüfen `is_managed_by` bzw. `can_view_drafts` **im Service** unter Sperre. Ergebnismeldung durch Teilnehmer nur für beteiligte Teams (`services/matches.py:225-245`). Entwürfe sind für Nicht-Staff unsichtbar (`visible_to`). Einladungscodes haben 128 Bit (`secrets.token_hex(16)`) und ein Versuchslimit pro User/IP. Externe Turnierlinks nur über HTTPS, ohne Credentials und Steuerzeichen. `tournament_detail` lädt Daten gebündelt (keine N+1-Muster gefunden). Keine `|safe`/`mark_safe` in Turnier-Templates/Admin.
Hinweis: Das Rechtemodell erlaubt **jedem** Staff-Konto die Leitung **aller** Turniere (`models.py:398-410`). Das ist eine bewusste Designentscheidung, im Handover aber nicht beschrieben.
Weitergereicht an M16: `{% t %}` innerhalb von JavaScript-Stringliteralen ohne `escapejs` (`templates/tournaments/team_detail.html:331,343`).

## M09 contact

### F-032 · contact/projektweit · `contact/tokens.py:12-20`, `contact/views.py:32-36`; kein `clearsessions` im Repo
- **Schweregrad:** niedrig
- **Beschreibung:** Sessions liegen in PostgreSQL (`django.contrib.sessions`, Default-Engine). Abgelaufene Sessions werden nirgends bereinigt: kein `clearsessions` in Entrypoint, Worker, Compose oder Doku. Zusätzlich legt jeder **anonyme** `GET /kontakt/` (bei aktivem Formular) über `make_submission_token` eine neue Session-Zeile an, ohne Rate-Limit auf GET.
- **Auswirkung:** `django_session` wächst unbegrenzt, und ein einfacher Skriptaufruf erzeugt beliebig viele Zeilen. Folgen sind größere DB und Backups. Außerdem iteriert `users/services.py:384` bei jeder Kontolöschung/Sperre über alle nicht abgelaufenen Sessions (siehe F-018).
- **Lösungsvorschlag:** `python manage.py clearsessions` periodisch ausführen, z. B. im Clan-Hold-Worker einmal täglich oder als eigener Compose-Dienst/Cron, und im Handover/`docs/updating.md` dokumentieren. Für das Kontaktformular den Scope erst beim POST benötigen oder ein signiertes Cookie (`signing.dumps` mit kurzer Laufzeit) statt Session verwenden.
- **Sicherheit des Befunds:** bestätigt (Code, Repo-weite Suche).

Geprüft ohne Befund: signiertes, an Session und Benutzer gebundenes Idempotenz-Token (1 h), Honeypot-Feld, Limits pro Absenderadresse (5/h, 60 s Abstand) und IP-Hash (100/10 min) dauerhaft in der DB statt im Cache, Advisory-Locks in fester Reihenfolge, Empfänger nur aus der Konfiguration (kein offenes Relay), Reply-To validiert, Betreff gegen Zeilenumbrüche geprüft, gesperrte/gelöschte Konten ausgeschlossen, Templates ohne `|safe`.
Abhängigkeit zu M19: Das IP-Limit nutzt `get_client_ip` (vertraut `X-Real-IP`, siehe M03).

## M10 info · M11 knowledge · M12 news · M13 sponsors · M14 media_designer · M15 backups

**Keine Auffälligkeiten** (gezielte Prüfung von Ausgabe-Escaping, Uploads, Zugriffsrechten und Datei-/Pfadbehandlung):
- **info:** HTML wird beim Speichern (`info/models.py:201-223`) **und** bei der Ausgabe (`|safe_html`) bereinigt. Embeds nur von freigegebenen HTTPS-Origins (keine Credentials, IDNA-normalisiert, nie die eigene Origin), `iframe` mit `sandbox` und seitenbezogener `frame-src`-CSP. Entwürfe nur mit `view/change_eventinfo`.
- **knowledge:** Alle Views nur für aktive Staff-Konten mit `never_cache`. Anhänge liegen außerhalb von `MEDIA_ROOT` (`PrivateStorage.url()` wirft absichtlich) und werden mit `nosniff`, `default-src 'none'; sandbox` und standardmäßig als Download ausgeliefert. Upload-Allowlist, 10 MB, Bildformat-/Pixelprüfung (Dekompressionsbombe), Dateiname per UUID. Inhalte werden vor der Ausgabe bereinigt (`knowledge/views.py:131,219`), `<img>` nur auf interne Anhang-URLs.
- **news:** `rendered_content` bereinigt (`news/models.py:85-89`), Vorschaubilder nur aus `/media/` bzw. `/static/` (keine Drittanbieter-Requests), nur veröffentlichte Artikel öffentlich.
- **sponsors:** Beschreibung beim Speichern bereinigt und mit `|safe_html` ausgegeben, Links mit `rel="noopener noreferrer"`.
- **media_designer:** Nur Staff. Font-Uploads werden per Magic Bytes und testweisem Laden mit Pillow geprüft, Größenlimits für Bilder (10 MB) und Fonts (5 MB).
- **backups:** Nur aktive Staff-Superuser (`backups/views.py:19-21`), CSRF auf allen POSTs, Archive mit AES-256-GCM authentifiziert (nur selbst erstellte Sicherungen werden akzeptiert). Entpacken mit Namens-Allowlist (`safe_name`, kein `..`/absolut/Backslash/Symlink), Datei-, Größen- und Manifestlimits, Job-IDs per Regex validiert, Fortschritts-URL als 256-Bit-Capability mit `compare_digest`, Worker fängt Fehler pro Job ab. Raw SQL nur mit internen, quotierten Bezeichnern (`backups/database.py:50-85`).

Einzige Kleinigkeiten wurden unter F-003 erfasst (ungenutzte Variable `backups/services.py:92`, ungenutzter Import `backups/apps.py:9`, beabsichtigter Side-Effect-Import).

## M16 Globale Templates

### F-033 · Templates · `templates/tournaments/team_detail.html:331,343`, `templates/sponsors/sponsor_list.html:224-225`, `templates/auth/verify_email.html:143`
- **Schweregrad:** niedrig
- **Beschreibung:** An fünf Stellen steht `{% t %}` (admin-editierbarer Text) direkt in einem JavaScript-Stringliteral innerhalb eines Inline-`<script>`. Django escaped dort nur HTML (`'` → `&#x27;`), nicht JavaScript (`\`, Zeilenumbrüche, `</script>` wird zu `&lt;/script&gt;`).
- **Auswirkung:** Kein XSS, da die Werte per `innerHTML` als Text dekodiert bzw. als reine Strings verwendet werden (geprüft). Ein Übersetzungstext mit Backslash oder Zeilenumbruch erzeugt aber einen JavaScript-Syntaxfehler und legt die Kopier- bzw. „Mehr lesen“-Funktion still.
- **Lösungsvorschlag:** `{% t "key" as label %}{{ label|escapejs }}` bzw. Texte gebündelt per `json_script` übergeben (wie bereits im Check-in-Scanner, `checkin_scanner.html:202`).
- **Sicherheit des Befunds:** bestätigt (systematische Suche über alle Inline-Skripte: 5 Übersetzungen, 9 unkritische numerische/CSRF-Variablen, 6 korrekt escaped).

Ergänzung zu **F-006 (CSP)**: Die Templates enthalten 57 Inline-Event-Handler (`onclick`/`onsubmit`), 9 Inline-`<script>`-Blöcke und über 1.100 `style`-Attribute. Eine CSP ohne `'unsafe-inline'` erfordert daher vorher eine Auslagerung. Positiv: Es gibt keine externen Skript-/Style-/Bildquellen in Templates, die Offline-Aussage im Handover stimmt.

Geprüft ohne Befund: alle `|safe`-Ausgaben (`icon_svg` → F-011; `reading_content`/`revision_content` vorher bereinigt; `theme_css_vars` aus validierten Werten; `custom_css` validiert; `user_info` in `admin/seating/live_preview.html:16` stammt aus `format_html`), Nachrichten (`{{ message }}` escaped), Logout als POST mit CSRF, `500.html` eigenständig ohne DB-Zugriff (siehe aber F-012), keine `autoescape off`-Blöcke.
Code-Qualität: Die Navigation ist in `base.html` dreifach dupliziert (Desktop Z. 80-100, Mobile Z. 170-185, Modal Z. 215-230) einschließlich identischer Aktiv-Logik. Ein Include mit Parametern würde Pflegefehler vermeiden.

## M17 Statische Dateien (JS/CSS)

### F-034 · static · `static/js/admin-seat-picker.js:76-93` (eingebunden über `templates/admin/events/assigned_seat_picker.html:38`)
- **Schweregrad:** mittel
- **Beschreibung:** Der Sitzplatz-Picker im Admin (Anmeldung bearbeiten → „Sitzplatz-Zuweisung“) baut das Raster per String-Konkatenation und `container.innerHTML = gridHtml`. Dabei landen `c.seat_label` (Inhalt, `title`-Attribut und JS-Stringliteral im `onclick`) und `c.text_label` **unescaped** im Markup. `seat_label` ist Freitext bis 20 Zeichen ohne Zeichenprüfung (`seating/services.py:163-164`) und kann von jedem Staff-Konto mit `seating.change_seatingplan` im Sitzplan-Editor gesetzt werden. Die Werte kommen über `/seating/api/plan/<id>/` zurück.
- **Auswirkung:** Gespeichertes XSS im Django-Admin-Kontext. Beispiel: Der Sitzname `',import('//a.bc'),'` (genau 20 Zeichen) ergibt `onclick="selectSeatForUser(1, 1, 1, '',import('//a.bc'),'', 'admin')"`. Klickt ein Superuser diesen Platz an, wird ein beliebiges JavaScript-Modul der Angreiferdomain in der Admin-Origin ausgeführt (Admin-Aktionen mit dessen Session/CSRF-Token, z. B. Rechte vergeben). Kurze Payloads wie `<svg onload=alert()>` (20 Zeichen) funktionieren bereits im Zellinhalt. Das ist eine Rechteausweitung von „Sitzplan bearbeiten“ zu Superuser.
- **Lösungsvorschlag:** DOM per API aufbauen statt per HTML-String:
  ```javascript
  const cell = document.createElement('div');
  cell.textContent = content;
  cell.title = title;
  if (isClickable) cell.addEventListener('click',
      () => selectSeatForUser(regId, x, y, c.seat_label || '', username));
  grid.appendChild(cell);
  ```
  Zusätzlich serverseitig `seat_label`/`text_label` auf ein Zeichen-Whitelist-Muster beschränken (z. B. `^[\w .\-/#]{0,20}$`). Langfristig schützt eine CSP ohne `'unsafe-inline'` (F-006).
- **Sicherheit des Befunds:** bestätigt: Erzeugtes Markup mit Node nachgestellt, Payloadlänge 20 passt durch die Kürzung auf 20 Zeichen, keine Zeichenfilterung. Die Ausführung im Browser wurde nicht nachgestellt.

### F-035 · static/templates · `static/js/dashboard.js:111`, `events/templates/events/guest_list.html:381`
- **Schweregrad:** niedrig
- **Beschreibung:** Zwei Stellen schreiben admin-editierbare Systemtexte per `innerHTML`: (1) `data-not-configured-text="{% t 'dash_seat_plan_not_configured' %}"` wird über `dataset` gelesen. Dabei werden die HTML-Entities wieder dekodiert, und der Text wird ins Dashboard-Minimap-Element eingefügt (öffentliche Startseite, wenn kein Sitzplan existiert). (2) Toast der Gästeliste mit API-Meldung `msg_payment_check_updated`.
- **Auswirkung:** Ein Staff-Konto mit `change_systemtranslation` kann Skript in die öffentliche Startseite einschleusen (z. B. `<img src=x onerror=…>` als Übersetzungstext). Da diese Rolle über F-009 ohnehin den `SECRET_KEY` erreicht, ist der Zusatzschaden gering. Es ist aber ein weiterer Grund, Übersetzungen strikt als Text zu behandeln.
- **Lösungsvorschlag:** `textContent` verwenden: `const s = document.createElement('span'); s.className = 'minimap-empty'; s.textContent = container.dataset.notConfiguredText || '…'; container.replaceChildren(s);` und analog im Toast.
- **Sicherheit des Befunds:** bestätigt (Code); nicht im Browser ausgeführt.

Geprüft ohne Befund: Check-in-Scanner (Scan-Ergebnisse inkl. gescanntem Rohtext ausschließlich per `textContent`, Texte per `json_script`; damit ist der Querverweis aus M05 erledigt), öffentlicher Sitzplan (`textContent`/`title`-Property/`setAttribute`), Zeilen-HTML des Scanners serverseitig gerendert, Countdown/Statistiken nur mit statischen Strings bzw. Zahlen. CSS: nur lokale Fonts (`static/css/fonts.css`), keine externen Importe.
Node-Tests: `node --test scripts/tests/*.test.cjs` → 31/31 bestanden (Node 24.18; CI nutzt 22).

## M19 Deployment

Querverweis aus M03/M09 **erledigt**: Nginx setzt auf den öffentlichen Eingängen 80/443 `X-Real-IP`, `X-Forwarded-For` und `X-Forwarded-Proto` selbst und leert `CF-Connecting-IP` (`nginx/templates/default.conf.template:51-55,70-73,185-199`). Nur der unveröffentlichte Tunnel-Eingang 8080 übernimmt Cloudflare-Angaben. Die IP-Ermittlung in `users/auth_backends.py` ist damit im Compose-Betrieb nicht fälschbar. Ergänzung zu **F-006**: Auch Nginx setzt keine CSP, die Lücke besteht also auf beiden Ebenen.

### F-036 · Deployment · `docker-compose.yml:20-27`, `config/settings.py:179-185`
- **Schweregrad:** mittel
- **Beschreibung:** Redis läuft ohne Passwort (`requirepass` fehlt) und wird zusätzlich am Host veröffentlicht (`127.0.0.1:6379:6379`). Djangos `RedisCache` serialisiert Werte mit `pickle` (bestätigt in `django/core/cache/backends/redis.py`, `RedisSerializer`). Gelesene Cache-Werte werden von allen Webworkern deserialisiert (z. B. `navigation_items`, `site_customization`, `general_configuration`).
- **Auswirkung:** Jeder Prozess bzw. Benutzer mit Zugriff auf den Host-Loopback (z. B. ein anderer Dienst auf demselben VPS oder eine SSRF-Lücke in einer Nachbaranwendung) kann ein präpariertes Pickle in einen dieser Schlüssel schreiben und damit **Codeausführung im Web-Container** erreichen. Ausnutzbarkeit hängt von der Hostumgebung ab, deshalb nicht „hoch“.
- **Lösungsvorschlag:** In Produktion den Host-Port nicht veröffentlichen (Compose-Override nur für Entwicklung) und ein Passwort setzen:
  ```yaml
  redis:
    command: ["redis-server", "--requirepass", "${REDIS_PASSWORD:?}"]
    # ports: nur in docker-compose.override.yml für lokale Entwicklung
  ```
  `REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/1`, Healthcheck `redis-cli -a "$REDIS_PASSWORD" ping`. Dasselbe gilt sinngemäß für den veröffentlichten PostgreSQL-Port (`docker-compose.yml:4-5`), der dort aber durch ein Passwort geschützt ist.
- **Sicherheit des Befunds:** Konfiguration und Pickle-Serializer bestätigt; Angriff nicht durchgeführt.

### F-037 · Deployment · `docker-compose.yml:3,21,127`, `Dockerfile:1`
- **Schweregrad:** mittel (Vermutung bzgl. Patchstand)
- **Beschreibung:** `nginx:1.27-alpine` bezeichnet einen Mainline-Zweig von 2024/2025. Nach dem Release-Modell von nginx bekommt ein Mainline-Zweig nach Erscheinen des Nachfolgers keine Fixes mehr, der Tag bleibt also auf dem letzten 1.27-Patch stehen. `postgres:16-alpine`, `redis:7-alpine` und `python:3.12-slim-bookworm` sind dagegen gleitende Tags ohne Digest, während Certbot und cloudflared per Digest gepinnt sind. Das Handover (Z. 35) nennt „Nginx 1.27“ als maßgeblichen Stand.
- **Auswirkung:** Der internetseitige Reverse Proxy erhält vermutlich keine Sicherheitsupdates mehr. Die gleitenden Tags machen Builds nicht reproduzierbar und können ungeprüfte Versionssprünge einspielen.
- **Lösungsvorschlag:** Auf den aktuellen **stable**-Zweig von nginx wechseln (z. B. `nginx:<stable>-alpine`) und alle Basisimages mit `@sha256:` pinnen, Updates per Renovate/Dependabot. CI-Smoke (`scripts/container_smoke.py`) deckt den Wechsel ab.
- **Sicherheit des Befunds:** Konfiguration bestätigt. Dass 1.27 keine Fixes mehr erhält, ist eine Vermutung aus dem nginx-Release-Modell (nicht online verifiziert).

### F-038 · Deployment · `Dockerfile:9-17,38`, `.dockerignore`, `initial_data.json`
- **Schweregrad:** niedrig
- **Beschreibung:** (1) Das Laufzeitimage behält `build-essential`, `libpq-dev`, `netcat-openbsd` und `curl`, obwohl `psycopg[binary]` und Pillow-Wheels keinen Compiler brauchen (kein Multi-Stage-Build). (2) `COPY . /app/` übernimmt `docs/` (inkl. Screenshots), `scripts/tests/` und `initial_data.json`, weil sie nicht in `.dockerignore` stehen. (3) `initial_data.json` enthält 13 Benutzer mit **nutzbaren PBKDF2-Passwort-Hashes**, darunter einen Superuser (Platzhalter-Domain `entailsng.local`), und liegt damit im Git-Verlauf und in jedem Image.
- **Auswirkung:** Größere Angriffsfläche und Images. Offline-Knacken der Hashes ist möglich. Falls ein Entwickler ein dort verwendetes Passwort andernorts wiederverwendet, ist dieses gefährdet. `AUDIT_BERICHT.md:98,122` empfiehlt das Entfernen bereits, nennt die Hashes aber nicht.
- **Lösungsvorschlag:** Multi-Stage-Build oder Build-Pakete nach `pip install` per `apt-get purge` entfernen. `.dockerignore` um `docs/`, `scripts/tests/`, `initial_data.json`, `*.md` (außer benötigten) ergänzen. `initial_data.json` und den zugehörigen Test (`seating/tests.py:1659`) entfernen. Prüfen, ob die enthaltenen Passwörter irgendwo noch genutzt werden.
- **Sicherheit des Befunds:** bestätigt (Datei ausgewertet, nur Zählwerte ausgegeben).

### F-039 · Deployment · `docker-compose.yml:64-124`, `entrypoint.sh:49-66`
- **Schweregrad:** niedrig
- **Beschreibung:** (1) Die Worker-Container `email_worker`, `clan_seat_worker` und `backup_worker` haben keinen Healthcheck. (2) `email_worker` setzt nur `SKIP_ENTRYPOINT_WAIT`/`SKIP_ENTRYPOINT_MIGRATION` und führt deshalb bei jedem Start `collectstatic` (in sein Container-Dateisystem ohne Volume) sowie alle drei Seeds aus. Die anderen Worker nutzen `SKIP_ENTRYPOINT_INIT=1`. (3) `start.sh:69` startet `runserver` auf `0.0.0.0` mit dem von `install.sh:56` gesetzten `DEBUG=True`. Djangos Debug-404-Seite listet dann allen Geräten im LAN sämtliche URL-Muster (laut Handover Z. 79 nur für Entwicklung, aber ohne Warnhinweis im Skript).
- **Auswirkung:** Ein hängender Worker (z. B. blockierter SMTP-Connect) bleibt unbemerkt, da nur Abstürze per `restart: unless-stopped` abgefangen werden (F-022 ist im Compose-Betrieb dadurch entschärft, ein Hänger aber nicht). Unnötige Startzeit und Schreiblast. Informationspreisgabe im LAN bei Nutzung von `start.sh` während einer Veranstaltung.
- **Lösungsvorschlag:** Worker schreiben pro Durchlauf einen Zeitstempel (z. B. `/tmp/worker-heartbeat`), Healthcheck `test: ["CMD-SHELL", "find /tmp/worker-heartbeat -mmin -2 | grep -q ."]`. Für `email_worker` `SKIP_ENTRYPOINT_INIT=1` setzen. In `start.sh` auf `127.0.0.1` binden oder bei `DEBUG=True` + `0.0.0.0` deutlich warnen.
- **Sicherheit des Befunds:** bestätigt (Konfiguration).

Geprüft ohne Befund: Non-Root-User im Image, Web-Port 8000 nicht am Host veröffentlicht, Healthcheck `/api/health/` (DB + Cache), `depends_on` mit `service_healthy`, private Medien/Backups nicht im Nginx-Container gemountet, HTTP→HTTPS-Redirect, TLS 1.2/1.3 mit AEAD-Ciphers, Session-Tickets aus, Upload-Limit 25 MB bzw. 1 GB nur für `/admin/backups/`, `.env` per `.gitignore`/`.dockerignore` ausgeschlossen, Entrypoint bricht bei Seed-Fehlern ab (`set -e`) und pausiert bei unterbrochenem Restore, `install.sh` erzeugt Zufallsschlüssel und überschreibt keine vorhandene `.env`.

## M20 CI und Testabdeckung

### F-040 · CI · `.github/workflows/ci.yml:1-12,51-128`
- **Schweregrad:** niedrig
- **Beschreibung:** Der Workflow setzt keinen `permissions:`-Block, sodass der `GITHUB_TOKEN` mit den Repository-Standardrechten läuft (je nach Einstellung Schreibrechte). Drittanbieter-Actions sind nur per Tag gepinnt (`actions/checkout@v4`, `setup-python@v5`, `setup-node@v4`, `upload-artifact@v4`), nicht per Commit-SHA. Ein Linter-/Formatter-Lauf fehlt (laut Handover Z. 144 bewusst noch nicht eingerichtet, vgl. F-003).
- **Auswirkung:** Bei einer kompromittierten Action oder einem verschobenen Tag läuft fremder Code mit Repo-Token. Ungenutzte Importe/Variablen fallen nicht automatisch auf.
- **Lösungsvorschlag:** Auf oberster Ebene `permissions: { contents: read }` setzen, Actions per SHA pinnen (Kommentar mit Version) und einen Schritt `pip install ruff==<pin> && ruff check --select F,E9,B .` ergänzen.
- **Sicherheit des Befunds:** bestätigt (Workflow-Datei).

**Testlauf und Abdeckung** (Wegwerf-PG 18.6, Django 6.0.9, CI-äquivalente Umgebung, Redis → LocMem): 1335 Tests OK in 269 s, 0 übersprungen. Zeilenabdeckung des Produktivcodes **88 %** (15.199 Anweisungen, 1.772 nicht ausgeführt; ohne Migrationen, Tests, `scripts/`). 99 Dateien sind vollständig abgedeckt.

Lücken mit Bezug zu Befunden oder Betriebsrisiko:
| Datei | Abdeckung | Anmerkung |
|---|---|---|
| `emails/management/commands/process_email_queue.py` | 68 % | Daemon-Schleife ungetestet (F-022) |
| `seating/management/commands/process_clan_seat_holds.py` | 0 % | Worker-Schleife ungetestet |
| `backups/management/commands/process_backup_jobs.py` | 0 % | Worker-Schleife ungetestet |
| `emails/management/commands/email_doctor.py` | 0 % | Diagnosekommando komplett ungetestet |
| `emails/diagnostics.py` / `emails/dns_checker.py` | 42 % / 70 % | SMTP-Fehlererklärung, DNS-Prüfung |
| `seating/clan_payment_views.py` | 58 % | Fehler- und Randpfade der Clan-Sammelzahlung |
| `users/rate_limits.py` | 62 % | Redis-Zweig nie ausgeführt (Tests nutzen LocMem; F-017) |
| `seating/views.py` | 76 % | u. a. Fehlerpfad aus F-028 |
| `backups/views.py`, `backups/locking.py` | 70 % / 74 % | Restore-/Wartungspfade |
| `configuration/views.py` | 72 % | Health-Endpoint bei DB-/Cache-Ausfall |
| Admin-Klassen (`users/`, `emails/`, `clans/`, `info/`, `seating/clan_payment_admin.py`) | 74–79 % | Admin-Aktionen und Berechtigungszweige |

Inhaltliche Testlücken (unabhängig von der Zeilenabdeckung), jeweils zu einem Befund: Format-String-Platzhalter in Übersetzungen (F-009), Sichtbarkeit sensibler Outbox-Inhalte (F-020), Escaping im Admin-Sitzplatz-Picker (F-034, JS ungetestet), SVG mit Processing Instruction (F-011), Benutzernamen in anderer Schreibweise (F-015), 500-Handler bei DB-Ausfall (F-012), Kaskaden beim Admin-Löschen (F-024).

## M21 Doku-Abgleich und Repo-Hygiene

Alle 31 Dateiverweise im Handover existieren. Bestätigt wurden u. a.: 9 Themes, 6 Turniermodi, Services-Paket `tournaments/services/`, `WEB_CONCURRENCY=3`, WhiteNoise in der Middleware, private Anhänge nur in Web/Backup-Worker, LocMemCache in Tests, irreversible Migration `tournaments/0017`, Sessions/Codes löschen und Mail pausieren nach Restore (`backups/database.py:83-85`), keine externen Frontend-Ressourcen.

**Abweichungen zwischen Handover und Code** (als Befund geführt bzw. hier gesammelt):
| Handover | Tatsächlicher Stand | Bezug |
|---|---|---|
| Dateiname `developers_handover.md` (Auftrag) | `DEVELOPER_HANDOVER.md` | F-002 |
| Z. 33: Pythonpakete „vollständig gepinnt“ | Nur direkte Abhängigkeiten gepinnt, keine Hashes | F-008 |
| Z. 32: Django 6.0.9 maßgeblich | Lokale `.venv` hat 6.0.7 | F-001 |
| Z. 35: „Nginx 1.27“ als maßgeblicher Stand | vermutlich nicht mehr gepflegter Mainline-Zweig | F-037 |
| Z. 17, 101-105: Mailversand über separaten Mail-Worker | zusätzlich Versand-Threads im Webprozess | F-021 |
| Z. 79: „Keine Standardkonten oder Standardpasswörter“ | `seed_tournaments` setzt `password123` | F-031 |
| Z. 93: `initial_data.json` nur historischer Snapshot | Enthält nutzbare Passwort-Hashes, liegt im Image | F-038 |
| Z. 160: Rechte-Risiko nur als USERS-03 (`change_user`) benannt | Weitere faktisch superuser-äquivalente Rechte: `change_systemtranslation`, `view_outgoingemail`, `change_generalemailsettings`, `change_seatingplan` | F-009, F-020, F-034 |
| Z. 119: „Turniere … Podium erst nach expliziter Bestätigung“ | bestätigt; ergänzend: jedes Staff-Konto darf jedes Turnier leiten (nicht dokumentiert) | M08-Hinweis |
| kein Hinweis auf Session-Bereinigung | `clearsessions` fehlt vollständig | F-032 |
| kein Hinweis auf Öffentlichkeit der Gästeliste | öffentlich, inkl. Zahlungsstatus und Entwürfe | F-025 |

`AUDIT_BERICHT.md` (18.10.2026, nicht im Handover verlinkt) listet weitere Aufräumkandidaten (veraltete Skripte, Screenshots, Doku). Die Punkte zu `seed_tournaments` und `initial_data.json` sind dort als „Löschen“ markiert, aber nicht umgesetzt.
