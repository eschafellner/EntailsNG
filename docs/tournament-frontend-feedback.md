# Turnieransichten und Anmeldung schließen

Stand: 5. Oktober 2026. Umsetzung des Testerfeedbacks zur Turnieroberfläche.

## Anzeigen

- **Turnierstatus:** Im Kopf der Detailseite steht immer der aktuelle Status,
  unabhängig davon, ob der Besucher mit einem Team angemeldet ist. Abgesagte
  Turniere werden ausdrücklich als abgesagt angezeigt und bieten keine
  Anmelde- oder Startaktionen an.
- **Anmeldestatus und Kader:** Die Teilnehmerliste zeigt „Angemeldet“ oder
  „Zurückgezogen“ sowie „Vollzählig“, „Unvollständig“ oder „Ungültiger Kader“
  mit dem aktuellen Stand, etwa 4/5 bestätigte Spieler. Derselbe Kaderstand
  erscheint beim eigenen Anmeldestatus im Turnierkopf. Nur bestätigte
  Mitgliedschaften zählen; Änderungen werden beim nächsten Aufruf angezeigt.
  Ein zulässiger unvollständiger Kader bleibt als unvollständig gekennzeichnet,
  mit dem separaten Hinweis auf die gewählte Teamgrößenregel.
- **Urkunden:** Der Link „Urkunden gestalten und exportieren“ erscheint auf der
  Turnierdetailseite nur für Mitarbeiter und nur bei abgeschlossenem Turnier.
  Der Medien-Designer behält seine bisherigen Rechte und Exportprüfungen.
- **Neustarts:** Neue Ausgaben zeigen keinen Verweis auf das Originalturnier.
  Herkunft, Anlass und Teamübernahme bleiben im Backend erhalten. Die Links
  beim Original auf sichtbare neue Ausgaben bleiben bestehen.
- **Turnierübersicht:** Verbliebene Merge-Konfliktmarkierungen und der doppelte
  Metadatenblock sind bereinigt. Anmeldeschluss, Turnierstart und Turnierleitung
  bleiben sichtbar.

## Anmeldung schließen

1. Die Turnierdetailseite als Orga öffnen und **Anmeldung schließen** wählen.
2. Der ausgeklappte Bereich erklärt die Folgen. Mit **Jetzt Anmeldung schließen**
   bestätigen oder mit **Abbrechen** zuklappen.
3. Der Status wechselt auf **Anmeldung geschlossen**. Bestehende Anmeldungen und
   Anmeldezeiten bleiben erhalten. Neue Anmeldungen werden abgewiesen.
4. Spielplan und Turnierstart erfolgen später über **Baum jetzt generieren**
   beziehungsweise beim Schweizer System über **Runde 1 vorbereiten**. Die
   bisherigen Startprüfungen, einschließlich der Teamgrößenregel, bleiben aktiv.

Die Aktion ist für aktive Mitarbeiter/Superadmins und den zugewiesenen
Turnieradmin beziehungsweise Support verfügbar. Sie gilt nur für offene,
noch nicht generierte Turniere in einer nicht beendeten/abgesagten Veranstaltung.
Auch eine durch Zeitablauf beendete Veranstaltung sperrt die Aktion.
Entwürfe werden weiterhin über die vorhandene Veröffentlichungsaktion geöffnet.

`TournamentLifecycleService.close_registration()` prüft Rechte und Zustand
innerhalb einer Transaktion. Die Sperrreihenfolge ist **Event → Turnier**,
wie bei Anmeldung und Start. Eine Anmeldung, die zuerst abgeschlossen wird,
bleibt erhalten; eine Anmeldung, die hinter dem Schließen wartet, wird gesperrt.
Der Frontend-Endpunkt verlangt Login, POST und einen gültigen CSRF-Token.
Er generiert keine Matches und entfernt keine Teams. Wiederholte Aufrufe oder
Aufrufe für laufende/beendete/abgesagte Turniere verändern den Zustand nicht.

## Installation und Prüfung

```sh
python manage.py seed_translations
python manage.py collectstatic --noinput
```

Anschließend die Webprozesse neu starten. Keine zusätzliche Migration nötig;
der vorhandene Status `CLOSED` wird verwendet. Übersetzungstexte und statische
Dateien wurden lokal aktualisiert. Kein Deployment ausgeführt.

```sh
DB_ENGINE=sqlite python manage.py test tournaments --noinput
```

346 Tests: 322 erfolgreich, 24 PostgreSQL-Fälle auf SQLite übersprungen.
19 neue Funktionstests prüfen Status und Rollen, Kaderkennzeichnung,
Urkunden-Link, Konfliktbereinigung, Neustart-Historie, separates Schließen,
CSRF/POST, Spielplanstart nach Schließen und die Event-/Turniersperren.
Zwei neue PostgreSQL-Fälle prüfen parallele Anmeldung und Schließen in beiden
Reihenfolgen. Sie sind in der PostgreSQL-CI enthalten und wurden lokal nicht
gegen PostgreSQL ausgeführt. Systemcheck, Migrationscheck für `tournaments`
und Prüfung auf Whitespacefehler erfolgreich.

Browserprüfung mit getrennten lokalen QA-Daten: Bestätigung und Abbrechen,
erfolgreicher Wechsel auf `CLOSED`, beide Teams erhalten, keine Matches angelegt,
kein Originalverweis und keine Konfliktmarkierungen. Desktop und Smartphone
(390 px) zeigen Kaderkennzeichnungen und Status ohne horizontalen Überlauf.
