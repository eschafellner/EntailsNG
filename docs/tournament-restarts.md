# Turnier-Neustarts im Backend

> Seit 5. Oktober 2026 verwendet das Projekt ausschließlich PostgreSQL, auch lokal und für Tests. Testbefehle benötigen eine konfigurierte PostgreSQL-Verbindung; erwähnte SQLite-Ergebnisse sind historische Prüfstände vor der Umstellung. Die vollständige PostgreSQL-Suite einschließlich Parallelität und Backups läuft gemeinsam in CI.

Stand: 2. Oktober 2026. Im Django-Admin kann für jedes vorhandene Turnier eine
unabhängige neue Ausgabe vorbereitet werden. Dies funktioniert für Entwürfe,
offene, laufende, abgeschlossene und abgesagte Turniere in allen sechs Modi.

## Bedienung

1. **Backend → Turniere → gewünschtes Turnier** öffnen. Oben bei den
   Objektaktionen **Neustart vorbereiten** auswählen.
2. Die Übersicht zeigt Original, Veranstaltung, Spiel, Modus und maximale
   Teilnehmerzahl. Titel, Anmeldebeginn, Anmeldeschluss und optionalen
   Turnierstart für die neue Ausgabe festlegen. Die Termine sind zunächst vom
   Original übernommen; bei älteren Turnieren entsprechend aktualisieren.
3. Teams auswählen. Standardmäßig sind alle noch vorhandenen Anmeldungen
   ausgewählt, einschließlich zurückgezogener Teams. Zurückgezogene und
   archivierte Teams sind gekennzeichnet. Setzpositionen können übernommen oder
   für eine neue Auslosung verworfen werden. Eine leere Auswahl ist als Vorlage
   mit anschließend manuell ergänzbaren Anmeldungen erlaubt.
4. Einen Anlass angeben. Bei einem offenen oder laufenden Original optional
   **Offenes oder laufendes Original absagen** aktivieren. Ohne diese Auswahl
   läuft das Original unverändert weiter. Bei beendetem oder bereits abgesagtem
   Original ist diese Option gesperrt.
5. **Neue Ausgabe als Entwurf erstellen** wählen. Das Backend öffnet anschließend
   die neue Ausgabe. Dort können Regeln, Verantwortliche und Teilnehmer vor der
   Veröffentlichung weiter überarbeitet werden. Anmeldung und Turnierstart
   erfolgen anschließend über die vorhandenen Funktionen.

Die neue Ausgabe erhält eine eigene ID und URL. Gäste sehen ihren Entwurf auch
über einen direkten Link nicht. Links auf neue Ausgaben im Frontend werden nach
derselben Sichtbarkeitsregel gefiltert; beim Original werden sichtbare neue
Ausgaben verlinkt. Neue Ausgaben zeigen im Frontend keinen Originalverweis;
die Herkunft bleibt im Backend erhalten. Im Backend sind neue Ausgaben bereits während
der Vorbereitung beim Original aufgeführt.

## Übernahme und Historie

Übernommen werden Spiel, Veranstaltung, Beschreibung, Modus, maximale
Teilnehmerzahl, Teamgrößenregel, Schweizer Regeln, kleines Finale, Gruppenqualifikanten,
Gleichstandsregel, Turnieradmin und Support sowie die gewählten Anmeldungen.
Die vorhandenen Team-Datensätze werden weiterverwendet. Damit ändern sich deren
Identität und bisherige Turnierhistorie nicht.

Matchdaten, Ergebnisse, Platzierungen, Gruppenzuordnungen, Schweizer Runden und
deren Zufallsstartwert werden nicht übernommen. Neue Anmeldungen beginnen mit
null Punkten und ohne Aufgabe-/Rückzugsstatus. Setzpositionen werden nur bei
aktivierter Übernahme kopiert. Auch bereits ausgespielte Schweizer Turniere
können so mit unveränderten historischen Runden neu aufgesetzt werden.

Die Kopie hält schreibgeschützt Originalreferenz, Originaltitel zum Zeitpunkt
der Erstellung, ausführenden Mitarbeiter, Anlass, gewählte Teams/Seeds und die
optionale Absage fest. `created_at` dokumentiert den Zeitpunkt. Wird das Original
später gelöscht, bleiben Originaltitel und Übernahmeprotokoll an der Kopie
erhalten. Der Löschvorgang entfernt die Kopie nicht.

