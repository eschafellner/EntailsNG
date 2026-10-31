# Anmeldebestätigung und Ticket-Zahlungsfrist

## Anmeldebestätigung

`RegistrationService.register_user` stößt nach dem Commit `EventRegistration.send_registration_confirmation_email` an. Das gilt für neue und reaktivierte (zuvor stornierte) Anmeldungen. Keine Mail gibt es bei einer bereits bestehenden Anmeldung (erneuter Klick), bei Anmeldungen über eine bezahlte Clan-Sammelzahlung (`clan_seat_hold_id`) und für gelöschte Konten.

| Vorlage | Wann |
| --- | --- |
| `event_registration_confirmation` | Offener Betrag > 0 € und Bankdaten in der Allgemeinen Konfiguration hinterlegt (`can_show_payment_qr`). Enthält GiroCode, Bankdaten als Text und den Fristhinweis. |
| `event_registration_confirmation_free` | Kostenloses Ticket oder fehlende Bankdaten. Ohne Zahlungsblock; `{payment_hint}` erklärt den Grund. |
| `registration_payment_expired` | Automatische Stornierung wegen abgelaufener Zahlungsfrist. |

Inhalte: Benutzername, Klarname, Veranstaltung (Titel, Beginn/Ende in Europe/Vienna, Ort), Ticketkategorie, Preis zum Zeitpunkt der Anmeldung (`booking_price`), Verwendungszweck, Dashboard-Link (`PUBLIC_BASE_URL`). Fristsätze und Hinweise sind Systemtexte (`mail_payment_deadline_hint`, `mail_payment_no_deadline_hint`, `mail_registration_free_hint`, `mail_registration_payment_pending_hint`).

Die Vorlagen legt `seed_email_templates` bei Bedarf an (bestehende Anpassungen bleiben unverändert). Sie lassen sich im Admin bearbeiten oder deaktivieren.

### QR-Code in der Mail

Die Outbox speichert nur den EPC-Text (`OutgoingEmail.inline_qr_payload`), keine Bilddaten. Beim Versand erzeugt `emails.services.InlineQrEmail` daraus das PNG und hängt es als `multipart/related` an den HTML-Teil (`Content-ID: <payment_qr>`). In der Vorlage wird es mit `<img src="cid:payment_qr">` eingebunden. Der Payload ist identisch mit dem Dashboard-QR (`generate_epc_qr_payload`). Ändern sich Bankdaten zwischen Einreihen und Versand, enthält die Mail die Daten zum Zeitpunkt der Anmeldung.

## Zahlungsfrist je Ticketkategorie

`TicketType.payment_deadline` (optional, Datum) ist der letzte Tag für den Zahlungseingang; der Fristtag zählt vollständig mit (Europe/Vienna). Die Frist darf nicht nach dem Veranstaltungsende liegen. Beim Übernehmen von Ticketkategorien aus einem anderen Event wird sie nicht kopiert.

- Nach Fristablauf ist die Kategorie nicht mehr buchbar: Das Dashboard bietet sie nicht mehr an, `register_user` lehnt sie ab und wählt ohne Angabe die erste noch buchbare Kategorie.
- `PaymentDeadlineService.cancel_overdue_registrations` storniert offene Anmeldungen mit Preis > 0 €, deren Frist abgelaufen ist, über `PaymentService.mark_cancelled` (Sitzplatz wird frei) und verschickt `registration_payment_expired`. Unter Sperre wird erneut geprüft (Zahlung, Fristverlängerung, Clan-Deckung, Check-in). Beendete und abgesagte Events bleiben unberührt. Bezahlte, kostenlose und Anmeldungen ohne Frist werden nie storniert.
- Ausführung: automatisch in jedem Durchlauf des Workers `process_clan_seat_holds` (Compose: alle 60 s); einmalig per `python manage.py process_payment_deadlines`.
- Verlängert die Orga die Frist, gilt sie sofort auch für bestehende Anmeldungen. Eine stornierte Anmeldung kann die Orga wie bisher als bezahlt reaktivieren (mit Kapazitätsprüfung).
