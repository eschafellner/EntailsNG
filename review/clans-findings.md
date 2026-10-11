Verifikationszusammenfassung (9. Oktober 2026): **3 BESTÄTIGT / 0 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Stufe 2: Alle Clan-Findings über ihre URL, Login/CSRF, Formulare, Models, Verwaltungslocks und Admin-Gegenpfade geprüft. CLANS-03 erneut mit echtem ModelForm/Model in isolierter Django-Konfiguration reproduziert; DB-Validierungsabfragen und Model-Schreiboperation gemockt, keine DB-/Dateiänderung.

Zusammenfassung: 3 Findings — Kritisch: 0, Hoch: 0, Mittel: 2, Niedrig: 1, Info: 0.

Geprüft: Models, Views/URLs, Formulare, Rollen-/Nachfolge-Services, Admin einschließlich Quotenformular, Migrationen und Templates. Rollenänderungen prüfen die Berechtigung nach dem Sperren erneut; die Datenbank verhindert mehrere akzeptierte Clans pro Benutzer. Das öffentliche Logoformular prüft Größe, Bildstruktur und Dimensionen. Kein eigener Serializer vorhanden. Die Sammelzahlungen und ihre Endpunkte sind im Seating-Review behandelt.

### [CLANS-01] Unbegrenzte Versuche gegen das Clan-Beitrittspasswort
- Schweregrad: Mittel
- Kategorie: Security
- Fundstelle: clans/views.py:225, clans/views.py:243, clans/views.py:246, clans/views.py:250; clans/forms.py:113
- Beschreibung: Der Passwort-Beitritt benötigt zwar eine angemeldete Sitzung und CSRF, hat aber weder Fehlversuchslimit noch Verzögerung oder Sperre. Jeder Benutzer ohne akzeptierte Mitgliedschaft kann beliebig viele Passwörter gegen einen Clan prüfen. Für Clan-Passwörter ist zudem keine Mindeststärke vorgesehen.
- Auswirkung / Angriffsszenario: Ein registrierter Benutzer probiert automatisiert ein Wörterbuch gegen einen fremden Clan. Ein Treffer gewährt sofort eine akzeptierte Mitgliedschaft, ohne Zustimmung eines Clan-Admins. Die Nutzer-Login-Limits schützen diesen separaten Endpunkt nicht. Das Passwort-Hashing erschwert einzelne Versuche, begrenzt ihre Anzahl aber nicht.
- Betroffener Code:
  ```python
  if form.is_valid():
      entered_password = form.cleaned_data.get('password')
      if clan.check_password(entered_password):
          # unmittelbar ACCEPTED-Mitgliedschaft anlegen
  ```
- Empfehlung: Atomare Fehlversuchslimits pro Clan und Benutzer/IP, zeitliche Sperren und angemessene Passwortstärke einführen; keinen unbegrenzten Hashvergleich zulassen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Der eigene Login-Passwortversuchszähler wird beim Clanbeitritt nicht aufgerufen. Die aktive URL akzeptiert beliebig wiederholte eigene POSTs eines angemeldeten Nichtmitglieds; das Formular enthält nur ein Passwortfeld ohne Stärke-/Versuchslimits. Django-`check_password` prüft einen sicheren Hash, setzt aber keine Fehlversuchssperre. Bei einem Treffer erzeugt die View direkt ACCEPTED ohne Clan-Adminfreigabe. Im Middleware-/Nginx-Pfad existiert kein globaler Request-Limiter.
- **Belege / Gegenmaßnahmen:** `config/urls.py:74`, `clans/urls.py:9`, `clans/views.py:225`, `:230`, `:243`, `:246`, `:250`, `clans/forms.py:113`, `clans/models.py:50`, `:56`, `templates/clans/clan_detail.html:209`, `:210`, `config/settings.py:96`, `:201`. Login/CSRF, bestehende Mitgliedschaft und DB-Eindeutigkeit (`clans/models.py:150`) beschränken den Pfad; sie verhindern kein Wörterbuch-Raten vor erfolgreichem Beitritt. `AUTH_PASSWORD_VALIDATORS` werden von diesem einfachen CharField nicht automatisch aufgerufen. Der separate Request-Join-Pfad (`clans/urls.py:10`) verlangt eine spätere Freigabe, die Passwort-URL umgeht ihn ausdrücklich.

