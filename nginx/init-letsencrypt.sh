#!/usr/bin/env bash
# ==============================================================================
# EntailsNG - Automatischer Let's Encrypt TLS-Zertifikats-Initialisierer
# ==============================================================================
set -e

# .env laden
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
else
    echo "❌ Fehler: .env Datei nicht gefunden. Bitte erstelle eine .env basierend auf .env.example."
    exit 1
fi

if [ -z "$DOMAIN_NAME" ]; then
    echo "❌ Fehler: DOMAIN_NAME ist in .env nicht gesetzt!"
    exit 1
fi

if [ -z "$CERTBOT_EMAIL" ]; then
    echo "❌ Fehler: CERTBOT_EMAIL ist in .env nicht gesetzt!"
    exit 1
fi

echo "🚀 Starte TLS-Zertifikatsausstellung für Domain: $DOMAIN_NAME"

# 1. Prüfen ob Zertifikat bereits existiert
CERT_PATH="./data/certbot/conf/live/$DOMAIN_NAME"
if [ -d "$CERT_PATH" ]; then
    echo "ℹ️ Bestehendes Zertifikat für $DOMAIN_NAME gefunden. Starte regulär..."
    docker compose up -d
    exit 0
fi

# 2. Dummy-Zertifikat erstellen, damit Nginx beim ersten Start nicht abstürzt
echo "⏳ Erstelle temporäres Dummy-Zertifikat für den initialen Nginx-Start..."
mkdir -p "./data/certbot/conf/live/$DOMAIN_NAME"
mkdir -p "./data/certbot/www"

docker compose run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:2048 -days 1\
    -keyout '/etc/letsencrypt/live/$DOMAIN_NAME/privkey.pem' \
    -out '/etc/letsencrypt/live/$DOMAIN_NAME/fullchain.pem' \
    -subj '/CN=localhost'" certbot

# 3. Nginx starten, um die ACME-Challenge erreichbar zu machen
echo "⏳ Starte Nginx für ACME Challenge..."
docker compose up --force-recreate -d nginx

# 4. Dummy-Zertifikat löschen
echo "⏳ Lösche temporäres Dummy-Zertifikat vor echtem Abruf..."
docker compose run --rm --entrypoint "\
  rm -Rf /etc/letsencrypt/live/$DOMAIN_NAME && \
  rm -Rf /etc/letsencrypt/archive/$DOMAIN_NAME && \
  rm -Rf /etc/letsencrypt/renewal/$DOMAIN_NAME.conf" certbot

# 5. Echtes Let's Encrypt Zertifikat anfordern
echo "🔐 Fordere offizielles Let's Encrypt Zertifikat für $DOMAIN_NAME an..."
docker compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    --email $CERTBOT_EMAIL \
    -d $DOMAIN_NAME \
    --rsa-key-size 4096 \
    --agree-tos \
    --no-eff-email \
    --force-renewal" certbot

# 6. Nginx neu laden, um das echte Zertifikat einzubinden
echo "🔄 Lade Nginx mit echtem Zertifikat neu..."
docker compose exec nginx nginx -s reload

# 7. Gesamten Stack starten
echo "🚀 Starte alle Dienste..."
docker compose up -d

echo "✅ HTTPS-Einrichtung für https://$DOMAIN_NAME erfolgreich abgeschlossen!"
