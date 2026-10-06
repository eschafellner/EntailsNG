# Prüfung des Turniermoduls – 1. Oktober 2026

> Seit 5. Oktober 2026 verwendet das Projekt ausschließlich PostgreSQL, auch lokal und für Tests. Testbefehle benötigen eine konfigurierte PostgreSQL-Verbindung; erwähnte SQLite-Ergebnisse sind historische Prüfstände vor der Umstellung. Die vollständige PostgreSQL-Suite einschließlich Parallelität und Backups läuft gemeinsam in CI.

Geprüft wurden Anmeldung, Teamverwaltung, alle sechs Formate, Ergebnisdienste,
Aufgaben, Berechtigungen, Adminformulare, Frontend und Urkundendaten. Die unten
aufgeführten Fehler sind korrigiert und durch Regressionstests abgesichert.

## Gefundene Fehler und Korrekturen

| Bereich | Fehler | Korrektur |
|---|---|---|
| KO-System | Zwei Freilose konnten ein Folge-Match bei 5, 9, 10 oder 11 Teams dauerhaft auf PENDING halten. | Die zweite Runde wird nach dem Schreiben sämtlicher Erst­runden-Slots vollständig auf Spielbereitschaft geprüft. |
| Status | Ältere Formate ließen Starts, Ergebnisse oder Resets bei abgesagten Turnieren beziehungsweise beendeten Veranstaltungen zu. | Zentrale Statusprüfung unter Event- und Turniersperre; Rückzüge verändern keine abgesagten oder abgeschlossenen Turniere. |
| Generierung | Der öffentliche Kompatibilitätshelfer konnte vorhandene Matches überschreiben. | Delegation an den abgesicherten Dienst; bestehende Ergebnisse bleiben erhalten. Das übergebene Modell wird weiterhin aktualisiert. |
| Orga-Start | Seit der Anmeldung veränderte Kader wurden nicht erneut geprüft. | Prüfung von Spiel, Veranstaltung, Archivstatus, exakter Teamgröße, akzeptierter Kapitänsmitgliedschaft, aktiven Accounts und mehrfach eingesetzten Gästen beim Start durch die Orga, einschließlich Schweizer Vorschau und Freigabe. |
| Ergebnisse | Fehlerhafte Sieger-IDs konnten Serverfehler auslösen; Dezimalwerte wurden abgeschnitten, fehlende Werte als 0 behandelt und Datenbankgrenzen nicht eingehalten. | Strenge Prüfung vollständiger ganzzahliger Ergebnisse, IDs, Wertebereiche und Textlängen. Beide bisherigen POST-Namensvarianten bleiben unterstützt. |
| Fairplay | Teilnehmer konnten einen dem Sieger widersprechenden Punktestand speichern und dadurch die Tabellenwertung beeinflussen. | Solche Abweichungen kann nur die Orga mit Begründung werten. Teilnehmer können weiterhin eigene Niederlagen und erlaubte Remis bestätigen. |
| FFA-Korrekturen | Teilkorrekturen, doppelte oder fremde Teilnehmer und ungültige Ränge konnten alte Ergebnisse überschreiben oder mehrere Sieger hinterlassen. | Alle Teilnehmer werden gemeinsam validiert und atomar gespeichert. Bei Fehlern bleiben sämtliche bisherigen Ergebnisse unverändert. |
| FFA-Aufgabe | Das Ergebnisformular konnte eine durch Rückzug gesetzte Disqualifikation wieder löschen. | Aufgegebene Teilnehmer bleiben disqualifiziert. Der Dialog zeigt Disqualifikation und Notizen ausdrücklich an. |
| FFA-Plätze | Bei geteilten Plätzen konnte das Podium willkürlich ein Team auswählen; Urkunden enthielten nur die ersten drei Plätze. | Alle eingetragenen FFA-Plätze einschließlich Gleichständen stehen für Urkunden zur Verfügung. Das bisherige Podiumsformat erfindet bei Gleichständen keinen einzelnen Zweiten oder Dritten. |
| FFA-Oberfläche | Nach Abschluss war eine vom Dienst unterstützte Orga-Korrektur über den sichtbaren Button nicht mehr erreichbar. | Die vollständige Korrektur bleibt bei laufender Veranstaltung zugänglich; abgesagte Turniere und geschlossene Veranstaltungen sind gesperrt. |
| Solo-Anmeldung | Frühere Solo-Teams wurden ohne Prüfung ihrer aktuellen Zuordnung übernommen; ein vorhandenes aktuelles 1v1-Team konnte um ein zweites Team ergänzt werden. | Ein vorhandenes aktives Einzelspieler-Team hat Vorrang. Archivierte Solo-Teams werden nach Prüfung von Account, Spiel, Kader und alten Turnieranmeldungen automatisch reaktiviert; ihre Historie bleibt bestehen. Details: [Solo-Reaktivierung](solo-team-reactivation.md). |
| Datenlängen | Lange Benutzernamen konnten Solo-Teamnamen über 32 Zeichen erzeugen; wiederholte lange Turniertitel konnten das Slug-Limit überschreiten. | Automatisch erzeugte Namen und eindeutige Slugs berücksichtigen die Modellgrenzen. |
| Check-in | Stornierte Tickets mit altem Check-in-Flag konnten noch eine Turnieranmeldung erlauben. | Stornierte Event-Anmeldungen gelten nicht als gültiger Check-in. Die bestehende Orga-Ausnahme bleibt erhalten. |
| Teambeitritt | Archivierte Teams und Teams fremder Veranstaltungen konnten über Codes, Bewerbungen und deren Annahme Mitglieder erhalten. | Gemeinsame Statusprüfung aller Beitrittswege; gelöschte beziehungsweise inaktive Bewerber können nicht aufgenommen werden. |
| Teamreaktivierung | Beim Wechsel auf ein kleineres Spiel konnte ein überfüllter Kader übernommen werden. | Vor der Reaktivierung wird die Anzahl der tatsächlich behaltenen Mitglieder geprüft. |
| Ausstehende Bewerbung | Der Austritt eines noch nicht akzeptierten Bewerbers konnte das Team zum Aufgeben bringen. | Nur der Austritt eines akzeptierten Mitglieds verändert die erforderliche Kadergröße. |
| Gruppenphase | Bereits aufgegebene Gruppenführer konnten für die Finalphase qualifiziert werden. | Historische Tabellen bleiben erhalten; qualifiziert werden nur aktive Teams. Leere Qualifikationsplätze werden als Freilose abgewickelt. |
| Gruppenvorschau | Die geplante KO-Phase fehlte wegen unterschiedlicher Daten- und Template-Schlüssel. | Vorschau und Template verwenden kompatible Schlüssel. |
| Admin | Direkte Änderungen konnten Ergebnisdienste umgehen, Kader oder Teilnehmer gestarteter Turniere verändern und Validierungsfehler als Serverfehler ausgeben. | Struktur und aktive Kader sind geschützt; Admin-Ergebnisse werden vom Ergebnisdienst im Formular geprüft. FFA-Ergebnisse werden über die verlinkte Turnieransicht bearbeitet. |
| Schweizer Status | Ein gestartetes Schweizer Turnier konnte per Statusänderung wieder eine offene Anmeldung erhalten. | Nur die reguläre Reset-Aktion kann vor gewerteten Spielen die Anmeldung wieder öffnen. |
| Frontend | Die mobile Standard-Matchliste versteckte zunächst die Schweizer Rangliste; mehrere Überschriften teilten dieselbe Dialog-ID. | Schweizer Turniere starten mit der Übersicht; eine bewusst gewählte Matchliste wird weiter gespeichert. Überschriften haben eindeutige IDs. Gesperrte Ergebnisse zeigen keine Eingabebuttons. |
| Urkunden/Medien | Die Validierung bestehender Bilddateien ließ Dateien geöffnet und verursachte unter Windows Dateisperren. | Die Bild- und Schriftvalidierung stellt den vorherigen Dateizustand wieder her. |

