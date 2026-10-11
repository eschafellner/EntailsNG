Verifikationszusammenfassung (9. Oktober 2026): **4 BESTÄTIGT / 0 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Stufe 2: Öffentliche URL-Zuordnung, Staff-/Methodenschutz, CSRF, Admin-ModelForm, Zahlungsservice, Check-in-Sperren und Scanner-Rückmeldung geprüft. HEAD-Schreibpfad und beide JSON-Strukturfehler zusätzlich isoliert mit Originalfunktionen und gemockten Datenzugriffen nachvollzogen; keine realen Check-ins ausgeführt.

Zusammenfassung: 4 Findings — Kritisch: 0, Hoch: 0, Mittel: 3, Niedrig: 1, Info: 0.

Geprüft: Modelle, Services, Views/URLs, Admin/Formulare, QR-Erzeugung, Migrationen, Dashboard-, Gäste-, Scanner- und Admin-Templates sowie Scanner-JavaScript. Keine Serializer oder eigenen Signals vorhanden. Eigentümerprüfung der QR-Bilder, Staffschutz, CSRF, UUIDv4/Kurzcode, Buchungspreis und Event-/User-/Registrierungssperren berücksichtigt.

### [EVENTS-01] HEAD-Anfrage führt einen Check-in ohne CSRF-Prüfung aus
- Schweregrad: Mittel
- Kategorie: Security
- Fundstelle: events/views.py:330, :358, :378
- Beschreibung: `process_checkin` zeigt nur bei `request.method == 'GET'` die Vorschau. Alle anderen Methoden erreichen den schreibenden Pfad; eine Begrenzung auf POST fehlt. HEAD ist für Djangos CSRF-Middleware eine sichere Methode und benötigt keinen CSRF-Token.
- Auswirkung / Angriffsszenario: Ein angemeldeter Staff kann mit HEAD auf `/checkin/<id>/<token>/` eine bezahlte Anmeldung einchecken. Auch ein Link-Prüfer mit Staffsession kann so unbeabsichtigt Einlass markieren. Der Staffschutz und die Kenntnis des gültigen Tokens sind weiterhin erforderlich; ein beliebiger anonymer Angreifer kann dies nicht direkt ausführen. Cross-Site-Ausnutzung hängt zusätzlich von Cookie-/SameSite-Kontext ab.
- Betroffener Code:
  ```python
  if request.method == 'GET':
      return render(...)
  already_checked_in = registration.is_checked_in
  if not already_checked_in:
      registration.check_in(target_event=active_event)
  ```
- Empfehlung: GET und HEAD ausdrücklich ohne Mutation behandeln und den schreibenden Zweig ausschließlich für POST freigeben; alle übrigen Methoden mit 405 ablehnen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Die UUID-URL bindet die Funktion direkt; `staff_member_required` prüft Rolle/Aktivität, aber keine HTTP-Methode. Die Vorschau verzweigt ausschließlich für GET. HEAD erreicht deshalb die mutierende Modelmethode; auch OPTIONS/TRACE würden denselben Zweig erreichen. Die CSRF-Middleware akzeptiert diese sicheren Methoden ohne Token. Die Modelprüfung kontrolliert Zahlung/Event/Ban und sperrt Zeilen, kennt aber die Requestmethode nicht.
- **Belege / Gegenmaßnahmen:** `events/urls.py:23`, `events/views.py:330`, `:358`, `:378`, `:381`, `events/models.py:399`, `:448`, `config/settings.py:102`; Framework `/tmp/breakpoint-review-20261007/lib/python3.14/site-packages/django/middleware/csrf.py:425` (6.0.9). Der isolierte HEAD-Test wurde von dieser CSRF-Middleware akzeptiert und rief in der Originalview `check_in` auf. Die getrennte Scanner-API ist POST-begrenzt (`events/views.py:512`), schützt diese alternative URL jedoch nicht. Der Bestätigungsbutton mit CSRF in `events/templates/events/checkin_confirm.html` beschränkt nur den normalen Browserablauf. Gültiges Ticket und aktive Staffsession bleiben erforderlich.

