# Konfiguration und Umgebungsvariablen

`config/settings.py` lädt die lokale `.env`; bereits gesetzte Prozessvariablen haben Vorrang. `.env.example` enthält **Produktionsvorgaben**, keine direkt passende Host-Entwicklungsumgebung. Schlüssel und Passwörter selbst setzen, nicht aus Dokumentation übernehmen.

| Variablen | Bedeutung, Default und Bedingung |
| --- | --- |
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | SECRET_KEY immer erforderlich; DEBUG standardmäßig False; ALLOWED_HOSTS dann Pflicht. Hosts ohne Schema, CSRF-Origins mit Schema. Für den Compose-Healthcheck zusätzlich `127.0.0.1` in ALLOWED_HOSTS aufnehmen. Bei DEBUG=True gilt nur ohne explizite Hostliste der Wildcard-Fallback. |
| `FIELD_ENCRYPTION_KEY`, `USER_BAN_HMAC_KEY` | Getrennter dauerhafter Schlüssel für SMTP-Geheimnisse; ohne FIELD-Schlüssel Fallback auf SECRET_KEY. HMAC-Schlüssel vor Nutzung der Adresssperrliste setzen und dauerhaft sichern. |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_CONN_MAX_AGE` | Produktion verlangt Name/User/Passwort. Hostdefault `db`, Port 5432, Verbindungsalter 600 Sekunden. Hostentwicklung nutzt 127.0.0.1; Compose überschreibt Host/Port für App und Worker. `DB_ENGINE` wird nicht ausgewertet. |
| `REDIS_URL`, `WEB_CONCURRENCY` | REDIS_URL für laufende Produktion Pflicht; Entwicklung ohne URL und Tests verwenden LocMem. Compose setzt redis://redis:6379/1. Gunicornstandard 3 im Image; kein Einfluss auf runserver oder PostgreSQL. |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `DEFAULT_FROM_EMAIL`, `SERVER_EMAIL`, `EMAIL_TIMEOUT` | Backenddefault ConfiguredSMTPBackend; Port 587, TLS True, SSL False, Timeout 10s. Servervorgaben gelten im Adminmodus „Vom Server vorgegeben“; eigene SMTP-Konfiguration kommt aus der DB. Absender, Aktivierung und Sandbox werden ebenfalls im Admin verwaltet. |
| `EMAIL_ASYNC_QUEUE`, `EMAIL_QUEUE_LEASE_TIMEOUT_SECONDS` | Defaults True und 300s; in der Beispiel-.env nicht aufgeführt, aber von Settings gelesen. |
| `PUBLIC_BASE_URL` | Absolute Links in Hintergrundmails, Default http://localhost:8000; für die tatsächliche öffentliche/lokale URL setzen. |
| `PRIVATE_MEDIA_ROOT`, `SERVE_MEDIA` | Private Anhänge standardmäßig private_media/ im Repo; SERVE_MEDIA standardmäßig DEBUG. In Compose öffentliche Medien über Nginx, private Anhänge ausschließlich über autorisierte Django-Views. |
| `BACKUP_ROOT`, `BACKUP_ENCRYPTION_KEY`, `BACKUP_PG_BIN_DIR` | Privater Speicher standardmäßig backups_data/; Aktivierung benötigt einen Base64-Schlüssel mit 32 dekodierten Bytes und PG-Tools derselben Hauptversion. Native Tools optional über Verzeichnis angeben. Schlüssel separat sichern. |
| `BACKUP_KEEP_COUNT`, `BACKUP_MAX_UPLOAD_BYTES`, `BACKUP_MAX_UNPACKED_BYTES`, `BACKUP_MAX_FILES`, `BACKUP_MIN_FREE_BYTES`, `BACKUP_DRAIN_TIMEOUT`, `BACKUP_OPERATION_TIMEOUT` | Defaults 7 Sicherungen, 1 GiB Upload, 10 GiB entpackt, 50.000 Dateien, 256 MiB freier Mindestplatz, 60s Drain und 1800s Operation. Nginx hat eigene Upload-/Timeoutgrenzen. |
| `BEHIND_PROXY`, `USE_X_FORWARDED_FOR`, `NUM_PROXIES`, `TRUST_CLOUDFLARE` | Defaults True, gleich BEHIND_PROXY, 1, False. Vertrauen setzt einen kontrollierten Proxy-Eingang voraus; lokal BEHIND_PROXY=False. Öffentliche Nginx-Eingänge überschreiben Client-Metadaten; der interne Tunnel-Eingang verarbeitet sie. |
| `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD` | Werden unter DEBUG=False gesetzt; Defaults True/True/True/31536000/True/True. Healthroute vom Django-SSL-Redirect ausgenommen. |
| `DOMAIN_NAME`, `CERTBOT_EMAIL`, `HTTP_PORT`, `HTTPS_PORT`, `CLOUDFLARE_TUNNEL_TOKEN` | Nginx-/ACME-/Tunnelkonfiguration; öffentliche Portdefaults 80/443. Tunnel-Token nur für Profil tunnel; interner Originport 8080 wird nicht am Host publiziert. |
| `DEMO_MODE`, `LOAD_DEMO_DATA`, `INSTALL_DEMO_DATA`, `SKIP_ENTRYPOINT_INIT`, `SKIP_ENTRYPOINT_WAIT`, `SKIP_ENTRYPOINT_MIGRATION` | Dockerinitialisierung, siehe `entrypoint.sh`; Demo standardmäßig aus; DEMO_MODE wird zusätzlich als Django-Setting gelesen. Demoaktivierung akzeptiert `true` oder `1`; INSTALL_DEMO_DATA ist ein Installer-Alias; Worker überspringen je nach Compose-Konfiguration Initialisierung bzw. Warten/Migration. Demoaktivierung verwendet jetzt den atomaren Generator, keinen Snapshotimport; bestehende Fachdaten ohne gültigen Marker führen zum Abbruch. |
| `DJANGO_LOG_LEVEL` | Default INFO; Logging nach stdout. |

Belege für Defaults: `config/settings.py`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`. Adminwerte sind zusätzlich in der Datenbank gespeichert und werden nicht allein durch die `.env` beschrieben.


Die aktuelle Beispieldatei erlaubt den internen Healthcheck-Host bereits. Der Seed-Generator wird mit `DEMO_MODE=True python manage.py seed_demo_data` ausdrücklich angefordert.
