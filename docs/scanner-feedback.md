# Rückmeldung am Check-in-Scanner

Stand: 30. September 2026. Die Rückmeldung erscheint ausschließlich auf dem Gerät der Orga unter `/checkin/scanner/`.

- Nach einer Serverbestätigung erscheint das Ergebnis drei Sekunden lang groß über dem Kamerabild. Anschließend bleibt es in der Ergebniskarte stehen. Auf Smartphones steht die Karte vor der Kamera.
- Grün mit Haken bedeutet erfolgreicher Check-in. Gelb kennzeichnet bereits eingecheckte Gäste, Auschecken oder eine Anfragesperre. Rot zeigt Ablehnungen mit dem konkreten Grund. Nickname, Sitzplatz und lokale Check-in-Uhrzeit ergänzen die Rückmeldung.
- Kamera, manuelle Ticket-Code-Eingabe, USB-Scanner mit Tastatureingabe und Tabellenaktionen verwenden dieselbe Anzeige. Enter in einer eindeutigen Teilnehmersuche verwendet den Ticket-Code und kann einen bereits eingecheckten Gast nicht versehentlich auschecken. Auschecken erfolgt weiterhin über den Tabellenbutton.
- Während einer Anfrage und der anschließenden Lesepause sind weitere Check-in-Aktionen gesperrt. Ein dauerhaft im Kamerabild gehaltener QR-Code löst keine Folgeanfrage aus. Für einen bewussten erneuten Scan den Code mindestens 1,5 Sekunden aus dem Kamerabild nehmen.
- Nach spätestens 15 Sekunden ohne Antwort wird die Anfrage abgebrochen. Verbindungsfehler, Serverfehler und abgelaufene Sitzungen zeigen „Keine Bestätigung erhalten“. Der Server kann bereits gespeichert haben: Status prüfen oder den Ticket-Code erneut scannen. Die Teilnehmerliste wird zur erneuten Statusprüfung geladen.
- Ergebnisse verwenden Text und Symbole zusätzlich zur Farbe sowie eine Live-Region für Screenreader. API-Texte werden als Text ausgegeben. Ton und Vibration ergänzen die Anzeige, sofern der Browser sie unterstützt.

Die neuen Texte beginnen mit `scanner_feedback_`. Die Standardtexte funktionieren sofort. `python manage.py seed_translations` macht fehlende Schlüssel im Admin bearbeitbar. Eine Datenbankmigration ist nicht erforderlich.

## Prüfung

```sh
python manage.py test events --noinput
node --test scripts/tests/checkin-scanner.test.cjs
```

100 Event-Tests und sieben JavaScript-Tests erfolgreich. Die JavaScript-Prüfungen decken insbesondere gleichzeitige Anfragen, Lesepause, gehaltene QR-Codes, erneutes Scannen, abgelehnte Tickets, sichere Textausgabe, Verbindungsfehler und die Enter-Suche ab. Sie laufen auch in CI.

Zusätzlich im lokalen Browser auf Desktop- und Smartphone-Größe geprüft: erfolgreicher Check-in, wiederholter Scan, unbezahltes Ticket, Tabellenaktionen und Teilnehmerzählung. Kameraerkennung und Mehrfachscan-Sperre sind automatisiert geprüft; ein tatsächlicher Kamera-/USB-Hardwaretest steht noch aus.
