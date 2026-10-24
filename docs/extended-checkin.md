# Erweiterter Check-in mit Gastfoto

Stand: 23. Oktober 2026. Optionale Identitätsprüfung am Einlass: Nach dem Scan
sieht die Orga das hinterlegte Foto des Gastes. Ohne Foto ist kein Check-in
möglich; die Orga nimmt es dann direkt am Scanner auf.

## Einrichtung

Unter „Allgemeine Konfiguration“ → „Erweiterter Check-in“:

- **Erweiterter Check-in (Gastfoto)** schaltet die Funktion ein (Standard: aus).
- **Gastfotos löschen nach X Tagen** (Standard 14, höchstens 365, 0 = direkt
  danach). Gezählt wird ab dem Ende der letzten nicht stornierten Veranstaltung
  des Gastes, ohne Anmeldung ab dem Hochladen.

Den Datenschutzhinweis der Veranstaltung um das Gastfoto ergänzen (Zweck,
Sichtbarkeit, Löschfrist, Pflicht für den Einlass, Minderjährige), siehe
Baustein unten. Der Text im Profil ist der Systemtext `guest_photo_notice`.

Mitarbeiter ohne Superuser-Rechte brauchen für die Adminansicht „Gastfotos“ die
Rechte „Can view“ bzw. „Can delete Gastfoto“. Dort lassen sich einzelne Fotos
ansehen und löschen sowie über „Alle Gastfotos jetzt löschen“ alle auf einmal
entfernen. Fotos anlegen oder ändern ist im Admin nicht möglich.

## Ablauf

- **Gast:** Im Profil Foto hochladen, ersetzen oder löschen. Die Ticketkarte
  zeigt einen Hinweis, solange kein Foto vorhanden ist, und das Foto im QR-Fenster.
- **Orga:** Der Scanner zeigt nach jedem Scan das Foto zum Vergleich. Fehlt es,
  meldet er „Foto erforderlich“; „Foto aufnehmen und einchecken“ öffnet die
  Rückkamera, speichert das Foto und checkt in einem Schritt ein.
- Die Sperre gilt für QR-Scan, Ticket-Code, Teilnehmerliste, Check-in-Link und
  Admin-Aktion. Bereits eingecheckte Gäste bleiben unberührt; Auschecken bleibt möglich.
- Fällt ein Gerät aus, mit einem anderen Mitarbeiter-Handy weiterarbeiten. Die
  Kamera braucht HTTPS und eine einmalige Browserfreigabe je Gerät.

Die Teilnehmerliste im Scanner kennzeichnet noch nicht eingecheckte Gäste ohne
Foto mit „📷 Foto fehlt“.

## Speicherung und Zugriff

- Fotos werden als JPEG (max. 600 px Kante) ohne EXIF-/GPS-Daten neu kodiert
  und liegen in `private_media/guest_photos/`, ohne öffentliche URL.
- Ausgabe nur über `/photos/<user_id>/`: der Gast selbst immer, Mitarbeiter nur
  bei aktivem erweiterten Check-in, Antwort mit `Cache-Control: no-store`.
- Bei der Kontolöschung wird das Foto sofort entfernt.
- Lädt der Gast selbst hoch, speichert `notice_confirmed_at` den Zeitpunkt, zu dem
  er den Hinweis bestätigt hat. Eine Aufnahme am Einlass setzt das Feld zurück.

## Löschung

Der Compose-Dienst **guest_photo_worker** ruft stündlich auf:

```bash
python manage.py purge_guest_photos --daemon --interval 3600
python manage.py purge_guest_photos --dry-run   # nur zählen
```

Der Befehl berechnet alle Fristen neu (geänderte Löschfrist, Anmeldungen aus
dem Admin) und löscht abgelaufene Fotos, Datensätze ohne Datei sowie Dateien
ohne Datensatz, die älter als eine Stunde sind. Wird die Funktion abgeschaltet,
läuft die Löschung weiter.

## Backups

Gastfotos sind von Backups ausgeschlossen (`pg_dump --exclude-table-data`,
Medienordner). Eine Wiederherstellung entfernt Fotodatensätze auch aus älteren
Archiven und löscht danach die verbliebenen Fotodateien; Gäste werden am Einlass
neu fotografiert. Bei einem Rollback bleiben Datenbank und Fotodateien erhalten.

## Baustein für die Datenschutzerklärung

Unverbindlicher Entwurf, vor Veröffentlichung an die eigene Rechtsgrundlage,
Verantwortliche und Fristen anpassen und rechtlich prüfen lassen:

> **Foto für den Einlass.** Ist der erweiterte Check-in aktiviert, speichern wir
> zu deinem Benutzerkonto ein Foto, um am Einlass zu prüfen, dass das Ticket
> von dir genutzt wird. Ohne Foto ist kein Check-in möglich; du kannst es vorab
> im Profil hochladen oder es wird am Einlass vom Orga-Team aufgenommen. Das
> Foto sehen nur du und das Orga-Team; es wird nicht veröffentlicht, nicht für
> Badges oder andere Zwecke verwendet und nicht automatisch ausgewertet
> (keine Gesichtserkennung). Wir speichern es ohne Standort- und Kameradaten
> und löschen es automatisch [X] Tage nach dem Ende deiner letzten
> Veranstaltung, ohne Anmeldung [X] Tage nach dem Hochladen, sowie sofort bei
> Löschung deines Kontos. Du kannst es im Profil jederzeit selbst löschen.
> Gastfotos sind nicht Teil unserer Datensicherungen. Bei Minderjährigen
> [Regelung zur Einwilligung der Erziehungsberechtigten ergänzen].
> Rechtsgrundlage: [z. B. Art. 6 Abs. 1 lit. b oder f DSGVO].

## Prüfung

```sh
python manage.py test users.test_guest_photo events.test_extended_checkin backups --noinput
node --test scripts/tests/checkin-scanner.test.cjs
```

Ein Kameratest auf echten Android- und iOS-Geräten steht noch aus.
