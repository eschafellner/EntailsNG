Verifikationszusammenfassung (9. Oktober 2026): **4 BESTÄTIGT / 0 TEILWEISE ABGESICHERT / 0 FALSE POSITIVE / 0 NICHT ENTSCHEIDBAR**.

Stufe 2: Quellcodeprüfung einschließlich alternativer HTTP-/HTTPS-Eingänge und Admin-Framework. Produktions-Firewall, externe Renewal-Jobs und tatsächlich vergebene Staff-Permissions sind nicht aus dem Repository bestimmbar. Framework-Abgleich: `requirements.txt:1` pinnt Django 6.0.7; lokal verfügbare Prüfumgebung enthält 6.0.9. Das entscheidende Aktionsverhalten wurde zusätzlich am offiziellen 6.0.7-Quellcode abgeglichen. Keine Dienste oder Datenbankbestände verändert.

Zusammenfassung: 4 Findings — Kritisch: 0, Hoch: 0, Mittel: 4, Niedrig: 0, Info: 0.

Prüfumfang: `config/` (Settings, URLs, WSGI/ASGI), Middleware, gemeinsame Basistemplates, Dockerfile, Compose, Entrypoint, Nginx-Konfiguration und TLS-Skripte. Statische Codeprüfung; keine Änderungen am Anwendungscode und keine Eingriffe in laufende Dienste. Abhängigkeiten wurden nicht auf externe CVE-Datenbanken geprüft.

Eigene Django-Apps laut `config/settings.py:79`: users, events, configuration, contact, seating, info, knowledge, news, clans, emails, tournaments, media_designer, sponsors, backups (14). Außerdem installiert: django.contrib.admin, auth, contenttypes, sessions, messages, staticfiles sowie tinymce. `config` ist das Projektpaket, keine zusätzliche registrierte App. Framework-/Paketcode wird nicht als eigener Anwendungscode auditiert.

### [PROJECT-01] Öffentlich erreichbarer HTTP-Proxy übernimmt gefälschte Vertrauensheader
- Schweregrad: Mittel
- Kategorie: Security
- Fundstelle: nginx/templates/default.conf.template:8, :14, :22, :65, :82; docker-compose.yml:130; config/settings.py:300; users/auth_backends.py:36
- Beschreibung: Port 80 ist standardmäßig am Host veröffentlicht. Dort übernimmt Nginx beliebige `X-Forwarded-Proto`- und `CF-Connecting-IP`-Header vom Client. Ein gesetztes `X-Forwarded-Proto: https` unterdrückt den HTTPS-Redirect und wird von Django als sichere Verbindung interpretiert. `CF-Connecting-IP` wird selbst bei `TRUST_CLOUDFLARE=False` in `X-Real-IP` übersetzt; das Auth-Backend vertraut diesem Header.
- Auswirkung / Angriffsszenario: Ein direkter Request an Port 80 mit beiden Headern kann IP-basierte Login-/Formularlimits unter wechselnden scheinbaren IPs umgehen und Audit-IP-Adressen fälschen. Das accountbezogene Login-Limit bleibt bestehen. Sichere Session-Cookies werden dadurch nicht automatisch vom Browser über HTTP übertragen. Voraussetzung: direkter Zugriff auf den veröffentlichten HTTP-Port; eine zusätzliche Firewall kann ihn verhindern.
- Betroffener Code:
  ```nginx
  map $http_cf_connecting_ip $real_client_ip {
      default $http_cf_connecting_ip;
      ''      $remote_addr;
  }
  proxy_set_header X-Real-IP $real_client_ip;
  proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
  ```
