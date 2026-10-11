Verifikationszusammenfassung (9. Oktober 2026): **0 BESTÄTIGT / 0 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Keine Original-Findings zu klassifizieren. Die nachfolgenden Belege bestätigen die für die Nachprüfung relevanten Grenzen, ohne einen vollständigen erneuten Modulaudit zu behaupten.

Zusammenfassung: 0 Findings — Kritisch: 0, Hoch: 0, Mittel: 0, Niedrig: 0, Info: 0.

Keine nachvollziehbaren Findings im geprüften Modul.

Geprüft wurden Models, Zugriffsschutz, Views/URLs, Formulare, Services, HTML-Verarbeitung, privater Dateispeicher, Systemchecks, Admin, Migrationen, Templates und Editor-JavaScript. Die Wissensbasis ist ausdrücklich für alle aktiven Mitarbeiter vorgesehen. Alle Endpunkte einschließlich Anhängen prüfen diese Rolle; Schreibaktionen sind POST/CSRF-geschützt. Änderungen verwenden Transaktionen, Sperren und Versionsprüfungen. Anhänge haben Typ-, Größen- und Bilddimensionenprüfungen und werden ausschließlich über geschützte Downloads mit sicheren Headern ausgeliefert. Der Knowledge-Sanitizer escapet Text selbst; der in CONFIGURATION-01 beschriebene Text-Rekonstruktionsfehler greift hier nicht.

Bewertung auf Grundlage des Quellcodes; keine produktive Datenbank oder Dateibestände verändert.

## Zusätzliche Beobachtungen

Alle gemappten Views einschließlich UUID-Download tragen `staff_only` (`knowledge/urls.py:5`, `knowledge/views.py:76`, `:97`, `:118`, `:124`, `:137`, `:179`, `:194`, `:203`, `:224`, `:240`, `:258`); der Wrapper verlangt Login und aktiven nicht gelöschten Staff (`knowledge/access.py:9`, `:19`). Schreibservices prüfen den frisch gesperrten Actor erneut, benutzen Transaktionen sowie Versionen (`knowledge/services.py:15`, `:21`, `:86`, `:96`, `:107`); Admin-Schreibpfade sind verboten (`knowledge/admin.py:8`). Anhänge liegen im privaten Storage ohne öffentliche URL (`knowledge/storage.py:9`, `:18`, `config/settings.py` PRIVATE_MEDIA_ROOT), Uploads haben Dateityp-/10-MB-/Bildstruktur-/Pixelprüfungen (`knowledge/forms.py:79`), Downloads Staffschutz, Attachment-Disposition für Nichtbilder, nosniff und restriktive CSP (`knowledge/views.py:258`, `:266`). Anders als der Basissanitizer escapet Knowledge Textknoten ausdrücklich (`knowledge/content.py:14`); der CONFIGURATION-01-Doppelpayload blieb im isolierten Originalhelfer auch nach zweimaliger Bereinigung escaped. Leseviews bereinigen vor safe-Ausgabe zusätzlich (`knowledge/views.py:131`, `:219`, `templates/knowledge/page.html:11`, `templates/knowledge/revision.html:7`), Versionsdiffs sind normal escaped (`templates/knowledge/revision.html:10`). Kein zusätzlicher belegter Befund in diesen Pfaden.


## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |

**Prüfungen:** Keine Original-Findings. Rollen-, Versions-, Anhangs- und Ausgabeschutz erneut gelesen; alle 38 Tests inkl. PostgreSQL-Concurrency bestanden. Keine Anwendungscodeänderung erforderlich.