### [CLANS-02] Bearbeitung speichert vor der Sperre geladene Clan-Daten zurück
- Schweregrad: Mittel
- Kategorie: Bug
- Fundstelle: clans/views.py:185, clans/views.py:197, clans/views.py:200; clans/services.py:47, clans/services.py:56; clans/forms.py:108
- Beschreibung: Das ModelForm arbeitet mit der vor der Transaktion geladenen Clan-Instanz. `locked_management` lädt unter Sperre eine frische Instanz, aber die View verwendet diese nicht. `clan.save()` schreibt anschließend alle Modellfelder der alten Instanz, einschließlich `seat_limit_override`, obwohl das öffentliche Formular dieses Feld gar nicht bearbeiten darf.
- Auswirkung / Angriffsszenario: Nach dem Laden/Validieren des Clanformulars ändert die Orga das Kontingent, bevor der Clan-Admin die Sperre erhält. Sein anschließender Save setzt die Quotenänderung auf den zuvor geladenen Wert zurück. Ebenso können parallele Bearbeitungen von Clan-Admins gegenseitig Änderungen überschreiben. Die Sperre verhindert hier gleichzeitige SQL-Schreibvorgänge, aber nicht den Verlust schon abgeschlossener Änderungen.
- Betroffener Code:
  ```python
  form = ClanForm(request.POST, request.FILES, instance=clan)
  if form.is_valid():
      with locked_management(clan.pk, request.user.pk):
          form.save()
  ```
- Empfehlung: Das Formular mit der frisch gesperrten Instanz erstellen/validieren oder ausschließlich explizit freigegebene Formularfelder auf diese Instanz übertragen. Optional eine Versionsprüfung für parallele redaktionelle Änderungen ergänzen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Der vollständige Clan wird vor Formularvalidierung und Transaktionsbeginn geladen. ModelForm befüllt diese alte Instanz nur mit Formularfeldern; `seat_limit_override` bleibt ihr alter Wert. `locked_management` lädt eine frische Instanz unter Zeilensperre, doch die View bindet den Yield nicht und speichert weiter `form.instance`. `ClanForm.save` und `Clan.save` geben keine `update_fields` an; Django speichert deshalb auch das alte Quotenfeld. Autorisierung nach der Sperre schützt die Rolle, nicht den verwendeten Datenstand. Eine inzwischen abgeschlossene Orga-Änderung kann somit überschrieben werden.
- **Belege / Gegenmaßnahmen:** `clans/urls.py:8`, `clans/views.py:185`, `:197`, `:200`, `:201`, `clans/forms.py:66`, `:101`, `:108`, `clans/services.py:33`, `:47`, `:48`, `:56`, `clans/models.py:10`, `:61`, `:79`; Django-Save-Feldauswahl `/tmp/breakpoint-review-20261007/lib/python3.14/site-packages/django/db/models/base.py:1056` (6.0.9). Der Admin-Quotenpfad nutzt Konfigurationslock und QuotaReleaseForm (`clans/admin.py:14`, `:16`, `:25`), aber keine Versionsprüfung oder Sicherung gegen späteren öffentlichen Stale-Save. CSRF, Logo-/URL-Validierung und Clan-Adminprüfung betreffen andere Eigenschaften.

