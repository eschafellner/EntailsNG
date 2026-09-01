<p align="center">
  <img src="static/images/entailsng-logo.png" alt="EntailsNG Logo" width="650">
</p>

# 🚀 EntailsNG – LAN Event Management CMS (Next Generation)

Willkommen bei **EntailsNG**, der modernen Neuauflage des LAN-Party-Managementsystems für Community-Treffen, Esports-Events und LAN-Partys mit bis zu 1.000 Gästen!

Stack: **Python 3.12+ / Django 6, PostgreSQL 16, Redis 7, Nginx, Gunicorn, WhiteNoise, Pillow**.

---

## ✨ Highlights & Module im Überblick

* 🎟️ **Event- & Ticket-Management:** Registrierungen, dynamische Ticketkategorien, Vorverkaufsfristen & Double-Opt-In E-Mail-Verifizierung.
* 🗺️ **Interaktiver 2D-Sitzplan:** Saalplan mit Zoom, Verschieben & Echtzeit-Reservierung für bis zu 1.000 Plätze.
* 📱 **Helfer Check-in Scanner:** Vor-Ort Einlass-Tool mit Kamera-QR-Scan, akustischem Feedback & Ausweis-Verifikation.
* 🏆 **Turnier- & Clan-Verwaltung:** Single/Double Elimination Brackets, Match-Scoring, Team-Management & Clan-Logos.
* 📰 **News & Ankündigungen:** Newsfeed mit Markdown/Rich-Text und Benachrichtigungen.
* 🎨 **Theme-Engine & UI-Skalierung:** Farbpaletten (*Warm Amber*, *Cyberpunk*, *Slate Blue*), Logo-Upload, Global `UIScale` und 100% Backend-übersetzbare Systemtexte.

---

## ⚡ Schnellstart für lokale Entwicklung (Dev-Setup)

### 🐧 Linux (Fedora / Ubuntu / Debian)

EntailsNG unterstützt sowohl **Podman** (Standard auf Fedora/RHEL) als auch **Docker** (Ubuntu/Debian):

```bash
# 1. Installation (einmalig)
./install.sh --demo    # Richtet .venv ein, startet DB & lädt Testdaten (sadmin/adminpwd)

# 2. Server starten
./start.sh             # Startet den Django Dev-Server & prüft automatisch PostgreSQL/Redis
```

#### 🐘 Lokale Datenbanken mit Podman / Docker steuern:
Falls du die Datenbanken manuell im Hintergrund starten oder stoppen möchtest:

```bash
# Für Fedora / Podman:
systemctl --user enable --now podman.socket   # Einmalig aktivieren
podman compose up -d db redis

# Für Ubuntu / Docker:
docker compose up -d db redis

# Dev-Server starten:
source .venv/bin/activate
python manage.py runserver
```

---

### 🪟 Windows (PowerShell)

```powershell
# 1. Virtuelle Umgebung anlegen & aktivieren
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Abhängigkeiten installieren
pip install -r requirements.txt

# 3. Datenbank strukturieren & Seeds ausführen
python manage.py migrate
python manage.py seed_translations
python manage.py seed_features
python manage.py seed_email_templates

# 4. Server starten
python manage.py runserver
```

---

## 🌐 Lokale Web-Adressen

Sobald der Server läuft, erreichst du die Anwendung unter:

