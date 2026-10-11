Verifikationszusammenfassung (9. Oktober 2026): **0 BESTÄTIGT / 0 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Keine Original-Findings zu klassifizieren. Die Aussage „keine Findings“ ist keine Garantie einer vollständigen Fehlerfreiheit.

Zusammenfassung: 0 Findings — Kritisch: 0, Hoch: 0, Mittel: 0, Niedrig: 0, Info: 0.

Keine eigenständigen Findings im geprüften Code nachvollzogen.

Geprüft: Formulare, Views/URLs, Services, signierte Submission-Tokens, App-Konfiguration, Kontakt-Template und vorhandene Sicherheits-/Concurrency-Tests. Die App hat keine eigenen Modelle, Migrationen, Admins oder Serializer; Konfiguration und Outbox liegen in `configuration` bzw. `emails` und werden dort bewertet.

Berücksichtigt: GET/POST-Begrenzung, CSRF, session- und benutzergebundene zeitlich begrenzte Tokens, POST-Redirect-GET, Honeypot, Eingabelängen, serverseitige Kategorie-/Empfängerauflösung, atomare Outbox-Erstellung, persistente Limits und parametrisierte PostgreSQL-Advisory-Locks. IP-Limits hängen von der korrekten Proxy-Konfiguration ab (PROJECT-01); die senderbezogenen DB-Limits bleiben davon unabhängig.

## Zusätzliche Beobachtungen

Nachprüfung der vorhandenen Absicherungen: Der einzige gemappte Formularpfad (`config/urls.py:68`, `contact/urls.py:5`) erlaubt GET/POST (`contact/views.py:13`) mit globalem CSRF und Token im Formular (`config/settings.py:102`, `templates/contact/form.html:22`). Das Formular begrenzt Längen und aktive Kategorien (`contact/forms.py:9`, `:15`, `:26`); der Service prüft die Kategorie und serverseitige Empfänger unter Sperre erneut (`contact/services.py:106`, `:109`, `:115`). Signatur, Ablauf, Session-/Actorbindung werden validiert (`contact/tokens.py:25`, `:27`), Sender/IP/Submission-Limits mit parametrisierten Advisory-Locks serialisiert (`contact/services.py:46`, `:88`, `:97`, `:101`). Doppelte Empfänger einer Submission sind zusätzlich durch `emails/models.py:430` geschützt. Für Kontaktbetreffzeilen existiert bereits eine explizite Längen-/CRLF-Prüfung (`contact/services.py:127`); das ist eine lokale Absicherung gegenüber dem allgemeinen EMAILS-02-Muster. Die IP-Herkunft hängt weiterhin von PROJECT-01 ab; der Senderlimitpfad bleibt unabhängig davon wirksam. Keine zusätzlichen eigenständigen Probleme im nachverfolgten Pfad belegt.


## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |

**Prüfungen:** Keine Original-Findings; vorhandene Schutzpfade erneut gelesen. Alle 38 Contacttests inkl. PostgreSQL-Advisory-Lock-Concurrency bestanden. Keine Anwendungscodeänderung erforderlich.
