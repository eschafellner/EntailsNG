#!/usr/bin/env bash
# ==============================================================================
# EntailsNG - Installationsassistent (Unterstützt Podman & Docker)
# ==============================================================================

set -e

# Farben für schöne Konsolen-Ausgaben
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

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
    echo -e "${GREEN}✓ Virtuelle Umgebung \`.venv\` erfolgreich erstellt.${NC}"
else
    echo -e "${GREEN}✓ Virtuelle Umgebung \`.venv\` existiert bereits.${NC}"
fi
source .venv/bin/activate
echo ""

# 3. Paket-Abhängigkeiten installieren
echo -e "${YELLOW}[3/5] Installiere benötigte Programmpakete (Django, psycopg, Pillow etc.)...${NC}"
pip install --upgrade pip --quiet 2>/dev/null || true
pip install -r requirements.txt --quiet
echo -e "${GREEN}✓ Alle Abhängigkeiten wurden erfolgreich installiert.${NC}\n"

# 3b. Konfigurationsdatei (.env) initialisieren falls nicht vorhanden
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo -e "${YELLOW}   Erstelle lokale .env Datei mit sicherem Zufallsschlüssel...${NC}"
    cp .env.example .env
    RANDOM_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
    sed -i "s|SECRET_KEY=hier-einen-langen-zufaelligen-secret-key-eintragen|SECRET_KEY=${RANDOM_SECRET}|" .env
    sed -i "s|DEBUG=False|DEBUG=True|" .env
    sed -i "s|ALLOWED_HOSTS=lan.meinedomain.de|ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0|" .env
    sed -i "s|CSRF_TRUSTED_ORIGINS=https://lan.meinedomain.de|CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000|" .env
    echo -e "${GREEN}✓ .env erfolgreich initialisiert.${NC}\n"
fi

if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# 4. Datenbank einrichten
echo -e "${YELLOW}[4/5] Richte Datenbank-Struktur ein...${NC}"

# Automatische Erkennung ob PostgreSQL erreichbar ist
PG_RUNNING=false
if python3 -c "import socket; s = socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', 5432)); s.close()" 2>/dev/null; then
    PG_RUNNING=true
fi

# Falls PostgreSQL nicht läuft, versuche Container über Podman/Docker zu starten
if [ "$PG_RUNNING" = false ] && [ "${DB_ENGINE:-postgresql}" != "sqlite" ]; then
    if command -v podman-compose &> /dev/null || command -v podman &> /dev/null; then
        echo -e "${YELLOW}   Starte lokale PostgreSQL & Redis über Podman...${NC}"
        systemctl --user enable --now podman.socket 2>/dev/null || true
        podman compose up -d db redis 2>/dev/null || podman-compose up -d db redis 2>/dev/null || true
        sleep 2
    elif command -v docker &> /dev/null; then
        echo -e "${YELLOW}   Starte lokale PostgreSQL & Redis über Docker...${NC}"
        docker compose up -d db redis 2>/dev/null || true
        sleep 2
    fi
fi

if python3 -c "import socket; s = socket.socket(); s.settimeout(1); s.connect(('127.0.0.1', 5432)); s.close()" 2>/dev/null; then
    export DB_ENGINE=postgresql
    echo -e "${GREEN}✓ PostgreSQL Datenbank auf Port 5432 erkannt.${NC}"
else
    export DB_ENGINE=sqlite
    echo -e "${YELLOW}ℹ️ PostgreSQL nicht auf Port 5432 erreichbar. Nutze SQLite Entwicklungs-Fallback.${NC}"
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput --quiet 2>/dev/null || python manage.py collectstatic --noinput

# Parameter-Check für Demo-Daten
LOAD_DEMO=false
for arg in "$@"; do
    if [ "$arg" == "--demo" ] || [ "$arg" == "--with-demo" ]; then
        LOAD_DEMO=true
    fi
done
if [ "$INSTALL_DEMO_DATA" == "1" ] || [ "$INSTALL_DEMO_DATA" == "true" ]; then
    LOAD_DEMO=true
fi

# Falls Demo-Daten explizit angefordert wurden, laden
if [ "$LOAD_DEMO" = true ] && [ -f "initial_data.json" ]; then
    echo -e "${YELLOW}   Lade Vorab-Daten (Test-Events, Sitzpläne, Demo-User sadmin/gamer1)...${NC}"
    python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from configuration.models import SystemTranslation, NavigationItem, FeatureFlag
SystemTranslation.objects.all().delete()
NavigationItem.objects.all().delete()
FeatureFlag.objects.all().delete()
" 2>/dev/null || true
    python manage.py loaddata initial_data.json --quiet 2>/dev/null || python manage.py loaddata initial_data.json
    python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.core.management.color import no_style
from django.db import connection
from django.apps import apps
[connection.cursor().execute(sql) for sql in connection.ops.sequence_reset_sql(no_style(), apps.get_models())]
" 2>/dev/null || true
    echo -e "${GREEN}✓ Demo-Daten erfolgreich geladen.${NC}"
else
    echo -e "${BLUE}ℹ️ Saubere Installation: Es wurden keine Demo-Benutzer oder Test-Events geladen.${NC}"
    echo -e "${BLUE}   (Hinweis: Führe './install.sh --demo' aus, falls du Test-Daten laden möchtest.)${NC}"
fi

# System-Seeds ausführen
python manage.py seed_translations --quiet 2>/dev/null || python manage.py seed_translations
python manage.py seed_features --quiet 2>/dev/null || python manage.py seed_features
python manage.py seed_email_templates --quiet 2>/dev/null || python manage.py seed_email_templates

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
