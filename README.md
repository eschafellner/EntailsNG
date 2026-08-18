<p align="center">
  <img src="static/images/entailsng-logo.png" alt="EntailsNG Logo" width="650">
</p>

# 🚀 EntailsNG – LAN Event Management CMS (Next Generation)

Willkommen bei **EntailsNG**, der modernen Neuauflage des LAN-Party-Managementsystems für Community-Treffen, Esports-Events und LAN-Partys mit bis zu 1.000 Gästen!

Dieses Repository wurde so vorbereitet, dass auch **weniger IT-affine Kolleginnen und Kollegen** den aktuellen MVP-Stand in weniger als einer Minute installieren, testen und präsentieren können.

---

## ✨ Neue Highlights & Features im MVP

* 🎨 **System-Individualisierbarkeit & Preset Themes:**
  - Vordefinierte Farb-Themes (*Warm Amber*, *Cyberpunk Neon*, *Slate Blue*, *Emerald Gaming*) oder eigene Custom-Farben.
  - Logo-Upload (PNG, SVG, WebP) für flexibles Branding.
  - Rechtstexte (Impressum & Datenschutz) direkt im Backend pflegbar.
  - Benutzerdefiniertes CSS per Backend injizierbar.
* 📏 **Globales UI-Skalierungssystem (`UIScale`):**
  - Einheitliche Steuerung aller Schriftgrößen, Abstände, Buttons, Formulare & Cards im gesamten Frontend.
  - Stufen im Backend einstellbar: *Sehr klein*, *Klein*, *Mittel (Default)*, *Groß*, *Sehr groß*.
* 📱 **Mobile Responsive & Mobile Top-Header Bar:**
  - Sticky Top-Header auf Mobilgeräten (< 860px) inkl. App-Style Bottom-Navigation.
* 🎟️ **Erweiterter Event-Ende-Status (`expired_ticket_mode`):**
  - **Modus "Ticket abgenutzt":** Das Ticket bleibt mit entwertetem Look (`BEENDET` Stempel, Sepia/Rot-Design) als Erinnerung sichtbar.
  - **Modus "Event beendet":** Das Ticket blendet sich bei Überschreitung des Enddatums automatisch aus.
* 🌐 **100% Backend-Übersetzbar (`SystemTranslation`):**
  - Sämtliche Texte im Frontend können ohne Code-Änderungen über den Admin-Bereich verwaltet werden.

---

## 💡 Warum eine virtuelle Umgebung (`.venv`) sinnvoll ist


Eine **virtuelle Umgebung** (Virtual Environment) erstellt einen isolierten "Sandkasten" für Python. Das bietet folgende Vorteile:

* 🛡️ **Keine Konflikte:** Alle benötigten Bibliotheken (Django, TinyMCE etc.) werden nur in diesen Projektordner installiert, ohne das globale Betriebssystem zu verändern.
* 🔄 **Saubere Installation:** Sollte etwas schiefgehen, kann der Ordner `.venv` einfach gelöscht und mit einem Befehl neu angelegt werden.
* 📦 **Identische Umgebung:** Alle Entwickler und Tester arbeiten exakt mit denselben Paketversionen.

---

## ⚡ Einrichtungsanleitung (Nach Betriebssystem aufgeteilt)

### 🐧 Für Linux-User (Fedora / Ubuntu / Debian)

#### Option 1: Automatisch (1-Klick Setup)
Öffne ein Terminal im Projektordner und führe aus:
```bash
./install.sh          # Saubere Installation (ohne Testdaten für Produktion)
# ODER:
./install.sh --demo   # Installation mit Test-Events & Demo-Benutzern

./start.sh            # Server starten
```

#### Option 2: Manuell im Terminal
```bash
# 1. Virtuelle Umgebung anlegen & aktivieren
python3 -m venv .venv
source .venv/bin/activate

# 2. Abhängigkeiten installieren
pip install -r requirements.txt

# 3. Datenbank strukturieren, System-Keys initialisieren & Server starten
python manage.py migrate
python manage.py seed_translations
python manage.py seed_features
# Optional: python manage.py loaddata initial_data.json  (nur für Demo-Daten)
python manage.py runserver
```

---

### 🪟 Für Windows-User (PowerShell / Eingabeaufforderung)

#### Manuelle Einrichtung in der PowerShell:
```powershell
# 1. Virtuelle Umgebung anlegen
python -m venv .venv

# 2. Virtuelle Umgebung aktivieren
.venv\Scripts\Activate.ps1
# (Falls Eingabeaufforderung / CMD genutzt wird: .venv\Scripts\activate.bat)

# 3. Abhängigkeiten installieren
pip install -r requirements.txt

# 4. Datenbank strukturieren & Server starten
python manage.py migrate
python manage.py seed_translations
python manage.py seed_features
# Optional für Demo-Daten: python manage.py loaddata initial_data.json
python manage.py runserver
```