### [CLANS-03] Bestimmte neue Clan-Passwörter bleiben bei Bearbeitung im Klartext
- Schweregrad: Niedrig
- Kategorie: Bug
- Fundstelle: clans/forms.py:101, clans/forms.py:105; clans/models.py:72, clans/models.py:78
- Beschreibung: Bei einem vorhandenen Clan hat ModelForm die Instanz bereits mit dem bereinigten neuen Passwort befüllt. Der Vergleich `password == self.instance.password` ist damit auch für ein neues Passwort wahr und überspringt `set_password`. Die nachgelagerte Präfix-Heuristik in `Clan.save` interpretiert jedes Passwort, das etwa mit `argon2` beginnt, als bereits gehasht.
- Auswirkung / Angriffsszenario: Beim Ändern auf `argon2Secret123` speichert die Anwendung diese Zeichenfolge unverändert; derselbe Wert funktioniert anschließend beim Beitritt nicht. Dies wurde isoliert mit dem echten Formular und Modell reproduziert: gültiges Formular, unveränderter Passwortwert, `check_password` ergibt False. Datenbank-Schreibmethoden wurden dabei gemockt. Das Verhalten betrifft die Bearbeitung; die Neuanlage ruft `set_password` auf.
- Betroffener Code:
  ```python
  if not (self.instance.pk and password == self.instance.password):
      clan.set_password(password)
  # Modell:
  if self.password and not self.password.startswith('argon2') ...:
      self.password = make_password(self.password)
  ```
- Empfehlung: Vorhandenen Hash separat vor der ModelForm-Instanzbefüllung merken und jede tatsächlich eingegebene neue Zeichenfolge ausdrücklich über `set_password` verarbeiten. Keine Klartext-/Hash-Erkennung allein anhand von Präfixen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Niedrig (unverändert).**
- **Begründung:** Djangos ModelForm `_post_clean` überträgt das bereinigte Passwort vor `save` in dieselbe Instanz. Beim vorhandenen Clan ist der Vergleich in ClanForm.save daher für jede neue nichtleere Eingabe wahr. Normale neue Passwörter werden anschließend noch von Clan.save gehasht; Hashalgorithmus-Präfixe überspringen auch diesen letzten Schritt. Der isolierte Originalform-Test mit vorhandenem pk, unverändertem slug und `argon2Secret123` war gültig, speicherte genau diesen Klartextwert und lieferte bei `check_password` False. Die Fundstelle ist somit kein allgemeiner Wegfall des Hashings aller Passwörter, sondern der beschriebene Präfixfall.
- **Belege / Gegenmaßnahmen:** `clans/views.py:197`, `clans/forms.py:92`, `:101`, `:105`, `clans/models.py:50`, `:59`, `:72`, `:78`, `templates/clans/clan_form.html:54`; Framework-Instanzbefüllung `/tmp/breakpoint-review-20261007/lib/python3.14/site-packages/django/forms/models.py:495` (6.0.9). Öffentliche Neuanlage ohne pk verwendet set_password; leere Bearbeitung bewahrt den bestehenden Wert (`clans/forms.py:94`). Beide schützen den nichtleeren Präfixfall bei Bearbeitung nicht. Präzisierung eines weiteren Eingangs desselben Bugs: Der normale Clan-Admin verwendet ClanQuotaForm statt ClanForm (`clans/admin.py:14`, `seating/clan_admin_forms.py:80`); auch dort kann die Model-Präfixheuristik bei direkter Rohpassworteingabe greifen.



## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| CLANS-01 | bestätigt | Vor dem Hashvergleich atomare Limits pro Benutzer (5), IP (25) und Clan (100) je 10 Minuten. Neue Formularpasswörter erfüllen die konfigurierten Django-Passwortvalidatoren; bestehende Passwörter bleiben benutzbar. Clanbeitritt prüft frischen Clan und Benutzer unter gemeinsamen Locks. |
| CLANS-02 | bestätigt | Clan-Edit bindet und validiert das Formular erneut mit der frisch gesperrten Claninstanz. Nicht freigegebene Orga-Felder werden nicht aus dem alten Snapshot zurückgeschrieben. |
| CLANS-03 | bestätigt | Formular merkt bisherigen Hash vor ModelForm-Instanzbefüllung und hasht jeden tatsächlich eingegebenen neuen Wert ausdrücklich. Admin nutzt dieselbe Passwortverarbeitung. Model-Fallback erkennt vollständig dekodierbare Hashes statt Algorithmuspräfixen. |

**Prüfungen:** Alle 58 Clantests inkl. PostgreSQL-Rollen-Concurrency bestanden. 5 neue Regressionstests prüfen Limits vor Hashvergleich, parallele Quotenänderung, Frontend-/Adminpasswörter, Blank-Edit und Präfixwerte.
