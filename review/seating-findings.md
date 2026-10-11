Verifikationszusammenfassung (9. Oktober 2026): **2 BESTÄTIGT / 0 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Stufe 2: Editor-/Reservierungs-URLs, JSON-Verarbeitung, globale CSRF-/Login-/Staff-Grenzen, Rasterservice, finanzierte Clan-Holds und Mitgliedszuweisung geprüft.

Zusammenfassung: 2 Findings — Kritisch: 0, Hoch: 0, Mittel: 1, Niedrig: 1, Info: 0.

Geprüft: Sitzplan-/Zell-/Clan-Zahlungsmodelle, alle Views/URLs, Rasterservice, Clan-Hold-/Zahlungsservices, Admin/Formulare, Signals, Worker/Bereinigung, Migrationen sowie Sitzplan-/Editor-/Clan-Zahlungs-/Admin-Templates und Sitzplan-JavaScript. Keine Serializer. Eigentümer-/Clan-/Staff-/Modellpermissions, CSRF, Signaturen, Quoten, atomare Zahlungssnapshots und Unique Constraints berücksichtigt.

### [SEATING-01] Raster-Speichern scheitert nach Zuweisung eines bezahlten Clanplatzes
- Schweregrad: Mittel
- Kategorie: Bug
- Fundstelle: seating/services.py:165, :252, :264; seating/clan_payments.py:316
- Beschreibung: `save_grid` normalisiert jeden eingehenden Reservierungsstatus außer `BLOCKED` auf `FREE`. Für finanzierte Clanplätze vergleicht es diesen normalisierten Status anschließend direkt mit dem bestehenden Zellstatus. Ein einem Mitglied zugewiesener bezahlter Clanplatz hat `RESERVED` und scheitert deshalb auch ohne jede Änderung an diesem Platz. Die spätere Logik, die bei belegten Plätzen den alten Status erhält, wird nicht mehr erreicht.
- Auswirkung / Angriffsszenario: Sammelzahlung bestätigen, einen Clanplatz einem Mitglied zuweisen, im Editor eine andere freie Kachel ändern und das komplette Raster speichern. Der Server lehnt die Änderung mit dem Hinweis auf die Sammelzahlung ab. Selbst unverändertes erneutes Speichern des vollständigen Plans scheitert.
- Betroffener Code:
  ```python
  reservation_status = (SeatingCell.ReservationStatus.BLOCKED
      if raw_res_status == SeatingCell.ReservationStatus.BLOCKED
      else SeatingCell.ReservationStatus.FREE)
  ...
  if cell.pk in funded_ids and (
      seat_label != cell.seat_label or res_status != cell.reservation_status):
      raise SeatingPlanValidationError(...)
  ```
- Empfehlung: Den tatsächlich anzuwendenden Status vor der Schutzprüfung bestimmen. Bei belegten Zellen den vorhandenen Status beibehalten; echte Änderungen an finanzierten Plätzen weiterhin ablehnen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Der Editor lädt und übermittelt Reservierungszustände des vollständigen Rasters. Der gemappte Save-POST ruft `save_grid` auf; RESERVED wird schon beim Normalisieren zu FREE. Bezahlte geschützte Holds bleiben in `committed_holds`, auch nach Mitgliedszuweisung, die die Zelle auf RESERVED setzt. Der Vergleich für finanzierte Plätze findet vor der späteren Beibehaltung des Zustands belegter Plätze statt und lehnt somit unveränderte finanzierte RESERVED-Zellen ab. Formulare der Zuweisung oder Versionsprüfung des Editors normalisieren diese Situation nicht weg.
- **Belege / Gegenmaßnahmen:** `seating/urls.py:8`, `:17`, `seating/views.py:38`, `:57`, `:61`, `:80`, `seating/templates/seating/editor.html:69`, `:312`, `seating/services.py:165`, `:194`, `:199`, `:252`, `:264`, `seating/clan_payments.py:40`, `:316`, `seating/clan_payment_views.py:84`, `:101`. Staff/Modellpermission/CSRF und Transaktionen verhindern unberechtigte bzw. teilweise Rasteränderungen. Sie verhindern hier gerade auch das zulässige Speichern und entkräften den Bug nicht. Das `SeatingPlanValidationError` wird kontrolliert mit 400 ausgegeben (`seating/views.py:88`), kein 500.