- Empfehlung: Tunnel-Eingang und öffentliche Eingänge getrennt betreiben; am öffentlichen Eingang Vertrauensheader überschreiben. Cloudflare-Header ausschließlich von nachweislich vertrauenswürdigen Peers akzeptieren bzw. Tunnel-Eingang nicht am Host veröffentlichen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Der veröffentlichte Port 80 führt über die Maps und `location /` zu Gunicorn/Django. Ein Clientwert `https` verhindert beide Redirects, weil auch `SecurityMiddleware` über `SECURE_PROXY_SSL_HEADER` diese Angabe vertraut. Eine syntaktisch gültige gefälschte Cloudflare-IP wird unabhängig von `TRUST_CLOUDFLARE` als `X-Real-IP` weitergegeben. Keine Peer-Allowlist oder Nginx-Rate-Limit-Regel schützt diesen Eingang. IP-Validierung prüft nur das Format, nicht die Herkunft.
- **Belege / Gegenmaßnahmen:** `docker-compose.yml:130`, `nginx/templates/default.conf.template:8`, `:14`, `:22`, `:73`, `:82`, `config/settings.py:97`, `:298`, `users/auth_backends.py:24`, `:36`, `:66`. HTTPS überschreibt IP/Protokoll und entfernt den Cloudflare-Header (`nginx/templates/default.conf.template:143`); dieser Schutz gilt nicht für Port 80. Account-Sperren bleiben bestehen (`users/models.py:195`), sichere Cookies sind Produktionsdefaults (`config/settings.py:312`). Eine externe Firewall kann die Voraussetzung entziehen; ihr Vorhandensein ist nicht belegt.

### [PROJECT-02] Dokumentierter VPS-Start aktiviert keine wirksame automatische Zertifikatserneuerung
- Schweregrad: Mittel
- Kategorie: Konfiguration
- Fundstelle: docker-compose.yml:147, :151, :157; nginx/init-letsencrypt.sh:76
- Beschreibung: Der dauerhaft erneuernde Certbot-Service ist nur in den Profilen `vps`/`certbot` aktiv. Das Einrichtungsprogramm startet abschließend ausschließlich `docker compose up -d`. Die vorherigen `compose run --rm`-Aufrufe starten nur temporäre Certbot-Container. Zusätzlich enthält die Renewal-Schleife keinerlei Reload für Nginx, das Zertifikate beim Start/Reload einliest.
- Auswirkung / Angriffsszenario: Bei der dokumentierten Installation läuft kein Renewal-Daemon. Selbst bei manueller Profilaktivierung lädt Nginx erneuerte Zertifikate ohne externen Reload nicht nach. Nach Ablauf scheitert der direkte HTTPS-Zugriff mit Zertifikatsfehlern.
- Betroffener Code:
  ```yaml
  profiles:
    - vps
    - certbot
  entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done'"
  ```
- Empfehlung: Den VPS-Stack ausdrücklich mit dem Renewal-Profil starten und nach erfolgreicher Erneuerung einen kontrollierten Nginx-Reload einrichten.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Der dokumentierte VPS-Einstieg ruft genau das Bootstrap-Skript auf. Seine einmaligen `compose run`-Aufrufe aktivieren keinen dauerhaften profilierten Service. Der abschließende normale Start aktiviert kein Renewal-Profil. Der einzige vorhandene Nginx-Reload erfolgt unmittelbar nach der Erstausstellung; die Renewal-Schleife enthält keinen Deploy-Hook/Reload. Auch ein aktiviertes Profil allein behebt deshalb nicht den gesamten Befund.
- **Belege / Gegenmaßnahmen:** `README.md:140`, `nginx/init-letsencrypt.sh:42`, `:61`, `:72`, `:76`, `docker-compose.yml:151`, `:157`. Das Bootstrap-Skript lädt das erste echte Zertifikat nach (`nginx/init-letsencrypt.sh:72`), erneuerte Zertifikate später jedoch nicht. Im Repository existiert kein weiterer Renewal-/Reload-Job; externe Betriebsautomation bleibt unbekannt.

### [PROJECT-03] Vorhandenes Fallback-Verzeichnis verhindert die Ausstellung eines echten Zertifikats
- Schweregrad: Mittel
- Kategorie: Bug
- Fundstelle: nginx/init-letsencrypt.sh:29; nginx/init-certs.sh:9
- Beschreibung: Das Einrichtungsprogramm prüft ausschließlich, ob `live/<domain>` existiert, und beendet dann den Ausstellungspfad. Nginx erstellt genau dieses Verzeichnis mit einem Dummy-Zertifikat beim normalen Erststart. Auch nach einer fehlgeschlagenen Erstausstellung kann das Verzeichnis bestehen bleiben.
- Auswirkung / Angriffsszenario: Nach einem vorherigen normalen Compose-/Tunnel-Start oder einem abgebrochenen TLS-Setup meldet ein erneuter Aufruf ein bestehendes Zertifikat und stellt kein vertrauenswürdiges Zertifikat aus. Direkter HTTPS-Zugriff bleibt fehlerhaft.
- Betroffener Code:
  ```bash
  if [ -d "$CERT_PATH" ]; then
      docker compose up -d
      exit 0
  fi
  ```
