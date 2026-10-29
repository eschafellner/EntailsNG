# Updates und Betriebsprüfung

Diese Anleitung aktualisiert eine vorhandene Installation. Ein frisches Setup steht in `../DEVELOPER_HANDOVER.md`. Kommandos im Repository ausführen; genutzte Compose-Profile immer beibehalten. Eine bestehende Anwendungs-`.env` niemals durch die Beispieldatei ersetzen.

## Vorbereiten

1. `git status` prüfen und den eingesetzten Commit samt lokalen Code-/Assetänderungen festhalten. Updates nicht über ungeklärte lokale Änderungen hinweg ausführen.
2. Eine verifizierte Sicherung für genau diesen Code-/Migrationsstand vorhalten. Die eingebauten Backups prüfen auch den Softwarefingerabdruck; ein Git-Tag allein bildet uncommittierte Änderungen nicht ab. `.env`, `SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `USER_BAN_HMAC_KEY`, `BACKUP_ENCRYPTION_KEY` und Zertifikate getrennt sichern. Verfahren und Grenzen: `backups.md`.
3. Releaseänderungen und Migrationen lesen. `configuration.0025_demodataset` ergänzt nur den Demo-Abschlussnachweis. Die bereits bestehende `tournaments.0017_rotate_exposed_invite_codes` ersetzt bei ihrer ersten Anwendung alle Teamcodes; bestehende Code-Einladungen werden ungültig. Ein erneutes `migrate` rotiert bereits migrierte Codes nicht erneut. Der [erweiterte Check-in](extended-checkin.md) bringt `users.0012_guest_photo`, `users.0013_guestphoto_notice_confirmed_at` und `configuration.0026_guest_photo` (nur neue Tabelle/Felder, Funktion standardmäßig aus) sowie den neuen Dienst `guest_photo_worker`; er entsteht mit dem folgenden `up -d --build`, ein reiner Neustart vorhandener Container legt ihn nicht an.
   `seating.0011_seating_label_charset` ändert keine Daten (SQL no-op), erlaubt aber für Sitzplatzbezeichnungen nur noch Buchstaben, Ziffern, Leerzeichen und `. - / #`, für Beschriftungen zusätzlich `, : ! ? & + ( )`. Bestehende Zellen mit anderen Zeichen bleiben erhalten, ein Plan lässt sich im Editor bzw. Admin aber erst nach deren Korrektur wieder speichern. Vor dem Update betroffene Zellen schreibfrei auflisten (Ausgabe: Plan-ID, X, Y, Bezeichnung, Beschriftung; leer = nichts zu tun):

   ```bash
   docker compose exec -T web python manage.py shell -c "import re; from seating.models import SeatingCell as C; ok=lambda v, e: re.fullmatch(r'[\w%s]*' % re.escape(e), v or '') is not None; [print(c.plan_id, c.x, c.y, repr(c.seat_label), repr(c.text_label)) for c in C.objects.only('plan_id', 'x', 'y', 'seat_label', 'text_label').iterator() if not (ok(c.seat_label, ' .-/#') and ok(c.text_label, ' .,:!?&+()-/#'))]"
   ```

   `configuration.0028_systemerrorlog_dedup_retention` ergänzt im Fehlerprotokoll Fingerabdruck, Zähler und letztes Auftreten (Bestandseinträge: Zeitpunkt des Eintrags; rückwärts ohne Datenänderung). Gleiche offene Fehler werden danach gezählt statt neu angelegt. Der Worker `guest_photo_worker` löscht beim nächsten stündlichen Lauf alle Einträge, die länger als `SYSTEM_ERROR_LOG_RETENTION_DAYS` (Default 30 Tage) zurückliegen, auch noch offene; wer ältere Einträge braucht, vorher den Wert in der `.env` erhöhen. Die öffentlichen Routen unter `/tinymce/` entfallen; der Editor im Admin lädt TinyMCE weiterhin aus den statischen Dateien.

   `events.0015_registration_protect` ändert keine Daten (SQL no-op): Benutzer und Events mit Eventanmeldungen lassen sich danach nicht mehr löschen, auch nicht im Admin; stattdessen gibt es die Admin-Aktion „Konto anonymisieren“ ([Kontolöschung](account-deletion.md)).

   Eigene SVG-Menüicons werden ab diesem Stand beim Speichern neu aus dem geprüften Baum erzeugt (Kommentare, XML-Deklaration und fremde Namespace-Attribute entfallen); `style`-Attribute und Verweise außerhalb des Icons (`href` ohne `#`) werden abgelehnt. Gespeicherte Icons ändern sich erst beim nächsten Speichern. Nach dem Update Einträge auflisten, die davon abweichen oder abgelehnt würden, und diese im Admin unter „Navigation“ prüfen und speichern bzw. das Icon ersetzen (schreibfrei; leer = nichts zu tun):

   ```bash
   docker compose exec -T web python manage.py shell -c "
   from configuration.models import NavigationItem as N
   from configuration.sanitizer import sanitize_and_validate_svg as clean
   for n in N.objects.filter(icon_name=N.IconChoices.CUSTOM):
       try:
           ok = clean(n.icon_svg) == n.icon_svg
       except Exception:
           ok = False
       if not ok:
           print(n.pk, n.title)
   "
   ```
