#!/usr/bin/env bash
set -e

# Do not migrate/seed a database while an interrupted restore still needs recovery.
if [ "${SKIP_ENTRYPOINT_INIT:-0}" != "1" ] && [ -f "${BACKUP_ROOT:-/app/backups_data}/maintenance.json" ]; then
    echo "Backup-Wartungsmodus aktiv: Initialisierung bleibt bis zur Rücksetzung pausiert."
    exec "$@"
fi

# Wenn SKIP_ENTRYPOINT_INIT=1 gesetzt ist, direkt das übergebene Kommando ausführen
if [ "${SKIP_ENTRYPOINT_INIT:-0}" = "1" ]; then
    exec "$@"
fi

# 1. Auf PostgreSQL warten (falls nicht SKIP_ENTRYPOINT_WAIT=1)
if [ "${SKIP_ENTRYPOINT_WAIT:-0}" != "1" ]; then
    DB_HOST_VAL="${DB_HOST:-db}"
    DB_PORT_VAL="${DB_PORT:-5432}"
    echo "⏳ Warte auf PostgreSQL ($DB_HOST_VAL:$DB_PORT_VAL)..."
    COUNT=0
    while ! python -c "import socket; s = socket.socket(); s.settimeout(1); s.connect(('$DB_HOST_VAL', int('$DB_PORT_VAL'))); s.close()" 2>/dev/null; do
        COUNT=$((COUNT+1))
        if [ $COUNT -ge 30 ]; then
            echo "❌ Fehler: PostgreSQL ($DB_HOST_VAL:$DB_PORT_VAL) nach 30 Sekunden nicht erreichbar!"
            exit 1
        fi
        sleep 1
    done
    echo "✓ PostgreSQL ist bereit."
fi

# 2. Auf Redis warten (falls REDIS_URL gesetzt und nicht SKIP_ENTRYPOINT_WAIT=1)
if [ "${SKIP_ENTRYPOINT_WAIT:-0}" != "1" ] && [ -n "$REDIS_URL" ]; then
    REDIS_HOST=$(python -c "import urllib.parse, os; url = os.environ.get('REDIS_URL', 'redis://redis:6379/1'); parsed = urllib.parse.urlparse(url); print(parsed.hostname or 'redis')")
    REDIS_PORT=$(python -c "import urllib.parse, os; url = os.environ.get('REDIS_URL', 'redis://redis:6379/1'); parsed = urllib.parse.urlparse(url); print(parsed.port or 6379)")
    echo "⏳ Warte auf Redis ($REDIS_HOST:$REDIS_PORT)..."
    COUNT=0
    while ! python -c "import socket; s = socket.socket(); s.settimeout(1); s.connect(('$REDIS_HOST', int('$REDIS_PORT'))); s.close()" 2>/dev/null; do
        COUNT=$((COUNT+1))
        if [ $COUNT -ge 30 ]; then
            echo "❌ Fehler: Redis ($REDIS_HOST:$REDIS_PORT) nach 30 Sekunden nicht erreichbar!"
            exit 1
        fi
        sleep 1
    done
    echo "✓ Redis ist bereit."
fi

# 3. Datenbank-Migrationen ausführen (falls nicht übersprungen)
if [ "${SKIP_ENTRYPOINT_MIGRATION:-0}" != "1" ]; then
    echo "🚀 Führe Datenbank-Migrationen aus..."
    python manage.py migrate --noinput
fi

# 4. Statische Dateien sammeln
echo "📦 Sammle statische Dateien..."
python manage.py collectstatic --noinput

# Required seeds run inside the demo transaction or the ordinary installation.
if [ "${DEMO_MODE:-false}" = "true" ] || [ "${DEMO_MODE:-0}" = "1" ] || [ "${DEMO_MODE:-false}" = "True" ] || [ "${LOAD_DEMO_DATA:-false}" = "true" ] || [ "${LOAD_DEMO_DATA:-0}" = "1" ]; then
    DEMO_MODE=True python manage.py seed_demo_data
else
    python manage.py seed_translations
    python manage.py seed_features
    python manage.py seed_email_templates
fi

echo "✨ Initialisierung erfolgreich abgeschlossen. Starte Anwendung..."
exec "$@"
