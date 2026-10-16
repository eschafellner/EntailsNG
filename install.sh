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
    echo -e "${YELLOW}   Erstelle lokale .env Datei mit sicheren Zufallsschlüsseln...${NC}"
    cp .env.example .env
    RANDOM_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
    RANDOM_ENCRYPT=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
    RANDOM_DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i "s|SECRET_KEY=hier-einen-langen-zufaelligen-secret-key-eintragen|SECRET_KEY=${RANDOM_SECRET}|" .env
    sed -i "s|FIELD_ENCRYPTION_KEY=hier-einen-langen-zufaelligen-schluessel-eintragen|FIELD_ENCRYPTION_KEY=${RANDOM_ENCRYPT}|" .env
    sed -i "s|DB_PASSWORD=hier-ein-sicheres-datenbank-passwort-eintragen|DB_PASSWORD=${RANDOM_DB_PASSWORD}|" .env
    sed -i "s|PUBLIC_BASE_URL=https://lan.example.com|PUBLIC_BASE_URL=http://127.0.0.1:8000|" .env
    sed -i "s|EMAIL_BACKEND=emails.backends.ConfiguredSMTPBackend|EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend|" .env
    sed -i "s|DEBUG=False|DEBUG=True|" .env
    sed -i "s|ALLOWED_HOSTS=lan.meinedomain.de,127.0.0.1|ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0|" .env
    sed -i "s|CSRF_TRUSTED_ORIGINS=https://lan.meinedomain.de|CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000|" .env
    sed -i "s|DB_HOST=db|DB_HOST=127.0.0.1|" .env
    sed -i "s|REDIS_URL=redis://redis:6379/1|REDIS_URL=redis://127.0.0.1:6379/1|" .env
    sed -i "s|BEHIND_PROXY=True|BEHIND_PROXY=False|" .env
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
if python3 scripts/wait_for_postgres.py --timeout 0 2>/dev/null; then
    PG_RUNNING=true
fi

# Falls PostgreSQL nicht läuft, versuche Container über Podman/Docker zu starten
if [ "$PG_RUNNING" = false ]; then
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

# PostgreSQL ist erforderlich; bei Verbindungsfehlern den Start abbrechen.
python3 scripts/wait_for_postgres.py --timeout 30

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

# All initialization paths use one atomic, non-destructive demo generator.
if [ "$LOAD_DEMO" = true ]; then
    DEMO_MODE=True python manage.py seed_demo_data
else
    python manage.py seed_translations
    python manage.py seed_features
    python manage.py seed_email_templates
fi
echo "Eigenen Administrator anlegen: python manage.py createsuperuser"

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