Die Funktion dient einer neuen Austragung beziehungsweise einer Überarbeitung
der neuen Ausgabe. Einzelne alte Ergebnisse werden dabei nicht rückwirkend
korrigiert; Endstand und Urkunden des Originals bleiben nachvollziehbar.

## Rechte und Konsistenz

- Erforderlich sind ein aktiver Mitarbeiter-/Superadmin-Account und die
  Django-Rechte `add_tournament`, `change_tournament` sowie
  `add_tournamentregistration`. Der Button erscheint nur mit diesen Rechten.
- Die Vorschau schreibt keine Turniere, Anmeldungen oder Ergebnisse. Änderungen
  am Original, dessen Anmeldungen oder den angezeigten Teamdaten erfordern eine
  neue Vorschau. Das signierte Token gilt 30 Minuten und ist an Original und
  ausführenden Account gebunden.
- Ein mehrfach abgeschicktes Formular erzeugt genau eine Ausgabe und führt
  erneut zu dieser Ausgabe. Eine frisch aufgerufene Vorschau erlaubt eine
  weitere, eigenständige Ausgabe.
- Kopie, neue Anmeldungen und optionale Absage werden gemeinsam in einer
  Transaktion gespeichert. Ein Fehler hinterlässt weder eine Teilkopie noch
  eine versehentliche Absage. Die Sperrreihenfolge ist
  **Event → Originalturnier → Anmeldungen → Teams**.
- Archivierte Teams werden nicht automatisch reaktiviert. Vor dem Start greift
  die vorhandene Prüfung von Spiel, Veranstaltung, Archivstatus, Kader gemäß
  der übernommenen [Teamgrößenregel](tournament-roster-rules.md) und aktiven Accounts. Teams mit Problemen müssen zuvor geklärt oder aus
  der Kopie entfernt werden.
- Bei einem beendeten/abgesagten Event kann eine interne Kopie vorbereitet
  werden. Veröffentlichung und Start bleiben durch die bestehenden Event-Sperren
  blockiert. Eine Übertragung in ein anderes Event mit automatischer
  Team-Reaktivierung ist nicht Teil dieser Funktion.

## Installation und Prüfung

```sh
python manage.py migrate
python manage.py seed_translations
```

Anschließend die Web-Prozesse neu starten. Migration:
`tournaments.0011_tournament_restart`. Die Umsetzung hat die App-Datenbank
nicht migriert und kein Deployment ausgeführt.

```powershell
$env:DEBUG = 'True'
$env:SECRET_KEY = 'local-restart-test'
.\.venv\Scripts\python.exe manage.py test tournaments.test_restart --noinput
.\.venv\Scripts\python.exe manage.py test tournaments --noinput
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations tournaments --check --dry-run
```

Die neue Testsuite enthält **21 Tests: 19 erfolgreich, zwei PostgreSQL-Fälle
auf SQLite übersprungen**. Sie prüft unter anderem abgeschlossene Originale
aller sechs Modi und deren vollständige erneute Austragung, Team- und Regelübernahme, frische Endstände, optionale Absage,
Rollback, Doppelklicks, manipulierte/veraltete Vorschauen, Rechte, CSRF, das
Backend-Formular, Draft-Sichtbarkeit, archivierte Teams und beendete Events.
Die beiden zusätzlichen PostgreSQL-Tests prüfen echte gleichzeitige
Veröffentlichungen und einen Rückzug während einer wartenden Kopiererstellung.
Sie sind in den PostgreSQL-CI-Job aufgenommen. Lokal ist PostgreSQL nicht
verfügbar; dieser CI-Job wurde hier nicht gestartet. Frontend-/Backend-Prüfungen
verwenden Django-Testclient und gerenderte Templates, keinen manuellen
Browserlauf.

Die vollständige Turniersuite wurde ebenfalls geprüft: **269 Tests entdeckt,
255 erfolgreich, 14 PostgreSQL-Fälle auf SQLite übersprungen**, keine Fehler.
`manage.py check` und der Migrationsabgleich für `tournaments` sind erfolgreich.
