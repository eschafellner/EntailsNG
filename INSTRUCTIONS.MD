# 📖 Schritt-für-Schritt Deployment-Handbuch für EntailsNG

Dieses Handbuch führt dich **von Grund auf** durch die Bereitstellung (Deployment) von **EntailsNG** auf einem Linux-Server (z. B. Ubuntu Server auf einem VPS, einem alten Laptop oder einer virtuellen Maschine).

---

## 🧭 Inhaltsverzeichnis
1. [Die 2 Deployment-Arten im Vergleich (Weg A vs. Weg B)](#-1-die-2-deployment-arten-im-vergleich)
2. [Schritt 1: Voraussetzungen auf dem Server installieren](#-schritt-1-voraussetzungen-auf-dem-server-installieren)
3. [Schritt 2: Projekt auf den Server holen](#-schritt-2-projekt-auf-den-server-holen)
4. [Schritt 3: Die Konfiguration (.env) – Jede Variable im Detail erklärt](#-schritt-3-die-konfigurationsdatei-env--jede-variable-erklärt)
5. [Schritt 4A: Deployment über Cloudflare Tunnel (Empfohlen für Heimserver & VMs)](#-schritt-4a-deployment-über-cloudflare-tunnel-weg-a)
6. [Schritt 4B: Reguläres Deployment auf Linux-VPS mit Let's Encrypt (Weg B)](#-schritt-4b-reguläres-deployment-auf-linux-vps-mit-lets-encrypt-weg-b)
7. [Schritt 5: Administrator-Account anlegen & Erster Login](#-schritt-5-administrator-account-anlegen--erster-login)
8. [Schritt 6: Troubleshooting – Häufige Fehler & schnelle Lösungen](#-schritt-6-troubleshooting--häufige-fehler--lösungen)
9. [Spickzettel: Die wichtigsten Befehle für den Alltag](#-spickzettel-wichtige-befehle-im-alltag)

---

## ⚖️ 1. Die 2 Deployment-Arten im Vergleich

Bevor du startest, wähle den Weg, der zu deiner Umgebung passt:

| Kriterium | 🟢 Weg A: Cloudflare Tunnel | 🔵 Weg B: Regulärer Linux-VPS |
| :--- | :--- | :--- |
| **Ideale Umgebung** | Heimserver, lokale VM, alter Laptop zu Hause, Hetzner/Netcup mit Cloudflare DNS | Eigener Linux-VPS mit fester öffentlicher IPv4-Adresse (z. B. DigitalOcean, Linode, Hetzner Cloud) |
| **Port-Freigaben im Router** | ❌ **Keine** (Funktioniert hinter Fritz!Box, DS-Lite, CGNAT) | ✔️ Port 80 und 443 müssen öffentlich erreichbar sein |
| **HTTPS / SSL** | Übernimmt Cloudflare automatisch an der Edge | Erstellt Let's Encrypt Zertifikate lokal auf dem Server |
| **Domain-Verwaltung** | Domain muss bei Cloudflare verwaltet werden | Beliebiger Domain-Registrar (z. B. Namecheap, Strato, IONOS) |
| **Sicherheit** | Echte Server-IP bleibt 100% verborgen (DDoS-Schutz) | Server-IP ist über DNS öffentlich sichtbar |

---

## 🛠️ Schritt 1: Voraussetzungen auf dem Server installieren

Logge dich per SSH oder direkt auf der Server-Konsole ein (als normaler Benutzer mit `sudo`-Rechten).

### 1.1 System aktualisieren & Basis-Tools installieren:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ufw docker.io docker-compose-v2
```

### 1.2 Docker-Berechtigungen für deinen Benutzer setzen:
Damit du Docker-Befehle ohne ständiges `sudo` ausführen kannst:
```bash
sudo usermod -aG docker $USER
newgrp docker
```
*(Test: Der Befehl `docker ps` sollte nun eine leere Tabelle ohne Fehlermeldung ausgeben).*

---

## 📥 Schritt 2: Projekt auf den Server holen

Klone dein Repository in das Verzeichnis `/opt/entailsng` (oder in dein Benutzerverzeichnis `~/entails-ng`):

```bash
# Projekt klonen (Ersetze die URL mit deinem GitHub-Repository):
git clone https://github.com/DEIN_BENUTZERNAME/DEIN_REPO.git /opt/entailsng

# In das Verzeichnis wechseln:
cd /opt/entailsng
```

---

## ⚙️ Schritt 3: Die Konfigurationsdatei (`.env`) – Jede Variable erklärt

Erstelle deine persönliche Konfigurationsdatei aus der Vorlage:
```bash
cp .env.example .env
nano .env
```

### 📋 Detaillierte Erklärung aller Variablen in der `.env`:

| Variable | Beispiel-Wert | Woher kommt der Wert? / Was bedeutet er? |
| :--- | :--- | :--- |
| `SECRET_KEY` | `dGhpcy1pcy1hLXNhbXBsZS1zZWNyZXQta2V5` | **Wichtig:** Ein geheimer Zufallsschlüssel für Django. Generiere ihn auf der Konsole mit:<br>`python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DEBUG` | `False` | Im Live-Betrieb **immer `False`**! Schützt vor der Anzeige interner Fehlerseiten und Zugangsdaten im Browser. |
| `DOMAIN_NAME` | `demo.entails-ng.com` | Deine vollständige Domain oder Subdomain, unter der das System erreichbar sein soll. |
| `ALLOWED_HOSTS` | `demo.entails-ng.com,localhost,127.0.0.1` | Schutz vor Host-Header-Angriffen. Trage deine Domain sowie `localhost,127.0.0.1` (durch Komma getrennt) ein. |
| `CSRF_TRUSTED_ORIGINS` | `https://demo.entails-ng.com` | **Wichtig:** Exakt `https://` gefolgt von deiner Domain. Verhindert den Fehler *„CSRF-Verifizierung fehlgeschlagen“* beim Login. |
| `CLOUDFLARE_TUNNEL_TOKEN` | `eyJhIjoi...` | *(Nur für Weg A)*: Der Token aus dem Cloudflare Zero Trust Dashboard. |
| `CERTBOT_EMAIL` | `orga@deinedomain.de` | *(Nur für Weg B)*: Deine E-Mail-Adresse für Ablaufwarnungen von Let's Encrypt. |
| `DB_ENGINE` | `postgresql` | Immer `postgresql` für den Produktionsbetrieb. |
| `DB_NAME` | `entailsng_db` | Name der internen PostgreSQL-Datenbank (frei wählbar). |
| `DB_USER` | `entailsng_user` | Datenbank-Benutzername (frei wählbar). |
| `DB_PASSWORD` | `einSicheresDBPasswort123!` | Ein starkes, zufälliges Passwort für die interne Datenbank. |
| `DB_HOST` | `db` | Der Name des Datenbank-Containers in Docker (immer `db` lassen). |
| `DB_PORT` | `5432` | Standard-PostgreSQL-Port (immer `5432` lassen). |
| `REDIS_URL` | `redis://redis:6379/1` | Verbindung zum internen Redis-Cache (immer so belassen). |
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` | E-Mail-Treiber (immer so belassen). |
| `EMAIL_HOST` | `smtp.sendgrid.net` *(oder dein Anbieter)* | Der SMTP-Server deines E-Mail-Providers (z. B. Strato, Hetzner, Gmail, Sendgrid). |
| `EMAIL_PORT` | `587` | Port des SMTP-Servers (meist `587` bei TLS oder `465` bei SSL). |
| `EMAIL_HOST_USER` | `apikey` *(oder dein Mail-Login)* | Dein SMTP-Benutzername. |
| `EMAIL_HOST_PASSWORD` | `dein-smtp-passwort` | Dein SMTP-Passwort oder API-Schlüssel. |
| `EMAIL_USE_TLS` | `True` | `True` bei Port 587, `False` bei Port 465. |
| `EMAIL_USE_SSL` | `False` | `True` bei Port 465, `False` bei Port 587. |
| `DEFAULT_FROM_EMAIL` | `noreply@deinedomain.de` | Die Absender-Adresse, die Empfänger in ihren E-Mails sehen. |
| `SERVER_EMAIL` | `noreply@deinedomain.de` | Absender-Adresse für interne System-Fehlermeldungen. |

*(Speichern in `nano`: `Strg` + `O` → `Enter`, Schließen: `Strg` + `X`).*

---

## 🟢 Schritt 4A: Deployment über Cloudflare Tunnel (Weg A)

*(Wenn du einen regulären VPS mit Let's Encrypt nutzt, überspringe diesen Schritt und gehe zu Schritt 4B).*

### 4A.1 Tunnel im Cloudflare Dashboard anlegen:
1. Öffne das [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/) → **Networks** → **Tunnels**.
2. Klicke auf **Add a tunnel** → Wähle **Cloudflared** → Vergib einen Namen (z. B. `entailsng-prod`) → Klicke auf **Save tunnel**.
3. Wähle als Installationsumgebung **Docker** aus. Kopiere den langen Token aus dem angezeigten Befehl (beginnt mit `eyJhIj...`).
4. Füge diesen Token in deine `.env`-Datei auf dem Server bei `CLOUDFLARE_TUNNEL_TOKEN=...` ein.
5. Klicke im Cloudflare Dashboard auf **Next** und konfiguriere den **Public Hostname**:
   - **Subdomain:** z. B. `demo` (oder leer lassen für Hauptdomain)
   - **Domain:** Wähle deine Domain aus dem Dropdown (z. B. `entails-ng.com`)
   - **Type:** `HTTP`
   - **URL:** `nginx:80`
6. Klicke unten rechts auf **Save hostname**.

### 4A.2 Nginx-Konfiguration & Docker Compose anpassen:
Für den Cloudflare Tunnel übernimmt Cloudflare das HTTPS-Zertifikat. Nginx muss intern nur auf Port 80 lauschen.

1. **`nginx/templates/default.conf.template` anpassen:**
   ```bash
   nano nginx/templates/default.conf.template
   ```
   Ersetze den Inhalt durch:
   ```nginx
   upstream django {
       server web:8000;
   }

   server {
       listen 80;
       listen [::]:80;
       server_name _;

       client_max_body_size 25M;

       location /static/ {
           alias /app/staticfiles/;
           expires 30d;
           add_header Cache-Control "public, no-transform";
           gzip_static on;
       }

       location /media/ {
           alias /app/media/;
           expires 7d;
           add_header Cache-Control "public, no-transform";
       }

       location / {
           proxy_pass http://django;
           proxy_set_header Host $http_host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto https;
           proxy_redirect off;
           proxy_connect_timeout 60s;
           proxy_read_timeout 60s;
       }
   }
   ```

2. **In `docker-compose.yml` den `cloudflared`-Container aktivieren:**
   Stelle sicher, dass am Ende der `docker-compose.yml` der `cloudflared`-Block aktiv ist:
   ```yaml
     cloudflared:
       image: cloudflare/cloudflared:latest
       container_name: entailsng_cloudflared
       restart: unless-stopped
       environment:
         - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
       command: tunnel --no-autoupdate run
       depends_on:
         - nginx
   ```

3. **In Cloudflare Dashboard SSL auf "Full" stellen:**
   Gehe im normalen Cloudflare Dashboard auf deine Domain → **SSL/TLS** → **Overview** → Stelle auf **Full** (oder **Full (strict)**).

4. **Container starten:**
   ```bash
   docker compose up -d --build
   ```

---

## 🔵 Schritt 4B: Reguläres Deployment auf Linux-VPS mit Let's Encrypt (Weg B)

### 4B.1 DNS A-Record setzen:
Gehe zu deinem Domain-Registrar und erstelle einen **A-Record**:
- **Name / Host:** `@` (oder deine Subdomain z. B. `lan`)
- **Ziel / IP:** Die öffentliche IPv4-Adresse deines Linux-VPS.

### 4B.2 SSL-Zertifikat automatisch ausstellen & starten:
Führe auf dem Server das vorbereitete Initialisierungsskript aus:
```bash
bash nginx/init-letsencrypt.sh
```
Das Skript erstellt ein temporäres Zertifikat, startet Nginx, holt das echte Zertifikat von Let's Encrypt und startet den gesamten Stack inklusive automatischer Zertifikatsverlängerung.

---

## 👤 Schritt 5: Administrator-Account anlegen & Erster Login

Sobald die Container laufen, lege deinen ersten Administrator-Account an:

```bash
docker compose exec web python manage.py createsuperuser
```
Gib Benutzername, E-Mail-Adresse und ein sicheres Passwort ein.

### 🌐 System im Browser aufrufen:
Öffne deinen Web-Browser und rufe deine Domain auf:
- **Frontend / Dashboard:** `https://demo.entails-ng.com/`
- **Admin-Bereich:** `https://demo.entails-ng.com/admin/`

---

## 🩺 Schritt 6: Troubleshooting – Häufige Fehler & Lösungen

### ❌ Problem 1: `container entailsng_web is unhealthy`
**Ursache:** Der interne Healthcheck wurde durch einen HTTPS-Redirect blockiert oder die Datenbank war noch nicht bereit.  
**Lösung:** Prüfe die Logs mit `docker compose logs web`. Stelle sicher, dass in `docker-compose.yml` beim `web`-Service der Header `-H 'X-Forwarded-Proto: https'` im Healthcheck steht.

### ❌ Problem 2: `FATAL: Passwort-Authentifizierung für Benutzer fehlgeschlagen`
**Ursache:** Das PostgreSQL-Volume wurde zuvor mit einem anderen Passwort initialisiert als aktuell in der `.env` steht.  
**Lösung:** Lösche das alte Volume und starte frisch:
```bash
docker compose down -v
docker compose up -d
```

### ❌ Problem 3: `CSRF verification failed / 403 Forbidden beim Login`
**Ursache:** Die Domain in `CSRF_TRUSTED_ORIGINS` stimmt nicht exakt mit der im Browser aufgerufenen URL überein.  
**Lösung:** In der `.env` prüfen: `CSRF_TRUSTED_ORIGINS=https://deine-echte-domain.de` (inklusive `https://`).

### ❌ Problem 4: `DNS_PROBE_FINISHED_NXDOMAIN` (Cloudflare Tunnel)
**Ursache:** Der Public Hostname im Cloudflare Zero Trust Dashboard wurde noch nicht gespeichert oder die Domain hat einen Tippfehler.  
**Lösung:** Zero Trust Dashboard → Tunnels → Configure → Tab **Public Hostnames** prüfen und auf *Save hostname* klicken.

---

## 📋 Spickzettel: Wichtige Befehle im Alltag

| Was möchtest du tun? | Befehl auf dem Server |
| :--- | :--- |
| **Status aller Container prüfen** | `docker compose ps` |
| **Live-Logs aller Container ansehen** | `docker compose logs -f` |
| **Logs nur vom Django-Webserver ansehen** | `docker compose logs -f web` |
| **Django System- & Sicherheitscheck durchführen** | `docker compose exec web python manage.py check --deploy` |
| **Stack neu starten** | `docker compose restart` |
| **Stack komplett stoppen (Daten bleiben erhalten)** | `docker compose down` |
| **Neuen Code nach Git Pull deployen** | `git pull && docker compose up -d --build` |