## Sperren und Dienstvertrag

Ergebnisänderungen, Generierung und Resets sperren zuerst Event, dann Turnier und
anschließend die betroffenen Matches beziehungsweise Teams. Dadurch sehen auch
zwei gleichzeitig eingetragene letzte Liga-Ergebnisse einen konsistenten Zustand
und schließen das Turnier zuverlässig ab.

Frontend-Kaderänderungen sperren Benutzer nach ID, Events nach ID und danach das
Team. Das stimmt mit Anmeldung und Account-Löschung überein. Kapazität, die Regel
„ein aktives Team pro Spiel“ und Veranstaltungsstatus werden nach den Sperren
geprüft.

Der bestehende Dienstvertrag für vertrauenswürdige interne Aufrufe ohne `actor`
bleibt erhalten. Diese umgehen die Orga-Kaderprüfung für Imports/technische
Fixtures. Sämtliche HTTP-Starts und Schweizer Freigaben übergeben den angemeldeten
Benutzer. Neue Anwendungsaufrufe sollen ebenfalls einen `actor` übergeben.

## Verifikation der ursprünglichen Prüfung

- **334 Django-Tests** für `tournaments`, `users.test_account_deletion`, `events`
  und `media_designer`: **319 bestanden, 15 übersprungen**, keine Fehler.
