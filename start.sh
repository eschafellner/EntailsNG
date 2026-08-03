#!/usr/bin/env bash
# ==============================================================================
# EntailsNG - 1-Klick Startskript
# ==============================================================================

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Prüfen ob .venv existiert
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Keine Installation gefunden. Starte zuerst das Setup...${NC}"
    bash install.sh
fi

source .venv/bin/activate

# Automatische Erkennung der PostgreSQL Datenbank
if [ -z "$DB_ENGINE" ]; then
    if python3 -c "import socket; s = socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', 5432)); s.close()" 2>/dev/null; then
        export DB_ENGINE=postgresql
    else
        export DB_ENGINE=sqlite
    fi
fi

echo -e "${BLUE}=====================================================${NC}"
echo -e "${GREEN} 🚀 EntailsNG Server wird gestartet...               ${NC}"
echo -e "${BLUE}=====================================================${NC}\n"

echo -e "Öffne deinen Internet-Browser und rufe folgende Adressen auf:\n"
echo -e "${CYAN} 🌐 Hauptseite / Dashboard: ${NC} http://127.0.0.1:8000/"
echo -e "${CYAN} 📱 Helfer Check-in Scanner: ${NC} http://127.0.0.1:8000/checkin/scanner/"
echo -e "${CYAN} 🛠️ Admin-Bereich:          ${NC} http://127.0.0.1:8000/admin/\n"
echo -e "${YELLOW}💡 Hinweis: Drücke [STRG] + [C] im Terminal, um den Server zu beenden.${NC}"
echo -e "${BLUE}=====================================================${NC}\n"

python manage.py runserver 0.0.0.0:8000