### [SEATING-02] Falsche JSON-Struktur führt im Reservierungsendpunkt zu ungefangenem Fehler
- Schweregrad: Niedrig
- Kategorie: Bug
- Fundstelle: seating/views.py:226, :228, :230, :534
- Beschreibung: `reserve_seat_api` und `admin_toggle_block_seat` rufen `.get` auf dem JSON-Wert auf, ohne einen Objekt-Typ zu prüfen. Der jeweilige except-Block erfasst `AttributeError` nicht. Andere Sitzplanendpunkte haben bereits eine passende Typprüfung.
- Auswirkung / Angriffsszenario: Ein normaler angemeldeter Benutzer sendet `[]` oder `null` an den Reservierungsendpunkt und erhält einen 500er statt 400. Wiederholte solche Requests erzeugen außerdem persistente Systemfehlerprotokolle. CSRF und Login bleiben erforderlich; die äußere Transaktion rollt zurück.
- Betroffener Code:
  ```python
  data = json.loads(request.body)
  x = int(data.get('x'))
  except (json.JSONDecodeError, ValueError, TypeError):
      ...
  ```
- Empfehlung: Vor dem Zugriff `isinstance(data, dict)` und passende Feldtypen prüfen; falsche Strukturen einheitlich mit 400 beantworten.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Niedrig (unverändert).**
- **Begründung:** Beide Endpunkte sind direkt gemappt. Die Body-Verarbeitung besitzt keinen ModelForm-/Serializer-Typschutz: Arrays/null passieren `json.loads`, `.get` wirft AttributeError, der in den dortigen except-Tupeln fehlt. Beim Block-Endpunkt ist der spätere breite Exception-Handler erst nach dem ungeschützten Parse-Abschnitt aktiv. Der vorgelagerte `seating_write`-Decorator führt eine Transaktion mit Konfigurationssperre aus, fängt den Fehler aber nicht als 400 ab.
- **Belege / Gegenmaßnahmen:** `config/urls.py:73`, `seating/urls.py:19`, `:24`, `seating/views.py:216`, `:227`, `:230`, `:521`, `:530`, `:534`, `:538`, `:584`, `seating/clan_services.py:38`, `configuration/middleware.py:55`. `reserve_seat_api` benötigt Login, POST und CSRF; die normale Event-Anmeldung wird erst nach dem fehlerhaften JSON-Zugriff geprüft (`seating/views.py:238`), daher reicht ein aktives Konto auch ohne Ticket für den Strukturfehler. Der Admin-Blockpfad verlangt zusätzlich aktiven Staff und `seating.change_seatingcell`. Die korrekte Objektprüfung in `save_seating_plan` (`seating/views.py:68`) und Clan-Update (`:703`) schützt ausschließlich diese anderen URLs.


## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| SEATING-01 | bestätigt | Effektiven Zellstatus vor finanziertem Schutzvergleich bestimmen. Belegte Plätze behalten ihren Reservierungsstatus; Umbenennung, Sperre und destruktive Typänderung bleiben abgelehnt. |
| SEATING-02 | bestätigt | Reserve-/Block-Endpunkte prüfen Objektstruktur und begrenzte positive Integer-Felder. Bool, Float, Container und Unicode-Sonderziffern liefern 400; bestehende ASCII-Ziffernstrings bleiben kompatibel. |

**Prüfungen:** 167 bestehende Sitzplan-/Clan-/PostgreSQL-Concurrencytests bestanden; beide neuen Regressionstests nach Korrektur eines URL-ID-Testfalls bestanden. Clan-Hold-JavaScript-Test bestanden.