- Darin **186 Turniertests**: 176 bestanden, 10 PostgreSQL-Fälle übersprungen.
- **37 neue Audit-Regressionstests** und **5 neue PostgreSQL-Paralleltests**.
- Vollständige KO-, Double-Elimination-, Liga- und Gruppenverläufe von 2 bis 16
  Teams (Gruppenphase ab 4), insgesamt 73 vollständige Varianten einschließlich
  Grand-Final-Reset; zusätzlich Aufgaben mit 4, 5 und 8 Teams je Format.
- Bestehende Schweizer Tests für Paarungen, Feinwertung, Freilose, Rückzüge,
  Vorschau-Tokens, Ergebniskorrekturen und Urkunden bestehen weiterhin.
- **12 JavaScript-Tests bestanden**, davon 5 neue Fälle zu mobiler Übersicht,
  gespeicherter Ansicht und ausgefallenem beziehungsweise beschädigtem Speicher.
- Browserprüfung auf isolierter SQLite-Testdatenbank: alle sechs Ansichten,
  eindeutige IDs, Schweizer Ergebnisdialog mit abgelehntem Remis und gespeichertem
  Sieg, FFA mit abgelehnten doppelten Siegern, vollständigem Abschluss,
  Disqualifikation, Notiz und weiterhin erreichbarer Orga-Korrektur.
- `manage.py check`, `makemigrations tournaments media_designer --check --dry-run`
  und `git diff --check` erfolgreich. Keine zusätzliche Audit-Migration nötig.

## Grenzen und bestehender Hinweis außerhalb des Moduls

Lokal steht keine PostgreSQL-Instanz zur Verfügung. Die 15 Tests mit echten
Zeilensperren wurden deshalb auf SQLite übersprungen und sind nicht als bestanden
gezählt. Die PostgreSQL-16-CI umfasst Account-Löschung, Schweizer Runden und die
neuen Rennen zwischen Liga-Ergebnissen, Beitritten, Teamkapazität,
Veranstaltungsabschluss und Kaderänderung/Turnierstart.

Der globale Migrationscheck meldet weiterhin bereits bestehende Abweichungen der
Farbdefaults von `configuration.SiteCustomization` (`background_color`,
`primary_color`, `secondary_color`), für die er Migration 0021 vorschlägt. Dieser
Hinweis liegt außerhalb des Turniermoduls und wurde hier nicht durch eine neue
Theme-Migration verändert. Der vollständige globale CI-Lauf ist damit nicht als
erfolgreich nachgewiesen.

Die Änderung ist lokal umgesetzt; weder Deployment noch Git-Commit wurden
durchgeführt. Die Migration 0009 aus der vorherigen Schweizer Erweiterung bleibt
für deren Einführung erforderlich. Neue Texte können mit `seed_translations`
in die editierbaren Systemtexte übernommen werden.

## Anschließende Solo-Erweiterung

Auf Wunsch wurde die Solo-Anmeldung zur automatischen, abgesicherten
Reaktivierung früherer Teams erweitert. Die ursprüngliche Einordnung archivierter
Teams als generell unerwünschte Wiederverwendung ist damit korrigiert.
Details und aktuelle Testergebnisse stehen in [Solo-Reaktivierung](solo-team-reactivation.md).
