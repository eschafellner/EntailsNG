#!/usr/bin/env bash
# ==============================================================================
# EntailsNG - Anfängerfreundliches Installationsskript
# ==============================================================================

set -e

# Farben für schöne Konsolen-Ausgaben
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=====================================================${NC}"
echo -e "${BLUE}   🚀 Willkommen beim EntailsNG Setup-Assistenten   ${NC}"
echo -e "${BLUE}=====================================================${NC}\n"

# 1. Prüfen, ob Python 3 vorhanden ist
echo -e "${YELLOW}[1/5] Prüfe Python-Installation...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 konnte nicht gefunden werden! Bitte installiere Python 3.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python 3 ist installiert.${NC}\n"

# 2. Virtuelle Umgebung (.venv) anlegen
echo -e "${YELLOW}[2/5] Richte isolierte Umgebung (.venv) ein...${NC}"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "${GREEN}✓ Virtuelle Umgebung `.venv` erfolgreich erstellt.${NC}"
else
    echo -e "${GREEN}✓ Virtuelle Umgebung `.venv` existiert bereits.${NC}"
fi
source .venv/bin/activate
echo ""

# 3. Paket-Abhängigkeiten installieren
echo -e "${YELLOW}[3/5] Installiere benötigte Programmpakete (Django, psycopg2 etc.)...${NC}"
pip install --upgrade pip --quiet 2>/dev/null || true
pip install -r requirements.txt --quiet
echo -e "${GREEN}✓ Alle Abhängigkeiten wurden erfolgreich installiert.${NC}\n"

# 4. Datenbank einrichten (PostgreSQL als Standard)
echo -e "${YELLOW}[4/5] Richte PostgreSQL / SQLite Datenbank-Struktur ein...${NC}"

# Automatische Erkennung ob PostgreSQL erreichbar ist
if [ -z "$DB_ENGINE" ]; then
    if python3 -c "import socket; s = socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', 5432)); s.close()" 2>/dev/null; then
        export DB_ENGINE=postgresql
        echo -e "${GREEN}✓ PostgreSQL Datenbank auf Port 5432 erkannt.${NC}"
    else
        export DB_ENGINE=sqlite
        echo -e "${YELLOW}ℹ️ PostgreSQL nicht auf Port 5432 erreichbar. Nutze Entwicklungs-Fallback.${NC}"
    fi
fi

python manage.py migrate --noinput
python manage.py seed_translations --quiet 2>/dev/null || python manage.py seed_translations
python manage.py seed_features --quiet 2>/dev/null || python manage.py seed_features

# Falls Vorab-Daten vorhanden sind, laden
if [ -f "initial_data.json" ]; then
    echo -e "${YELLOW}   Lade Vorab-Daten (Test-Events, Sitzpläne, Demo-User)...${NC}"
    python manage.py loaddata initial_data.json --quiet 2>/dev/null || python manage.py loaddata initial_data.json
    echo -e "${GREEN}✓ Demo-Daten erfolgreich geladen.${NC}"
fi

echo ""

# 5. Abschluss & Startskript
echo -e "${YELLOW}[5/5] Ausführungsrechte für Startskript setzen...${NC}"
chmod +x start.sh 2>/dev/null || true
echo -e "${GREEN}✓ Setup vollständig abgeschlossen!${NC}\n"

echo -e "${GREEN}=====================================================${NC}"
echo -e "${GREEN} 🎉 INSTALLATION ERFOLGREICH ABGESCHLOSSEN!          ${NC}"
echo -e "${GREEN}=====================================================${NC}"
echo -e "Du kannst den Server jetzt jederzeit mit folgendem Befehl starten:"
echo -e "${BLUE}   ./start.sh${NC}\n"