- Empfehlung: Zertifikat, Domain, Aussteller, Gültigkeit und Certbot-Renewal-Konfiguration prüfen; Dummy-/unvollständige Installationen durch den Ausstellungspfad führen.
- Konfidenz: Hoch

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Der identische bind-gemountete Zertifikatsbaum wird beim gewöhnlichen Nginx-Start mit Dummy-Dateien gefüllt. Der spätere Bootstrap prüft nur das Verzeichnis, startet den Stack und beendet sich vor Löschung, Ausstellung und Reload. Dateivollständigkeit, Aussteller und Renewal-Konfiguration werden dort nicht geprüft. Ein neuer Start von `init-certs.sh` ersetzt vorhandene Dummy-Dateien ebenfalls nicht durch echte Zertifikate.
- **Belege / Gegenmaßnahmen:** `docker-compose.yml:138`, `:141`, `nginx/init-certs.sh:5`, `:9`, `:12`, `nginx/init-letsencrypt.sh:30`, `:31`, `:54`, `:61`. Die Prüfung auf beide PEM-Dateien in `nginx/init-certs.sh:9` schützt lediglich vor einem Nginx-Startfehler, nicht vor dem irrtümlichen Bootstrap-Abbruch.

### [PROJECT-04] Schreibende Admin-Aktionen verlangen kein Änderungsrecht
- Schweregrad: Mittel
- Kategorie: Security
- Fundstelle: emails/admin.py:255, :261, :293, :307; users/admin.py:41; events/admin.py:204, :439; configuration/admin.py:326; tournaments/admin.py:382
- Beschreibung: Zahlreiche eigene Admin-Aktionen verwenden `@admin.action(description=...)` ohne `permissions=['change']` und ohne interne Änderungsberechtigungsprüfung. Django setzt dabei keine implizite Änderungsberechtigung: `_filter_actions_by_permissions` nimmt Aktionen ohne `allowed_permissions` unverändert auf. Für den Zugriff auf die Changelist genügt das Modell-Leserecht. Der gesonderte Schutz für `list_editable` schützt diese Aktionen nicht.
- Auswirkung / Angriffsszenario: Ein aktiver Staff-Nutzer mit lediglich `emails.view_emailtemplate` kann per gültigem Admin-POST Vorlagen deaktivieren, obwohl `change_emailtemplate` fehlt. Dadurch können beispielsweise Verifizierungs- oder Passwort-Reset-Mails ausfallen; der Versandservice bricht für deaktivierte Vorlagen ab. Entsprechend lassen sich mit Modell-Leserechten unter anderem Login-Fehlversuchssperren zurücksetzen, Fehlerprotokolle bearbeiten oder Teamarchive ändern. Voraussetzung ist, dass delegierte Staff-Konten tatsächlich solche Leserechte besitzen; Superuser sind ohnehin vollständig berechtigt. Login, Staff-Prüfung und CSRF bleiben erforderlich.
- Betroffener Code:
  ```python
  @admin.action(description="Ausgewählte Vorlagen deaktivieren")
  def deactivate_templates(modeladmin, request, queryset):
      updated = queryset.update(is_active=False)
  ```
- Empfehlung: Für schreibende Aktionen mindestens `permissions=['change']` setzen; falls eine Fachberechtigung nötig ist, diese zusätzlich explizit prüfen. Bei relevanten objektbezogenen Einschränkungen auch jedes Zielobjekt autorisieren. Reine Exporte können ausdrücklich Leserechte verwenden. Alle eigenen Admin-Aktionen nach diesem Muster prüfen.
- Konfidenz: Hoch. Das Verhalten wurde im lokal installierten Django 6.0.7 anhand von `django/contrib/admin/options.py:1021, :1979, :2007` und `decorators.py:21` geprüft und mit dem originalen Vorlagen-Aktionsdekorator sowie verweigertem Änderungsrecht isoliert nachvollzogen. Es wurden keine Vorlagen geändert.

