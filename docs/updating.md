# Updates und Betriebsprüfung

Diese Anleitung aktualisiert eine vorhandene Installation. Ein frisches Setup steht in `../DEVELOPER_HANDOVER.md`. Kommandos im Repository ausführen; genutzte Compose-Profile immer beibehalten. Eine bestehende Anwendungs-`.env` niemals durch die Beispieldatei ersetzen.

## Vorbereiten

1. `git status` prüfen und den eingesetzten Commit samt lokalen Code-/Assetänderungen festhalten. Updates nicht über ungeklärte lokale Änderungen hinweg ausführen.
2. Eine verifizierte Sicherung für genau diesen Code-/Migrationsstand vorhalten. Die eingebauten Backups prüfen auch den Softwarefingerabdruck; ein Git-Tag allein bildet uncommittierte Änderungen nicht ab. `.env`, `SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `USER_BAN_HMAC_KEY`, `BACKUP_ENCRYPTION_KEY` und Zertifikate getrennt sichern. Verfahren und Grenzen: `backups.md`.
3. Releaseänderungen und Migrationen lesen. `configuration.0025_demodataset` ergänzt nur den Demo-Abschlussnachweis. Die bereits bestehende `tournaments.0017_rotate_exposed_invite_codes` ersetzt bei ihrer ersten Anwendung alle Teamcodes; bestehende Code-Einladungen werden ungültig. Ein erneutes `migrate` rotiert bereits migrierte Codes nicht erneut.
4. Für den Compose-Healthcheck zusätzlich zur öffentlichen Domain `127.0.0.1` in `ALLOWED_HOSTS` setzen. Öffentliche Domain/CSRF-Origins und `PUBLIC_BASE_URL` weiterhin für die tatsächliche Installation konfigurieren. `DEMO_MODE=False` für den normalen Betrieb belassen.
5. Bei Änderungen, die nicht mit gleichzeitig laufendem altem Code kompatibel sind, schreibenden Zugriff in einem geplanten Wartungsfenster unterbinden und Mail-/Clan-/Backup-Worker kontrolliert stoppen. Ein Reverseproxy-Wartungsfenster ersetzt kein Datenbankbackup.

## Cloudflare Tunnel

Im Cloudflare-Dashboard den Service des öffentlichen Hostnamens auf **HTTP → nginx:8080** einstellen. Der öffentliche Nginx-Port 80 leitet auf HTTPS um und ist kein Tunnel-Origin. Port 8080 bleibt intern; keine zusätzliche Host-Portfreigabe anlegen.

Nach Übernahme des geprüften Codes:

```bash
docker compose --profile tunnel up -d --build
docker compose --profile tunnel up -d --force-recreate nginx cloudflared
docker compose exec -T web python manage.py check_runtime --health-host 127.0.0.1 --require-redis
docker compose ps
```

Bei aktiviertem Backupbetrieb jeweils zusätzlich `--profile backups` angeben. Den tatsächlichen externen HTTPS-Zugriff über den Tunnel separat prüfen; ein grüner interner Healthcheck bestätigt keine Cloudflare-Einstellung.

## VPS mit Let's Encrypt

```bash
docker compose --profile vps up -d --build
docker compose --profile vps up -d --force-recreate nginx certbot
docker compose exec -T nginx nginx -t
docker compose exec -T web python manage.py check_runtime --health-host 127.0.0.1 --require-redis
docker compose --profile vps ps
```

Für Erstausstellung bzw. Reparatur einer Zertifikatsinstallation `bash nginx/init-letsencrypt.sh` verwenden. Es prüft bestehende Certbot-Lineages, lädt das Zertifikat und aktiviert das VPS-Profil. Der dauerhafte Certbot setzt nach erfolgreicher Erneuerung einen Marker; `nginx/watch-certificates.sh` erkennt ihn alle 30 Sekunden und lädt nach erfolgreichem Konfigurationstest neu. Echte Ausstellung/Erneuerung mit Domain und Netzfreigaben in der Zielumgebung prüfen; die Shelltests verwenden keine öffentliche ACME-Ausstellung.

## Abnehmen und bei Fehlern eingreifen

`entrypoint.sh` führt normalerweise Migrationen, `collectstatic` und drei erforderliche Seeds aus. Ein Seedfehler bricht den Start jetzt ab; die Ursache im Log beheben. Mehr Web-/Workerprozesse lösen weder fehlende Migrationen noch eine falsche Hostliste.

```bash
docker compose logs --tail=100 web email_worker clan_seat_worker nginx
docker compose exec -T web python manage.py showmigrations --plan
docker compose exec -T web python manage.py check --deploy
```

Healthroute: `/api/health/`, 200 bei erreichbarer DB und funktionierendem Cache, 503 bei deren Ausfall; eine unzulässige Hostangabe führt bereits vorher zu 400. `check_runtime` prüft zusätzlich ausstehende Migrationen, das tatsächliche Cachebackend und bei aktiviertem Backup die passenden nativen PG-Tools. Es führt keine Seeds/Migrationen aus und schreibt keine Fachdaten; die Cacheprüfung verwendet ausschließlich einen eigenen kurzlebigen Testschlüssel. Ausgabe optional mit `--json`. Normales `DEBUG=False` verlangt Redis, auch ohne `--require-redis`.

Bei einem Fehler während einer irreversiblen Datenmigration nicht blind auf alten Code oder rückwärts migrieren. Schreibzugriffe pausiert lassen, angewendeten Stand erfassen und das zuvor geprüfte Wiederherstellungsverfahren mit dem passenden alten Softwarestand nutzen. Produktive Restore-Aktionen benötigen eine konkrete Betriebsentscheidung. Nach Restore Sessions/Codes, Cache und Mailpause beachten; Mail im Backup-Admin erst nach Prüfung wieder freigeben.

Die bestehenden Volumes bleiben erhalten. `docker compose down --volumes`, pauschales Löschen von Datenverzeichnissen und der alte Snapshotimport sind keine Updateschritte.

## Isolierte Integrationsnachweise

Die CI führt `scripts/setup_smoke.py`, `scripts/redis_smoke.py` und `scripts/container_smoke.py` aus. Der Containerlauf kopiert den Arbeitsstand ohne Anwendungs-`.env`, entfernt feste Containernamen/Hostports, vergibt eigene Volume-/Netzwerknamen und verwendet freie Loopbackports. SELinux-Relabeling betrifft nur die Kopie. Nach dem Lauf werden seine eigenen Ressourcen entfernt. Optional `--performance` für HTTP-Messungen durch Nginx/Gunicorn. Ein Testlauf kann Images/Buildcache herunterladen und benötigt Docker sowie ausreichend Platz; er ersetzt kein Deployment.