| Bereich | Web-Adresse (URL) | Beschreibung |
| :--- | :--- | :--- |
| **🌐 Hauptseite / Dashboard** | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) | Hauptübersicht mit aktuellem Event, Ticket-Status & News. |
| **🗺️ Interaktiver Sitzplan** | [http://127.0.0.1:8000/seating/](http://127.0.0.1:8000/seating/) | 2D-Saalplan mit Zoom & Sitzplatzwahl. |
| **📱 Helfer Check-in Scanner** | [http://127.0.0.1:8000/checkin/scanner/](http://127.0.0.1:8000/checkin/scanner/) | Vor-Ort Einlass-Tool für Helfer mit QR-Scanner *(Staff-Login nötig)*. |
| **🛠️ Admin-Verwaltung** | [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/) | Django Verwaltungsoberfläche (Standard-Admin: `sadmin` / `adminpwd`). |

---

## 🐳 Live-Deployment (Produktion / VM / VPS)

EntailsNG ist vollständig containerisiert und kann wahlweise über einen **Linux-VPS mit Let's Encrypt** oder über einen **Cloudflare Tunnel (Heimserver / VM)** betrieben werden.

### 1. Konfiguration (`.env`) anlegen

Kopiere `.env.example` nach `.env` und befülle alle Werte:
```bash
cp .env.example .env
nano .env
```

Wichtige Parameter:
* **`SECRET_KEY`**: Neuer kryptografisch sicherer Schlüssel (`python3 -c "import secrets; print(secrets.token_urlsafe(50))"`).
* **`DEBUG`**: `False`.
* **`DOMAIN_NAME`**: Deine Domain (z. B. `lan.meinedomain.de`).
* **`ALLOWED_HOSTS`**: `lan.meinedomain.de,localhost,127.0.0.1`.
* **`CSRF_TRUSTED_ORIGINS`**: `https://lan.meinedomain.de`.
* **`DB_PASSWORD`**: Starkes PostgreSQL-Passwort.
* **`EMAIL_HOST`**, **`EMAIL_PORT`**, **`EMAIL_HOST_USER`**, **`EMAIL_HOST_PASSWORD`**: SMTP-Zugangsdaten.

---

### 2. Variante A: Deployment über Cloudflare Tunnel (Empfohlen für VM / Heimserver)

1. Im [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/) einen Tunnel erstellen.
2. In der `.env` den `CLOUDFLARE_TUNNEL_TOKEN` eintragen.
3. Public Hostname im Cloudflare Dashboard auf `HTTP` -> `nginx:80` setzen.
4. Container starten:
   ```bash
   docker compose up -d --build
   # (oder: podman compose up -d --build)
   ```

---

### 3. Variante B: Deployment auf Linux-VPS mit Let's Encrypt

1. DNS A-Record der Domain auf die öffentliche IPv4 des VPS setzen.
2. SSL-Bootstrap-Skript ausführen:
   ```bash
   bash nginx/init-letsencrypt.sh
   ```

---

### 4. Erste Schritte nach dem Start (Superuser & Checks)

```bash
# Eigenen Superuser erstellen
docker compose exec web python manage.py createsuperuser

# System- & Sicherheitscheck ausführen (sollte 0 Fehler liefern)
docker compose exec web python manage.py check --deploy

# E-Mail-Konfiguration & Zustellbarkeit prüfen
docker compose exec web python manage.py email_doctor

# Container-Status prüfen
docker compose ps
```


---

## ✉️ E-Mail-Versand einrichten

EntailsNG versendet Registrierungsbestätigungen, Tickets und Passwort-Reset-Mails.

1. **Versandwege:**
   - **Vom Server vorgegeben (`.env`):** Nutzt die in der `.env` definierten `EMAIL_*`-Werte.
   - **Eigener SMTP-Server (Backend):** SMTP-Zugangsdaten werden direkt im Admin-Bereich unter *Allgemeine E-Mail Einstellungen* hinterlegt und verschlüsselt gespeichert.
2. **Einrichtung:**
   - Öffne im Django-Admin den Punkt **Allgemeine E-Mail Einstellungen**.
   - Wähle den gewünschten **Versandweg** und trage deine **Absenderadresse** ein (die Absenderdomain muss bei deinem Mailanbieter verifiziert sein!).
   - Klicke auf **Verbindung testen**, um die Erreichbarkeit zu prüfen.
   - Aktiviere anschließend den Schalter **Gäste erhalten E-Mails**.
3. **Diagnose-Befehl:**
   ```bash
   docker compose exec web python manage.py email_doctor
   # Optional mit echtem Testversand:
   docker compose exec web python manage.py email_doctor --send-to orga@meinedomain.de
   ```
4. **Sicherheitshinweis:**
   - `FIELD_ENCRYPTION_KEY` in der `.env` einmalig generieren und beibehalten, damit in der Datenbank gespeicherte Passwörter dauerhaft entschlüsselbar bleiben.

---

## 🛑 Container stoppen

```bash
docker compose down
# (oder: podman compose down)
```