### [EVENTS-02] Admin-Formular umgeht Kontingentprüfung beim Reaktivieren stornierter Tickets
- Schweregrad: Mittel
- Kategorie: Bug
- Fundstelle: events/admin.py:399, :420, :425; events/services.py:309
- Beschreibung: Das Adminformular speichert den neuen `PAID`-Status bereits mit `super().save_model`, bevor `PaymentService.mark_paid` ausgeführt wird. Der Service prüft Kapazität nur, wenn der aus der DB geladene Status noch `CANCELLED` ist. Bei bestehenden Anmeldungen greift auch `EventRegistration.clean` keine Kapazitätsprüfung.
- Auswirkung / Angriffsszenario: Event füllen, eine weitere stornierte Anmeldung öffnen und deren Status im normalen Adminformular auf „Bezahlt“ setzen: Sie wird trotz vollem Kontingent reaktiviert. Die Bulk-Aktion funktioniert anders, da sie den alten Status bis zur Serviceprüfung erhält. Das Finding ist ein unbeabsichtigter Admin-Bug, kein öffentlicher Buchungsangriff.
- Betroffener Code:
  ```python
  super().save_model(request, obj, form, change)
  if became_paid:
      obj.mark_as_paid(amount=obj.paid_amount or None, send_email=True)
  # Service:
  if reg.payment_status == EventRegistration.PaymentStatus.CANCELLED:
      if event.is_full and not allow_overbooking and not funding:
          raise EventFullError(...)
  ```
- Empfehlung: Zahlungsübergang auf Basis des gesperrten bisherigen DB-Zustands ausführen, bevor der Formularstatus persistiert wird; bei Ablehnung den gesamten Formularvorgang zurückrollen. Auch neue Adminbuchungen unter Event-Sperre validieren.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Der registrierte Admin nutzt die gewöhnliche ModelForm-Validierung. `EventRegistration.clean()` prüft Kapazität nur bei Neuanlagen. Bei bestehenden, nicht clanfinanzierten Tickets ist der Zahlungsstatus editierbar und wird vor dem Zahlungsservice gespeichert. Dieser lädt anschließend bereits PAID unter Sperre und überspringt die ausschließlich an CANCELLED gebundene Kapazitätsprüfung. Die Transaktionen serialisieren den falschen Ablauf und rollen ohne Ausnahme nichts zurück; die nachträgliche Überbuchungswarnung erzwingt keine Kapazität.
- **Belege / Gegenmaßnahmen:** `config/urls.py:18`, `events/admin.py:277`, `:279`, `:390`, `:399`, `:421`, `:425`, `:575`, `events/models.py:537`, `:548`, `:558`, `events/services.py:300`, `:301`, `:310`. Finanzierte Clan-Anmeldungen sind im Formular readonly (`events/admin.py:282`) und zusätzlich im Service geschützt (`events/services.py:304`); normale stornierte Tickets sind weiter betroffen. Die Bulk-Bezahlaktion (`events/admin.py:439`) persistiert den Status nicht vorab und widerlegt diesen separaten Formularpfad nicht.

### [EVENTS-03] Gleichzeitige Scans melden dasselbe Ticket mehrfach als neuen erfolgreichen Einlass
- Schweregrad: Mittel
- Kategorie: Bug
- Fundstelle: events/views.py:625, :628, :638; events/views.py:378; events/models.py:458, :463, :469
- Beschreibung: Die Views lesen `already_checked_in` vor der Zeilensperre. `check_in` lädt zwar den aktuellen Zustand unter Sperre und verhindert eine doppelte DB-Mutation, liefert aber stets `True`, ohne mitzuteilen, ob dieser Aufruf tatsächlich den ersten Check-in vorgenommen hat. Die View baut die Erfolgsmeldung anschließend aus ihrem alten Zustand.
- Auswirkung / Angriffsszenario: Zwei Helfer scannen denselben kopierten Code gleichzeitig. Beide Views lesen zunächst `False`; der zweite Aufruf wartet auf die Sperre und schreibt nichts mehr, antwortet aber ebenfalls mit `status: success` und `already_checked_in: false`. Der Scanner zeigt beiden einen neuen erfolgreichen Einlass. Es entsteht kein zweiter DB-Datensatz; betroffen ist die für die Einlassentscheidung entscheidende Rückmeldung.
- Betroffener Code:
  ```python
  already_checked_in = registration.is_checked_in
  if not already_checked_in:
      registration.check_in(target_event=active_event)
  return JsonResponse({
      'status': 'already_checked_in' if already_checked_in else 'success',
  })
  ```
- Empfehlung: Unter der Registrierungszeilensperre ein Ergebnis `checked_in_now`/`already_checked_in` bestimmen und dieses unverändert bis zur Scannerantwort weiterreichen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Beide erreichbar gemappten Views bilden ihre Antwort aus einem vor `check_in` gelesenen Bool. Unter Sperre verhindert das Model eine zweite Mutation, meldet jedoch stets True zurück und synchronisiert die aufrufende Instanz nur im Erstschreibzweig. Zwei vorher geladene False-Instanzen können daher beide den Erstcheck-in melden. Weder Service noch Template/Scanner korrigieren die Antwort danach. Dies ist ein Rückmeldungs-/Einlassfehler, kein doppelter Datensatz, wie bereits im Original eingegrenzt.
- **Belege / Gegenmaßnahmen:** `events/urls.py:19`, `:23`, `events/views.py:378`, `:401`, `:625`, `:628`, `:638`, `:649`, `events/models.py:456`, `:458`, `:463`, `:469`, `static/js/checkin-scanner.js:130`, `:135`, `events/templates/events/checkin_success.html`. Staff, POST/CSRF für Scans, gültiger Code, Ban-/Zahlungsprüfungen und die Datenbanksperre begrenzen den Zugriff und sichern den persistenten Zustand; keiner dieser Mechanismen liefert der View den tatsächlich gewonnenen Erstcheck-in zurück.

