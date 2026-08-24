#!/usr/bin/env bash
# ==============================================================================
# EntailsNG - 1-Klick Startskript (Unterstützt Podman & Docker)
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

# Prüfen ob Abhängigkeiten vollständig sind (z. B. nach git pull)
if ! python3 -c "import whitenoise" 2>/dev/null; then
    echo -e "${YELLOW}📦 Aktualisiere Python-Pakete aus requirements.txt...${NC}"
    pip install -r requirements.txt --quiet 2>/dev/null || python3 -m pip install -r requirements.txt --quiet
fi

# Lade Umgebungsvariablen aus .env falls vorhanden
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Prüfe, ob PostgreSQL auf 127.0.0.1:5432 erreichbar ist
PG_RUNNING=false
if python3 -c "import socket; s = socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', 5432)); s.close()" 2>/dev/null; then
    PG_RUNNING=true
fi

# Falls PostgreSQL nicht erreichbar ist, prüfe ob Podman oder Docker Compose gestartet werden kann
if [ "$PG_RUNNING" = false ] && [ "${DB_ENGINE:-postgresql}" != "sqlite" ]; then
    if command -v podman-compose &> /dev/null || command -v podman &> /dev/null; then
        echo -e "${YELLOW}🐘 PostgreSQL läuft nicht. Starte DB & Redis über Podman...${NC}"
        systemctl --user enable --now podman.socket 2>/dev/null || true
        podman compose up -d db redis 2>/dev/null || podman-compose up -d db redis 2>/dev/null || true
    elif command -v docker &> /dev/null; then
        echo -e "${YELLOW}🐘 PostgreSQL läuft nicht. Starte DB & Redis über Docker...${NC}"
        docker compose up -d db redis 2>/dev/null || true
    fi
fi

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