---

## 🌐 Aufrufen der Seiten im Web-Browser

Sobald der Server gestartet ist, öffne deinen Internet-Browser (z. B. Chrome, Firefox, Edge oder Safari) und rufe folgende Links auf:

| Bereich | Web-Adresse (URL) | Beschreibung |
| :--- | :--- | :--- |
| **🌐 Hauptseite / Dashboard** | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) | Hauptübersicht mit aktuellem Event, Ticket-Status, News & Saalplan-Vorschau. |
| **🗺️ Interaktiver Sitzplan** | [http://127.0.0.1:8000/seating/](http://127.0.0.1:8000/seating/) | 2D-Saalplan mit Zoom & Verschieben (Performance-optimiert für bis zu 1.000 Plätze). |
| **📱 Helfer Check-in Scanner** | [http://127.0.0.1:8000/checkin/scanner/](http://127.0.0.1:8000/checkin/scanner/) | Vor-Ort Einlass-Tool für Helfer mit Kamera-QR-Scan & Ton-Feedback *(Nur für Mitarbeiter)*. |
| **🛠️ Admin-Verwaltung** | [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/) | Django Verwaltungsoberfläche für Events, Sitzpläne, E-Mail-Konfiguration & User. |

---

## 🐳 Docker & Produktions-Betrieb (Linux-VPS)

EntailsNG ist für den direkten Produktivbetrieb auf einem Linux-VPS mit **Docker Compose**, **PostgreSQL 16**, **Redis 7**, **Nginx Reverse Proxy** und automatisierten **Let's Encrypt TLS-Zertifikaten** vorbereitet.

### 1. DNS-Records anlegen (beim Domain-Registrar)
Vor dem ersten Start müssen folgende DNS-Einträge auf die öffentliche IP-Adresse deines VPS zeigen:

| Typ | Host / Name | Ziel / Wert | Zweck |
| :--- | :--- | :--- | :--- |
| **A** | `@` (oder z. B. `lan`) | `<VPS-IPv4-Adresse>` | Haupt-Domain |
| **A** (optional) | `www` | `<VPS-IPv4-Adresse>` | WWW-Weiterleitung |
| **AAAA** (optional) | `@` (oder z. B. `lan`) | `<VPS-IPv6-Adresse>` | IPv6-Unterstützung |

---

### 2. Konfiguration (`.env`) anlegen

Kopiere die Vorlage `.env.example` nach `.env` und befülle alle Werte:
```bash
cp .env.example .env
```

> ⚠️ **Sicherheitshinweis zur Secret Rotation & Git-Historie:**
> Frühere Test-Commits enthielten Default-Schlüssel im Klartext. Erzeuge für den Live-Betrieb zwingend neue, kryptografisch sichere Passwörter und Schlüssel!

Wichtige Produktions-Variablen:
* **`SECRET_KEY`**: Neuer Zufallsschlüssel (z. B. via `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`).
* **`DEBUG`**: Zwingend `False`.
* **`DOMAIN_NAME`**: Deine Domain (z. B. `lan.meinedomain.de`).
* **`ALLOWED_HOSTS`**: Kommagetrennt (z. B. `lan.meinedomain.de`).
* **`CSRF_TRUSTED_ORIGINS`**: `https://lan.meinedomain.de`.
* **`CERTBOT_EMAIL`**: Deine E-Mail für Let's Encrypt Benachrichtigungen.
* **`DB_PASSWORD`**: Starkes, zufälliges PostgreSQL-Passwort.
* **`EMAIL_HOST`**, **`EMAIL_PORT`**, **`EMAIL_HOST_USER`**, **`EMAIL_HOST_PASSWORD`**: Zugangsdaten deines SMTP-Providers.

---

### 3. Erstinitialisierung & HTTPS-Zertifikate

Führe das mitgelieferte Initialisierungsskript aus, um das Nginx-Dummy-Zertifikat anzulegen, die ACME-Challenge zu durchlaufen und das offizielle Let's Encrypt Zertifikat zu beziehen:
```bash
bash nginx/init-letsencrypt.sh
```

Bei jedem späteren Start oder Update genügt ein einfaches:
```bash
docker compose up -d
```

---

### 4. Administrator-Account sicher anlegen

Nach dem ersten Start kann ein neuer Administrator-Account direkt im Container erstellt werden:
```bash
docker compose exec web python manage.py createsuperuser
```

---

### 5. Deployment-Überprüfung & Diagnose

Prüfe, ob alle Systemchecks und Deploy-Prüfungen ohne Fehler und Warnungen durchlaufen:
```bash
docker compose exec web python manage.py check --deploy
```

Status aller Container und Logs einsehen:
```bash
docker compose ps
docker compose logs -f web
```

---

## 🛑 Server stoppen
```bash
docker compose down
```