#### Verifikation
- **Urteil: BESTÄTIGT. Schweregrad: Mittel (unverändert).**
- **Begründung:** Der Pfad `/admin/emails/emailtemplate/` ist über `config/urls.py:18` und die Modellregistrierung erreichbar. Der Aktionsauswahlfilter übernimmt Aktionen ohne `allowed_permissions`; die Changelist verlangt nur Lesen oder Ändern und dispatcht gültige Aktions-POSTs vor der gesonderten `list_editable`-Änderungsprüfung. `ActionForm` validiert Auswahl und Ziel-IDs, ergänzt aber kein Änderungsrecht. `queryset.update()` löst keine Model-Clean-Prüfung aus. Die genannten weiteren schreibenden Aktionen enthalten ebenfalls keine nachgelagerte Actor-Prüfung.
- **Belege / Gegenmaßnahmen:** `emails/admin.py:261`, `:267`, `:273`, `users/admin.py:41`, `users/models.py:204`, `events/admin.py:204`, `:439`, `configuration/admin.py:326`, `tournaments/admin.py:382`. Deaktivierte Templates unterbrechen den Versand (`emails/services.py:63`). Admin-Staff-/Aktivprüfung und CSRF bleiben erforderlich: [Django 6.0.7 AdminSite](https://github.com/django/django/blob/6.0.7/django/contrib/admin/sites.py), `has_permission`/`admin_view`. Der fehlende implizite Aktionsschutz ist in [Django 6.0.7 ModelAdmin](https://github.com/django/django/blob/6.0.7/django/contrib/admin/options.py), `_filter_actions_by_permissions`, `changelist_view`, `response_action` belegt; lokal dieselben Mechanismen in `/tmp/breakpoint-review-20261007/lib/python3.14/site-packages/django/contrib/admin/options.py:1021`, `:1979`, `:2007`, `:2059` (6.0.9). Die explizit mit `permissions=['delete']` gesicherte Fehlerlöschaktion (`configuration/admin.py:336`) widerlegt die ungeschützten anderen Aktionen nicht.

## Zusätzliche Beobachtungen

- **Deployment-Anleitung für Tunnel unvollständig (Konfiguration, Niedrig):** `README.md:127` beschreibt einen Cloudflare-Tunnel, startet bei `README.md:134` aber ohne Profil. Der `cloudflared`-Service verlangt `tunnel` (`docker-compose.yml:163`); `.env.example` setzt kein `COMPOSE_PROFILES`. Ohne extern gesetztes Profil startet diese Anleitung den Tunnel nicht. Dies ist ein zusätzlicher Dokumentations-/Betriebsbefund, keine weitere Vertrauensheader-Schutzmaßnahme.


## Umsetzung am 11. Oktober 2026

Urteile beziehen sich auf den Code vor dieser Umsetzung. Historische Verifikationsblöcke bleiben erhalten.

| Finding | Urteil | Umsetzung / Begründung |
| --- | --- | --- |
| PROJECT-01 | bestätigt | Öffentliche HTTP-/HTTPS-Eingänge überschreiben IP-/Protokollheader; Cloudflare-Metadaten nur am nicht veröffentlichten internen Port 8080. Tunnel-Anleitungen angepasst; bestehende Cloudflare-Origin-URL auf nginx:8080 umstellen. |
| PROJECT-02 | bestätigt | Bootstrap startet Profil vps. Certbot-Deploy-Hook signalisiert Renewal im gemeinsamen Volume; Nginx-Watcher prüft und lädt die Konfiguration innerhalb von 30 Sekunden neu. |
| PROJECT-03 | bestätigt | Bootstrap prüft Certbot-Renewal-Datei, vollständige PEMs, Gültigkeit, Domain, Aussteller und passenden Schlüssel. Fallbacks werden neu ausgestellt; bestehende Certbot-Lineages bleiben erhalten. |
| PROJECT-04 | bestätigt | Alle eigenen Admin-Aktionen inventarisiert: schreibende Aktionen verlangen change, Klonen add, CSV-Export view. Diese appübergreifenden Dekoratoränderungen gehören zum Projektbefund. |

**Prüfungen:** 4 Regressionstests erfolgreich (Admin-Aktionsfilter und Bootstrap inkl. Fallback/Lineage/Fehlerpfad); Django system check ohne Fehler; docker compose config --quiet und Shell-Syntaxprüfungen erfolgreich.

Zusatzbeobachtung umgesetzt: README-Tunnelstart aktiviert --profile tunnel. Kein echter ACME-Aufruf oder laufender Nginx-/Cloudflare-Test; externe Firewall/Cloudflare-Konfiguration bleibt Betriebsverantwortung.
