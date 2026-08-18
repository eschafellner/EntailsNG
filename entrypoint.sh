#!/usr/bin/env bash
set -e

# Wenn SKIP_ENTRYPOINT_INIT=1 gesetzt ist, direkt das übergebene Kommando ausführen
if [ "${SKIP_ENTRYPOINT_INIT:-0}" = "1" ]; then
    exec "$@"
fi

# 1. Auf PostgreSQL warten (falls nicht SQLite und nicht SKIP_ENTRYPOINT_WAIT=1)
if [ "${SKIP_ENTRYPOINT_WAIT:-0}" != "1" ] && [ "${DB_ENGINE:-postgresql}" != "sqlite" ]; then
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

# 5. Idempotenter Fixture-Import (nur beim allerersten Start, um modifizierte Daten bei Restarts zu schützen)
IS_INITIALIZED=$(python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from users.models import User
print('true' if User.objects.filter(is_superuser=True).exists() else 'false')
" 2>/dev/null || echo "false")

if [ "$IS_INITIALIZED" = "false" ] && [ -f "initial_data.json" ]; then
    echo "📥 Erster Systemstart erkannt: Lade initial_data.json..."
    python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from configuration.models import SystemTranslation, NavigationItem, FeatureFlag
SystemTranslation.objects.all().delete()
NavigationItem.objects.all().delete()
FeatureFlag.objects.all().delete()
" 2>/dev/null || true
    python manage.py loaddata initial_data.json
    python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.core.management.color import no_style
from django.db import connection
from django.apps import apps
statements = connection.ops.sequence_reset_sql(no_style(), apps.get_models())
with connection.cursor() as cursor:
    for sql in statements:
        cursor.execute(sql)
" 2>/dev/null || true
else
    echo "ℹ️ Datenbank enthält bereits Daten. Überspringe Fixture-Import zur Erhaltung der Datenintegrität."
fi

# 6. System-Seeds ausführen (get_or_create: idempotent)
echo "🌱 Aktualisiere System-Übersetzungen, Feature-Flags und E-Mail-Templates..."
python manage.py seed_translations 2>/dev/null || true
python manage.py seed_features 2>/dev/null || true
python manage.py seed_email_templates 2>/dev/null || true

echo "✨ Initialisierung erfolgreich abgeschlossen. Starte Anwendung..."
exec "$@"