### [EVENTS-04] Gültiges JSON mit falscher Struktur erzeugt Scanner-500er
- Schweregrad: Niedrig
- Kategorie: Bug
- Fundstelle: events/views.py:270, :276, :547, :548
- Beschreibung: Die APIs nehmen an, dass `json.loads` ein Objekt zurückgibt. `[]`, `null`, Zahlen oder Strings sind gültiges JSON, haben aber keine `.get`-Methode. Beim Toggle liegt der Zugriff außerdem außerhalb des Parse-try-Blocks; ungültige Registrierungs-ID-Typen können ebenfalls ungefangen an den ORM gelangen.
- Auswirkung / Angriffsszenario: Ein Staff-Client sendet beispielsweise `[]` an `/api/check-in/scan/` und erhält einen 500er statt einer kontrollierten 400-Antwort. Der Fehler wird zusätzlich persistent protokolliert. Der Staffschutz begrenzt das Szenario.
- Betroffener Code:
  ```python
  data = json.loads(request.body)
  code_str = str(data.get('code', '')).strip()
  ```
- Empfehlung: JSON-Objekt und Feldtypen vor Zugriff/ORM-Abfrage validieren; ungültige Strukturen und IDs mit 400 beantworten.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Niedrig (unverändert).**
- **Begründung:** Beide URLs sind aktive Staff-POST-Endpunkte. `json.loads` akzeptiert Nichtobjekte; beim Toggle liegt `.get()` außerhalb des Parse-Handlers, beim Scan wird ausschließlich JSONDecodeError gefangen. Ein Array löste in beiden isoliert ausgeführten Originalfunktionen AttributeError aus, bevor eine ORM-Abfrage stattfand. Ohne Formular/Serializer für den Body kann die Framework-JSON-Verarbeitung dies nicht in einen Feldfehler übersetzen. Ungültige ID-Werte im Toggle haben ebenfalls keinen passenden Fehlerhandler.
- **Belege / Gegenmaßnahmen:** `events/urls.py:18`, `:19`, `events/views.py:265`, `:270`, `:276`, `:512`, `:547`, `:549`, `configuration/middleware.py:55`, `:72`. Der Scanner hat zusätzlich 60 Anfragen/Minute je Nutzer (`events/views.py:521`), der Toggle nicht. Staff, require_POST und CSRF verhindern anonyme/ungültige Methoden; innerhalb dieser Grenze bleibt die 500-Antwort bestehen. Die Fehlerprotokollierung ist best effort, kein garantierter dauerhafter Log bei DB-Ausfall.



## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| EVENTS-01 | bestätigt | Token-Check-in akzeptiert nur GET/HEAD/POST; GET und HEAD zeigen ausschließlich Vorschau, andere Methoden liefern 405. |
| EVENTS-02 | bestätigt | Adminformular validiert Neuanlagen und Reaktivierungen unter User-/Event-/Registrierungssperren. Bisheriger Zahlungsstatus bleibt bis zum PaymentService erhalten; Ablehnung rollt den Formularvorgang zurück. |
| EVENTS-03 | bestätigt | check_in liefert unter Zeilensperre checked_in_now und synchronisiert auch veraltete Instanzen. Scanner und Token-View bauen ihre Antwort unmittelbar aus diesem Ergebnis. |
| EVENTS-04 | bestätigt | Beide Scanner-APIs validieren JSON-Objekt und Feldtypen; Toggle verlangt positive begrenzte Integer-ID, Scan begrenzten String. Ungültige Strukturen liefern 400 vor ORM-Zugriff. |

**Prüfungen:** 105 Eventtests erfolgreich, darunter 5 neue Regressionstests inkl. Admin-Reaktivierung bei vollem/freiem Event und deterministisch simuliertem konkurrierendem Check-in; Scanner-JavaScript-Test erfolgreich.

Abschließende Grenzfallprüfung: Auch der JSON-Parserfehler für eine 5000-stellige Zahl und ungültiges UTF-8 wird in beiden APIs als 400 behandelt. Vier direkte View-Prüfungen ohne Datenbankzugriff erfolgreich; die Regressionstests enthalten diese Payloads.

Die abschließende gezielte Suite mit 13 Event-/Turniertests einschließlich dieser erweiterten JSON-Regression und der responsiven Codeansicht bestanden.
