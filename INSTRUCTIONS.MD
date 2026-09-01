# 📖 Schritt-für-Schritt Deployment-Handbuch für EntailsNG

Willkommen beim offiziellen Deployment-Leitfaden für **EntailsNG**!  
Dieses Handbuch führt dich **von Grund auf** durch die Bereitstellung (Deployment) von **EntailsNG** auf einem Linux-Server (z. B. Ubuntu Server auf einem VPS, einem alten Laptop oder einer virtuellen Maschine).

---

## 🧭 Inhaltsverzeichnis
1. [Die Architektur: Wie EntailsNG funktioniert](#-1-die-architektur-wie-entailsng-funktioniert)
2. [Die 3 Bereitstellungswege im Vergleich](#-2-die-3-bereitstellungswege-im-vergleich)
3. [Schritt 1: Server vorbereiten (Einmalig)](#-schritt-1-server-vorbereiten-einmalig)
4. [Schritt 2: Projekt auf den Server holen](#-schritt-2-projekt-auf-den-server-holen)
5. [Schritt 3: Konfigurationsdatei (.env) befüllen](#-schritt-3-konfigurationsdatei-env-befüllen)
6. [Schritt 4A: Bereitstellung über Cloudflare Tunnel (⭐ Empfohlen für Einsteiger & Heimserver)](#-schritt-4a-bereitstellung-über-cloudflare-tunnel-weg-a)
7. [Schritt 4B: Bereitstellung auf Linux-VPS mit Let's Encrypt (Weg B)](#-schritt-4b-bereitstellung-auf-linux-vps-mit-lets-encrypt-weg-b)
8. [Schritt 4C: Lokale Entwicklung & Offline-Nutzung (Weg C)](#-schritt-4c-lokale-entwicklung--offline-nutzung-weg-c)
9. [Schritt 5: Ersteinrichtung im Admin-Dashboard (Checkliste)](#-schritt-5-ersteinrichtung-im-admin-dashboard-checkliste)
10. [Schritt 6: E-Mail-Versand (SMTP) einrichten & testen](#-schritt-6-e-mail-versand-smtp-einrichten--testen)
11. [Schritt 7: Datensicherung (Backup) & Wiederherstellung](#-schritt-7-datensicherung-backup--wiederherstellung)
12. [Schritt 8: Updates einspielen](#-schritt-8-updates-einspielen)
13. [Schritt 9: Troubleshooting – Häufige Fehler & Sofortlösungen](#-schritt-9-troubleshooting--häufige-fehler--sofortlösungen)
14. [Spickzettel: Die wichtigsten Befehle](#-spickzettel-die-wichtigsten-befehle)

---

## 🧱 1. Die Architektur: Wie EntailsNG funktioniert

EntailsNG nutzt **Docker**. Das bedeutet: Du musst keine Datenbanken, Webserver oder Python-Pakete manuell auf deinem Server installieren – alles läuft isoliert in standardisierten Containern:

```mermaid
graph TD
    User["Besucher (Browser)"] -->|HTTPS| Cloudflare["Cloudflare / Let's Encrypt"]
    Cloudflare -->|HTTP| Nginx["Nginx Webserver (Port 80/443)"]
    Nginx -->|Static / Media| StaticFiles["Statische Dateien & Bilder"]
    Nginx -->|App Requests| Django["EntailsNG (Gunicorn / Django)"]
    Django --> Postgres["PostgreSQL Datenbank (Daten & User)"]
    Django --> Redis["Redis Cache (Sitzplan & Sessions)"]
```

* **`web` (Django/Gunicorn):** Das Herzstück der Anwendung.
* **`db` (PostgreSQL):** Sichere Speicherung aller Benutzer, Events, Sitzplätze und Turniere.
* **`redis` (Redis Cache):** Ultraschneller Arbeitsspeicher-Cache für Platzreservierungen und Live-Zähler.
* **`nginx` (Webserver):** Liefert Bilder und CSS aus und leitet Anfragen sicher an Django weiter.
* **`certbot` / `cloudflared`:** Automatische Verschlüsselung (HTTPS / SSL).

---

## ⚖️ 2. Die 3 Bereitstellungswege im Vergleich

| Kriterium | 🟢 Weg A: Cloudflare Tunnel | 🔵 Weg B: Regulärer Linux-VPS | 🟡 Weg C: Lokaler PC / Laptop |
| :--- | :--- | :--- | :--- |
| **Geeignet für** | Heimserver, Mini-PC (z. B. N100/Intel NUC), lokale VM, Laptop | Gemieteter Cloud-Server (Hetzner, Netcup, Strato, DigitalOcean) | Testen & Vorbereitung auf dem eigenen Computer |
| **Portfreigaben im Router** | ❌ **Keine** (Funktioniert hinter Fritz!Box, DS-Lite, CGNAT) | ✔️ Port 80 und 443 müssen offen sein | ❌ Keine |
| **Öffentliche IP nötig?** | ❌ Nein | ✔️ Feste öffentliche IPv4 nötig | ❌ Nein |
| **HTTPS / SSL** | Automatisch via Cloudflare Edge | Automatisch via Let's Encrypt Script | HTTP (Lokal `localhost:8000`) |
| **Sicherheit** | Server-IP bleibt 100% anonym (DDoS-Schutz) | Server-IP ist öffentlich im DNS | Nur lokal erreichbar |

---

## 🛠️ Schritt 1: Server vorbereiten (Einmalig)

Logge dich per SSH auf deinem Linux-Server ein (z. B. Ubuntu Server 22.04 / 24.04 LTS oder Debian 12):

### 1.1 System aktualisieren & Basis-Tools installieren:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ufw docker.io docker-compose-v2
```

### 1.2 Docker-Berechtigungen für deinen Benutzer setzen:
Damit du Docker ohne `sudo` steuern kannst:
```bash
sudo usermod -aG docker $USER
newgrp docker
```
> *(Test: Führe `docker ps` aus. Es sollte eine leere Tabelle ohne Fehlermeldung erscheinen).*

---

## 📥 Schritt 2: Projekt auf den Server holen

Klone das Repository auf deinen Server:

```bash
# In das Zielverzeichnis klonen:
git clone https://github.com/DEIN_BENUTZERNAME/DEIN_REPO.git /opt/entailsng

# In das Verzeichnis wechseln:
cd /opt/entailsng
```

---

## ⚙️ Schritt 3: Konfigurationsdatei (`.env`) befüllen

Kopiere die Vorlage `.env.example` in eine neue `.env`-Datei:

```bash
cp .env.example .env
nano .env
```

### 📋 Alle Einstellungen im Detail erklärt:

#### 1. Sicherheit & Domain
* **`SECRET_KEY`**: Ein langer, zufälliger Sicherheitsschlüssel für Django.  
  👉 **Befehl zum Generieren:**
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(50))"
  ```
* **`FIELD_ENCRYPTION_KEY`**: Ein zweiter, separater Schlüssel zur Verschlüsselung von Passwörtern (z. B. SMTP-Passwort) in der Datenbank.  
  👉 **Befehl zum Generieren:**
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(50))"
  ```
  > [!IMPORTANT]
  > Setze den `FIELD_ENCRYPTION_KEY` einmalig vor dem ersten Start und ändere ihn danach nicht mehr.

* **`DEBUG`**: Im Produktivbetrieb **immer `False`**!
* **`DOMAIN_NAME`**: Deine Domain oder Subdomain (z. B. `lan.meinedomain.de`).
* **`ALLOWED_HOSTS`**: Erlaubte Hostnamen, durch Komma getrennt (z. B. `lan.meinedomain.de,localhost,127.0.0.1`).
* **`CSRF_TRUSTED_ORIGINS`**: Deine Domain mit `https://` (z. B. `https://lan.meinedomain.de`).

#### 2. Datenbank (PostgreSQL)
* **`DB_ENGINE`**: `postgresql`
* **`DB_NAME`**: `entailsng_db` (Name der Datenbank)
* **`DB_USER`**: `entailsng_user` (Benutzername)
* **`DB_PASSWORD`**: Ein starkes, frei erfundenes Passwort (z. B. `MeinGeheimesDBPasswort2026!`).
* **`DB_HOST`**: `db` (Name des Datenbank-Containers – so belassen!)
* **`DB_PORT`**: `5432` (Standard-Port – so belassen!)

#### 3. Speichern in `nano`:
* Drücke `Strg` + `O`, dann `Enter` (Speichern).
* Drücke `Strg` + `X` (Beenden).

---

## 🟢 Schritt 4A: Bereitstellung über Cloudflare Tunnel (Weg A)

*(Die einfachste und sicherste Methode für Heimserver, DSL-Anschlüsse und lokale VMs).*

### 1. Tunnel im Cloudflare Dashboard anlegen:
1. Öffne das [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/) → **Networks** → **Tunnels**.
2. Klicke auf **Add a tunnel** → Wähle **Cloudflared** → Name vergeben (z. B. `entailsng`) → **Save tunnel**.
3. Wähle als Installationsumgebung **Docker**. Kopiere den langen Token (beginnt mit `eyJhIj...`).
4. Öffne deine `.env` auf dem Server (`nano .env`) und trage den Token ein:
   ```env
   CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoi...
   ```
5. Klicke im Cloudflare Dashboard auf **Next** und richte den **Public Hostname** ein:
   * **Subdomain:** z. B. `lan` (oder leer lassen für die Hauptdomain)
   * **Domain:** Wähle deine Domain aus
   * **Type:** `HTTP`
   * **URL:** `nginx:80`
6. Klicke auf **Save hostname**.
7. Stelle unter *Cloudflare Dashboard* → *Deine Domain* → *SSL/TLS* die Verschlüsselung auf **Full** (oder **Full (strict)**).

### 2. Container mit Tunnel starten:
```bash
docker compose --profile tunnel up -d --build
```

Fertig! Deine LAN-Party-Webseite ist jetzt weltweit unter `https://lan.meinedomain.de` erreichbar.

---

## 🔵 Schritt 4B: Bereitstellung auf Linux-VPS mit Let's Encrypt (Weg B)

### 1. DNS A-Record setzen:
Erstelle bei deinem Domainanbieter einen **A-Record**, der auf die öffentliche IP-Adresse deines Servers zeigt:
* `lan.meinedomain.de` $\rightarrow$ `123.45.67.89`

### 2. Firewall konfigurieren:
```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 3. SSL-Zertifikat automatisch ausstellen & Stack starten:
```bash
bash nginx/init-letsencrypt.sh
```
Das Skript erstellt die Zertifikate automatisch, bindet sie ein und startet alle Container.

---

## 🟡 Schritt 4C: Lokale Entwicklung & Offline-Nutzung (Weg C)

Für lokales Testen oder Vor-Ort-Betrieb ohne Internet:

```bash
# 1. Setup ausführen (einmalig)
./install.sh --demo

# 2. Server starten
./start.sh
```
Rufe im Browser auf: `http://127.0.0.1:8000/`

---

## 👤 Schritt 5: Ersteinrichtung im Admin-Dashboard (Checkliste)

Sobald die Container laufen, führe folgende Schritte durch:

### 1. Administrator-Konto erstellen:
```bash
docker compose exec web python manage.py createsuperuser
```
Gib deinen gewünschten Benutzernamen, E-Mail-Adresse und ein Passwort ein.

### 2. Im Admin-Bereich einloggen:
Öffne `https://deine-domain.de/admin/` und melde dich an.

### 3. Checkliste für die Event-Vorbereitung:
- [ ] **Hauptveranstaltung anlegen (`Veranstaltungen`):**
  - Titel, Start- und Endzeitpunkt, max. Teilnehmerzahl und Ticketpreis eintragen.
  - Das Häkchen bei **Ist aktiv** setzen (es kann immer genau eine aktive Hauptveranstaltung geben).
- [ ] **Ticketkategorien anlegen (`Ticket-Kategorien`):**
  - z. B. *Standard Ticket (30,00 €)*, *Clan-Ticket*, *VIP / Sponsor*.
- [ ] **Sitzplan erstellen (`Sitzpläne`):**
  - Klicke auf **Sitzplan-Editor öffnen**, wähle Spalten und Zeilen (z. B. 20x15) und zeichne Tische, Gänge, Bühne und Catering-Bereiche ein.
- [ ] **Zahlungsdaten hinterlegen (`Allgemeine Einstellungen`):**
  - **Kontoinhaber** & **IBAN** eintragen.
  - Dadurch wird für jeden Gast auf dem Dashboard automatisch der **GiroCode / SEPA-QR-Code** für Banking-Apps generiert.
- [ ] **Site Customization (`Webseiten-Anpassungen`):**
  - Eigenes Logo hochladen, Farbschema wählen (*Warm Amber*, *Cyberpunk*, *Slate Blue* etc.).

---

## ✉️ Schritt 6: E-Mail-Versand (SMTP) einrichten & testen

EntailsNG versendet E-Mail-Verifizierungscodes, Buchungsbestätigungen, Tickets und Passwort-Reset-Mails.

### 1. Empfohlene SMTP-Anbieter:
* **Resend** (sehr modern, 3.000 Mails/Monat kostenlos)
* **Brevo / Sendinblue** (300 Mails/Tag kostenlos)
* **Eigener Webhoster** (z. B. Hetzner, Strato, All-Inkl)

### 2. Im Admin-Bereich konfigurieren:
1. Öffne im Django-Admin den Menüpunkt **Allgemeine E-Mail Einstellungen**.
2. Wähle den gewünschten Versandweg:
   - **Eigener SMTP-Server:** Hostname, Port (z. B. `587` mit TLS), Benutzername und Passwort eintragen.
3. Klicke auf **Verbindung testen**.
4. Wenn der Test erfolgreich ist: Schalter **Gäste erhalten E-Mails** aktivieren.

### 3. Diagnose-Tool ausführen:
```bash
# E-Mail-Gesundheitscheck:
docker compose exec web python manage.py email_doctor

# Mit echtem Testversand an deine Adresse:
docker compose exec web python manage.py email_doctor --send-to deine@email.de
```

---

## 💾 Schritt 7: Datensicherung (Backup) & Wiederherstellung

### 1. Backup erstellen (Dauert 5 Sekunden):
```bash
# 1. Datenbank sichern (in Datei mit aktuellem Datum speichern):
docker compose exec -T db pg_dump -U entailsng_user entailsng_db > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Uploads & Konfiguration sichern:
tar -czf media_backup_$(date +%Y%m%d).tar.gz media/ .env
```

### 2. Backup wiederherstellen (Disaster Recovery):
```bash
# Datenbank aus SQL-Datei wiederherstellen:
cat backup_20260901_120000.sql | docker compose exec -T db psql -U entailsng_user entailsng_db
```

---

## 🔄 Schritt 8: Updates einspielen

Wenn es neue Versionen oder Verbesserungen von EntailsNG gibt:

```bash
cd /opt/entailsng

# 1. Neuesten Code abrufen:
git pull

# 2. Container neu bauen & starten (Migrationen laufen automatisch):
docker compose up -d --build
```
> *(Deine Datenbank, hochgeladene Logos und Einstellungen bleiben dabei zu 100% erhalten!)*

---

## 🩺 Schritt 9: Troubleshooting – Häufige Fehler & Sofortlösungen

### ❌ Problem 1: `container entailsng_web is unhealthy`
* **Ursache:** Die Datenbank war beim Start noch nicht ganz bereit oder der Healthcheck hat keine Antwort erhalten.
* **Lösung:** Prüfe die Logs mit:
  ```bash
  docker compose logs -f web
  ```

### ❌ Problem 2: `CSRF verification failed / 403 Forbidden beim Login`
* **Ursache:** Die in `.env` eingetragene URL bei `CSRF_TRUSTED_ORIGINS` stimmt nicht exakt mit der im Browser aufgerufenen Adresse überein.
* **Lösung:** Prüfe in der `.env`:
  ```env
  CSRF_TRUSTED_ORIGINS=https://deine-echte-domain.de
  ```
  *(Achte auf `https://` und eventuelle Subdomains wie `lan.`)*.

### ❌ Problem 3: `E-Mail-Versand schlägt fehl / Port 587 Timeout`
* **Ursache:** Viele Cloud-Hoster (z. B. Hetzner, DigitalOcean) sperren Port 587 für Neukunden standardmäßig gegen Spam.
* **Lösung:** 
  1. Nutze Port `465` mit SSL (`EMAIL_PORT=465`, `EMAIL_USE_SSL=True`).
  2. Oder nutze Resend auf Port `2587`.
  3. Prüfe die Diagnose mit `docker compose exec web python manage.py email_doctor`.

### ❌ Problem 4: `FATAL: password authentication failed for user`
* **Ursache:** Das Passwort in der `.env` wurde nachträglich geändert, aber das bestehende PostgreSQL-Volume enthält noch das alte Passwort.
* **Lösung:** Entweder in der `.env` das alte Passwort wieder eintragen, oder (falls noch keine echten Daten existieren) das Volume zurücksetzen:
  ```bash
  docker compose down -v
  docker compose up -d
  ```

---

## 📋 Spickzettel: Die wichtigsten Befehle

| Was möchtest du tun? | Befehl auf dem Server |
| :--- | :--- |
| **Status aller Container ansehen** | `docker compose ps` |
| **Live-Logs aller Container verfolgen** | `docker compose logs -f` |
| **Nur Web-Logs verfolgen** | `docker compose logs -f web` |
| **Neuen Administrator anlegen** | `docker compose exec web python manage.py createsuperuser` |
| **Django Sicherheitscheck durchführen** | `docker compose exec web python manage.py check --deploy` |
| **E-Mail Versand prüfen** | `docker compose exec web python manage.py email_doctor` |
| **Server neu starten** | `docker compose restart` |
| **Server komplett stoppen** | `docker compose down` |
| **Update durchführen** | `git pull && docker compose up -d --build` |

