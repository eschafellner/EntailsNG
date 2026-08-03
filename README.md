<p align="center">
  <img src="static/images/entailsng-logo.png" alt="EntailsNG Logo" width="650">
</p>

# 🚀 EntailsNG – LAN Event Management CMS (Next Generation)

Willkommen bei **EntailsNG**, der modernen Neuauflage des LAN-Party-Managementsystems für Community-Treffen, Esports-Events und LAN-Partys mit bis zu 1.000 Gästen!

Dieses Repository wurde so vorbereitet, dass auch **weniger IT-affine Kolleginnen und Kollegen** den aktuellen MVP-Stand in weniger als einer Minute installieren, testen und präsentieren können.

---

## 💡 Warum eine virtuelle Umgebung (`.venv`) sinnvoll ist

Eine **virtuelle Umgebung** (Virtual Environment) erstellt einen isolierten "Sandkasten" für Python. Das bietet folgende Vorteile:

* 🛡️ **Keine Konflikte:** Alle benötigten Bibliotheken (Django, TinyMCE etc.) werden nur in diesen Projektordner installiert, ohne das globale Betriebssystem zu verändern.
* 🔄 **Saubere Installation:** Sollte etwas schiefgehen, kann der Ordner `.venv` einfach gelöscht und mit einem Befehl neu angelegt werden.
* 📦 **Identische Umgebung:** Alle Entwickler und Tester arbeiten exakt mit denselben Paketversionen.

---

## ⚡ Einrichtungsanleitung (Nach Betriebssystem aufgeteilt)

### 🐧 Für Linux-User (Fedora / Ubuntu / Debian)

#### Option 1: Automatisch (1-Klick)
Öffne ein Terminal im Projektordner und führe aus:
```bash
./install.sh   # Einmalige Einrichtung
./start.sh     # Server starten
```

#### Option 2: Manuell im Terminal
```bash
# 1. Virtuelle Umgebung anlegen & aktivieren
python3 -m venv .venv
source .venv/bin/activate

# 2. Abhängigkeiten installieren
pip install -r requirements.txt

# 3. Datenbank strukturieren & Server starten
python manage.py migrate
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

## 🔑 Voreingestellte Test-Zugänge

Für Testzwecke wurden bereits vorgefertigte Benutzerkonten angelegt:

* **Administrator / Helfer Account**:
  * **Benutzername:** `sadmin`
  * **Passwort:** `adminpwd`
  * *(Besitzt Mitarbeiter-Rechte für den Helfer-Scanner und den Admin-Bereich)*

* **Normaler Teilnehmer / Spieler Account**:
  * **Benutzername:** `gamer1`
  * **Passwort:** `guestpwd`

---

## 🐘 Datenbank-Betrieb (PostgreSQL)

EntailsNG ist für den **PostgreSQL-Betrieb** ausgelegt.

### PostgreSQL Datenbank starten:
- **Über Docker / Podman**:
  ```bash
  docker-compose up -d
  ```
- **Nativ auf Linux (Fedora)**:
  ```bash
  sudo systemctl start postgresql
  ```

---

## 🛑 Server beenden
Um den Server wieder zu beenden, gehe zurück in das Terminal-Fenster und drücke gleichzeitig die Tasten **`[STRG]` + `[C]`**.