4. Für den Compose-Healthcheck zusätzlich zur öffentlichen Domain `127.0.0.1` in `ALLOWED_HOSTS` setzen. Öffentliche Domain/CSRF-Origins und `PUBLIC_BASE_URL` weiterhin für die tatsächliche Installation konfigurieren. `DEMO_MODE=False` für den normalen Betrieb belassen.
5. Bei Änderungen, die nicht mit gleichzeitig laufendem altem Code kompatibel sind, schreibenden Zugriff in einem geplanten Wartungsfenster unterbinden und Mail-/Clan-/Gastfoto-/Backup-Worker kontrolliert stoppen. Ein Reverseproxy-Wartungsfenster ersetzt kein Datenbankbackup.

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
docker compose logs --tail=100 web email_worker clan_seat_worker guest_photo_worker nginx
docker compose exec -T web python manage.py showmigrations --plan
docker compose exec -T web python manage.py check --deploy
```

Für das Sicherheitsupdate B1 zusätzlich `docker compose exec -T web python scripts/dependency_inventory.py` ausführen; denselben Aufruf in `email_worker`, `clan_seat_worker` und bei aktiviertem Backupprofil in `backup_worker` wiederholen. Erwartet werden Django 6.0.9 entsprechend dem Pin, python-dotenv 1.2.4 und pip 26.2.1. Den Imagebezug aller Anwendungsdienste mit dem geprüften Artefakt abgleichen. Neue Nachweise: [B1](b1-django-security-update-results.md). Eine Rückkehr zu Django 6.0.7 öffnet die bekannte Header-DoS-Lücke erneut; einen solchen Stand nicht öffentlich freigeben. Bei Problemen gegebenenfalls Wartungszugriff beschränken und eine korrigierte Version bereitstellen.

Healthroute: `/api/health/`, 200 bei erreichbarer DB und funktionierendem Cache, 503 bei deren Ausfall; eine unzulässige Hostangabe führt bereits vorher zu 400. `check_runtime` prüft zusätzlich ausstehende Migrationen, das tatsächliche Cachebackend und bei aktiviertem Backup die passenden nativen PG-Tools. Es führt keine Seeds/Migrationen aus und schreibt keine Fachdaten; die Cacheprüfung verwendet ausschließlich einen eigenen kurzlebigen Testschlüssel. Ausgabe optional mit `--json`. Normales `DEBUG=False` verlangt Redis, auch ohne `--require-redis`.

Bei einem Fehler während einer irreversiblen Datenmigration nicht blind auf alten Code oder rückwärts migrieren. Schreibzugriffe pausiert lassen, angewendeten Stand erfassen und das zuvor geprüfte Wiederherstellungsverfahren mit dem passenden alten Softwarestand nutzen. Produktive Restore-Aktionen benötigen eine konkrete Betriebsentscheidung. Nach Restore Sessions/Codes, Cache und Mailpause beachten; Mail im Backup-Admin erst nach Prüfung wieder freigeben.

Die bestehenden Volumes bleiben erhalten. `docker compose down --volumes`, pauschales Löschen von Datenverzeichnissen und der alte Snapshotimport sind keine Updateschritte.

## Isolierte Integrationsnachweise

Die CI führt `scripts/setup_smoke.py`, `scripts/redis_smoke.py` und `scripts/container_smoke.py` aus. Der Containerlauf kopiert den Arbeitsstand ohne Anwendungs-`.env`, entfernt feste Containernamen/Hostports, vergibt eigene Volume-/Netzwerknamen und verwendet freie Loopbackports. SELinux-Relabeling betrifft nur die Kopie. Nach dem Lauf werden seine eigenen Ressourcen entfernt. Optional `--performance` für HTTP-Messungen durch Nginx/Gunicorn. Ein Testlauf kann Images/Buildcache herunterladen und benötigt Docker sowie ausreichend Platz; er ersetzt kein Deployment.
