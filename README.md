# 🚀 EntailsNG – Event & LAN-Party Management System

Willkommen bei **EntailsNG**, der modernen Neuauflage des LAN-Party-Managementsystems für Community-Treffen, Esports-Events und LAN-Partys mit bis zu 1.000 Gästen!

Dieses Repository wurde so vorbereitet, dass auch **weniger IT-affine Kolleginnen und Kollegen** den aktuellen MVP-Stand in weniger als einer Minute installieren, testen und präsentieren können.

---

## ⚡ Schnellstartanleitung (in 2 Schritten)

### 1. Schritt: Installation ausführen
Öffne ein Terminal in diesem Ordner und führe folgenden Befehl aus:

```bash
./install.sh
```
*Das Skript richtet automatisch die isolierte Python-Umgebung ein, installiert alle benötigten Pakete und bereitet die Test-Datenbank vor.*

---

### 2. Schritt: Server starten
Führe danach einfach folgendes Startskript aus:

```bash
./start.sh
```

Fertig! Der Server läuft nun.

---

## 🌐 Aufrufen der Seiten im Web-Browser

Sobald der Server gestartet ist, öffne deinen Internet-Browser (z. B. Chrome, Firefox, Edge oder Safari) und rufe folgende Links auf:

| Bereich | Web-Adresse (URL) | Beschreibung |
| :--- | :--- | :--- |
| **🌐 Hauptseite / Dashboard** | [http://127.0.0.1:8000/](http://127.0.0.1:8000/) | Hauptübersicht mit aktuellem Event, Ticket-Status, News & Saalplan-Vorschau. |
| **🗺️ Interaktiver Sitzplan** | [http://127.0.0.1:8000/seating/](http://127.0.0.1:8000/seating/) | 2D-Saalplan mit Zoom & Verschieben (Performance-optimiert für bis zu 1.000 Plätze). |
| **📱 Helfer Check-in Scanner** | [http://127.0.0.1:8000/checkin/scanner/](http://127.0.0.1:8000/checkin/scanner/) | Vor-Ort Einlass-Tool für Helfer mit Kamera-QR-Scan & Ton-Feedback *(Nur für Mitarbeiter)*. |
| **🛠️ Admin-Verwaltung** | [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/) | Django Verwaltungsoberfläche für Events, Sitzpläne, Freigaben & User. |

---

## 🔑 Voreingestellte Test-Zugänge

Für Testzwecke wurden bereits vorgefertigte Benutzerkonten angelegt:

* **Administrator / Helfer Account**:
  * **Benutzername:** `admin`
  * **Passwort:** `password`
  * *(Besitzt Mitarbeiter-Rechte für den Helfer-Scanner und den Admin-Bereich)*

* **Normaler Teilnehmer / Spieler Account**:
  * **Benutzername:** `gamer1`
  * **Passwort:** `password`

---

## 🛑 Server beenden
Um den Server wieder zu beenden, gehe zurück in das Terminal-Fenster und drücke gleichzeitig die Tasten **`[STRG]` + `[C]`**.

---

## 🐘 Für Fortgeschrittene: PostgreSQL Datenbank nutzen (Produktivbetrieb)

Der Testbetrieb startet standardmäßig mit einer SQLite-Datenbank. Wenn du mit einer produktiven PostgreSQL-Datenbank testen möchtest:

1. Starte PostgreSQL via Docker/Podman:
   ```bash
   docker-compose up -d
   ```
2. Importiere die Daten in PostgreSQL:
   ```bash
   python scripts/setup_postgres.py
   ```
