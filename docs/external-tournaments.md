# Externe Turniere in der Turnierübersicht

Stand: 8. Oktober 2026.

Externe Turniere erscheinen als regulär gestaltete Karten in der Übersicht
des aktiven Events. **Zum Turnier →** öffnet die hinterlegte HTTPS-Adresse
direkt im selben Browser-Tab. Anbietername und die Kennzeichnung **Extern**
machen das externe Ziel erkennbar. Anmeldung und Spielplan werden beim
Anbieter geführt.

## Pflege durch die Orga

1. Im Django-Admin im Bereich **Externe Turniere** der App `tournaments`
   einen Eintrag anlegen.
2. Veranstaltung, vorhandenes Spiel, Turniertitel, Anbietername und die
   vollständige HTTPS-Turnieradresse auswählen beziehungsweise eintragen.
   Beispielsweise lässt sich `https://alpenscene.pro/` hinterlegen; eine
   konkrete Turnierseite mit Pfad, Parametern und Fragment ist ebenso möglich.
3. Optional Kurzbeschreibung (höchstens 500 Zeichen), Turniermodus,
   Anmeldeschluss und Turnierstart ergänzen. Fehlende Termine werden nicht
   angezeigt; der Turnierstart besitzt keinen automatischen Ersatztermin.
4. Als **Entwurf** speichern, um die Karte nur aktiven Mitarbeitern in der
   Frontendübersicht zu zeigen. Der Admin kann den Eintrag jederzeit bearbeiten.
5. Den Veröffentlichungszustand auf **Veröffentlicht** setzen und speichern.
   Der Eintrag ist dann für alle Besucher des aktiven Events sichtbar, auch
   ohne Login, Eventticket oder Check-in.
6. Zum Ausblenden wieder auf **Entwurf** stellen. Die Angaben bleiben erhalten.

Das gewählte Spiel liefert Spiellogo, Spielmodus und Teamgröße. Der zusätzliche
Turniermodus ist ausschließlich eine Anzeige. Alle Angaben einschließlich
Terminen werden von der Orga gepflegt; es findet keine automatische
Synchronisation mit dem Anbieter statt. Veröffentlichte Links bleiben auch
nach einem eingetragenen Anmeldeschluss erreichbar.

Mitarbeiter benötigen die Django-Berechtigungen für `ExternalTournament`:
`view_externaltournament`, `add_externaltournament`,
`change_externaltournament` und bei Bedarf `delete_externaltournament`.
Mitarbeiterstatus allein gewährt keine Admin-Bearbeitungsrechte. Superuser
haben den regulären vollständigen Adminzugriff. Die Frontendanzeige von
Entwürfen entspricht der bestehenden Regel für aktive, nicht gelöschte
Mitarbeiter und Superuser; Gäste erhalten dadurch keine Adminrechte.

## Grenzen zur internen Turnierverwaltung

`ExternalTournament` ist ein eigenes Modell mit separaten Event-/Spielrelationen
`external_tournaments`. Es erzeugt keine `Tournament`-Datensätze,
Turnieranmeldungen, Teams, Matches oder Ergebnisse. Interne Dienste und
Aktionsendpunkte verwenden weiterhin ausschließlich `Tournament`.

Damit bleiben Check-in, Kaderregeln, Anmeldung, Turnierbaum, Ergebnisprüfung,
Neustarts, Podium und Urkundenexport erhalten. Externe Einträge blockieren
den Eventabschluss nicht. Offene interne Turniere blockieren ihn weiterhin.

In der Übersicht werden externe Einträge alphabetisch nach den internen
Karten ergänzt. Die interne Abfrage, Kartenreihenfolge, Statusbuttons und
persönlichen Anmeldeinformationen sind unverändert. Der Leerzustand wird
angezeigt, wenn keine für den Besucher sichtbaren internen oder externen
Einträge vorhanden sind. Ohne aktives Event werden keine Einträge angezeigt.

