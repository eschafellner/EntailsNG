# Ausgehende E-Mails aufräumen

Unter **Backend → E-Mails → Ausgehende E-Mails → Aktion** stehen vier Aktionen bereit:

- Alle Emails älter als 30 Tage löschen
- Alle Emails älter als 90 Tage löschen
- Alle Emails älter als 180 Tage löschen
- Alle Emails älter als 365 Tage löschen

Eine Aktion wählen und **Ausführen** anklicken. Eine Markierung von Einträgen
ist nicht erforderlich. Die Aktion erfasst alle passenden E-Mails, unabhängig
von Auswahl, Suche, Statusfilter oder angezeigter Seite.

Die Bestätigungsseite zeigt Anzahl, Zeitgrenze und die ersten 50 betroffenen
Einträge. **Abbrechen** kehrt zur Liste zurück. Erst der Button zum endgültigen
Löschen entfernt die Einträge. Ohne Treffer erscheint ein Hinweis in der Liste.

## Welche Einträge werden gelöscht?

Maßgeblich ist **Erstellt am**, nicht der Versandzeitpunkt. „Älter als 30 Tage“
bedeutet streng vor dem Zeitpunkt des Aktionsstarts minus 30 × 24 Stunden.
Einträge genau auf der Zeitgrenze bleiben erhalten. Die Zeitgrenze bleibt
zwischen Vorschau und Bestätigung gleich.

Gesendete, ausstehende, fehlgeschlagene und abgelaufene E-Mails werden entfernt.
Gelöschte ausstehende Nachrichten werden nicht mehr versendet; gelöschte
Fehlerfälle können nicht mehr erneut eingereiht werden. Nachrichten, die bereits
in den Postfächern zugestellt wurden, sind davon unabhängig.

Einträge mit **Wird gesendet** sowie während der Löschung gesperrte Datensätze
bleiben erhalten. Die Aktion kann nach Abschluss des laufenden Versands erneut
ausgeführt werden. PostgreSQL-Zeilensperren mit `skip_locked` verhindern einen
Konflikt mit der bestehenden E-Mail-Warteschlange.

## Berechtigungen und Betrieb

Die Aktionen erfordern Zugriff auf die E-Mail-Liste und die Berechtigung
**Ausgehende E-Mail löschen**. Die Rechte werden beim Bestätigen erneut geprüft.
Die Bestätigung ist CSRF-geschützt, an Benutzer, Frist und Zeitgrenze gebunden
und eine Stunde gültig. Löschungen erscheinen im regulären Django-Adminprotokoll.
Die bestehenden Aktionen zum manuellen Löschen und erneuten Versand behalten
ihre bisherige Auswahlfunktion.

Keine Migration, neuen statischen Dateien oder zusätzlichen Dienste erforderlich.
Nach Übernahme des Codes die Webprozesse neu starten.

## Prüfung (6. Oktober 2026)

`python manage.py test emails --noinput`: **81 Tests erfolgreich**, darunter
21 neue Aufräumtests. Abgedeckt sind alle vier Fristen und ihre exakten Grenzen,
globale Anwendung trotz Auswahl und Filtern, unveränderte Zeitgrenze bei späterer
Bestätigung, Statusbehandlung, Vorschaugröße und HTML-Escaping, fehlende,
manipulierte und abgelaufene Bestätigungen, Rechteentzug, CSRF sowie unveränderte
Standardaktionen. Ein PostgreSQL-Paralleltest hält eine Zeilensperre wie der
Worker und bestätigt, dass die Bereinigung den Eintrag überspringt.

Zusätzlich im Browser mit einer separaten PostgreSQL-Vorschaudatenbank geprüft:
alle vier Einträge im Aktionsmenü, Start ohne Zeilenauswahl, Vorschau, Abbrechen
und bestätigte Löschung. Von zwölf Testnachrichten wurden neun passende gelöscht;
die zwei jüngeren und die gerade versendete Nachricht blieben erhalten.