## Links und Offline-Betrieb

Nur vollständige HTTPS-Adressen ohne Zugangsdaten, Leer-/Steuerzeichen oder
Backslashes sind erlaubt. Die Validierung läuft im Adminformular und beim
Speichern über das Modell. Vor Ausgabe des Links wird die Adresse erneut
geprüft, damit auch fehlerhafte Direktimporte keinen unsicheren Link erzeugen.
In diesem Fall zeigt die Karte **Link derzeit nicht verfügbar.**

Karteninhalte werden als Text ausgegeben und HTML wird maskiert. Neue Texte
stehen über `tournaments/external_texts.py` im bestehenden
`SystemTranslation`-System zur Verfügung.

Die Übersicht lädt weder Anbieterinhalte noch externe Bilder, iframes oder
Skripte. Sie benötigt keinen Anbieterzugriff und bleibt offline darstellbar;
erst das Öffnen der externen Seite benötigt deren Erreichbarkeit.

## Einführung

```sh
python manage.py migrate
python manage.py seed_translations
python manage.py collectstatic --noinput
```

Anschließend Webprozesse neu starten und den Orga-Gruppen die benötigten
Modellberechtigungen zuweisen. Keine neuen Pakete, Umgebungsvariablen,
Hintergrundprozesse oder externen API-Schlüssel erforderlich.

Migration `tournaments.0015_external_tournament` legt ausschließlich die neue
Tabelle samt Fremdschlüsseln an. Bestehende Turnierdaten werden nicht
umgeschrieben. Auf dem vorliegenden Arbeitsstand können zusätzlich noch
nicht eingespielte Migrationen anderer Erweiterungen vorhanden sein.

Migration, Übersetzungen und Beispieldaten wurden ausschließlich in einer
isolierten PostgreSQL-Vorschau angewendet. Die Anwendungsdatenbank wurde
nicht migriert, kein Deployment ausgeführt und kein Anbieter automatisch
als öffentliches Turnier angelegt.

## Prüfung

```sh
python manage.py test tournaments.test_external_tournaments --noinput
python manage.py test --noinput
node --test scripts/tests/*.test.cjs
python manage.py check
python manage.py makemigrations --check --dry-run
```

- 25 neue Funktionstests erfolgreich: Linkvalidierung, HTML-Maskierung,
  Entwurfsrechte, Eventfilter, gemischte und leere Übersichten, fehlende
  optionale Angaben, kollidierende IDs beider Modelle, Adminrechte,
  Veröffentlichung/Ausblenden, CSRF sowie interne Anmeldung, Generierung
  und Eventabschluss mit externen Einträgen.
- Vollständige Suite: **1.169 Python-Tests erfolgreich, keine Überspringungen**,
  gegen eine isolierte PostgreSQL-18.6-Instanz einschließlich nativer Backups
  und Parallelitätsprüfungen.
- **26 JavaScript-Tests erfolgreich**. Lokal mit Node 24 und
  `--test-isolation=none --test-reporter=spec` ausgeführt, um sämtliche
  Einzeltests sichtbar zu prüfen.
- Django-Systemprüfung, globaler Migrationsabgleich und Diff-Prüfung erfolgreich.
- Browserprüfung mit isolierten Beispieldaten: Adminanmeldung, Bearbeitung,
  erfolgreiches Speichern und anschließende Gastansicht; gemeinsame Desktopübersicht,
  öffentliche Karten und verborgene Entwürfe, vollständige Linkziele und
  fehlendes `target` für Navigation im selben Tab. Bei 390 und 320 Pixeln
  auch mit langen Turnier-/Anbieternamen kein horizontaler Überlauf.
- GitHub-CI und Docker-Imagebau wurden lokal nicht ausgeführt.

Vorschau mit Beispieldaten:
[Desktop](screenshots/external-tournaments-desktop.jpg),
[Mobil](screenshots/external-tournaments-mobile.jpg).
