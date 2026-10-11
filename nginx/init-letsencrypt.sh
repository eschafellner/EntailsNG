#!/usr/bin/env bash
# Run from the repository root. Existing Certbot lineages are never deleted.
set -euo pipefail

if [ ! -f .env ]; then
    echo "Fehler: .env fehlt. Bitte zuerst aus .env.example erstellen."
    exit 1
fi
set -a
source .env
set +a
: "${DOMAIN_NAME:?DOMAIN_NAME muss gesetzt sein}"
: "${CERTBOT_EMAIL:?CERTBOT_EMAIL muss gesetzt sein}"
[[ "$DOMAIN_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || {
    echo "Fehler: Ungültiger Domainname."
    exit 1
}

CERT_PATH="./data/certbot/conf/live/$DOMAIN_NAME"
RENEWAL_PATH="./data/certbot/conf/renewal/$DOMAIN_NAME.conf"

# A directory can contain the startup fallback. Require a real, valid lineage.
if [ -f "$RENEWAL_PATH" ] && [ -s "$CERT_PATH/fullchain.pem" ] && \
   [ -s "$CERT_PATH/privkey.pem" ] && \
   openssl x509 -in "$CERT_PATH/fullchain.pem" -noout -checkend 0 && \
   openssl x509 -in "$CERT_PATH/fullchain.pem" -noout -checkhost "$DOMAIN_NAME" && \
   [ "$(openssl x509 -in "$CERT_PATH/fullchain.pem" -noout -subject -nameopt RFC2253 | cut -d= -f2-)" != \
     "$(openssl x509 -in "$CERT_PATH/fullchain.pem" -noout -issuer -nameopt RFC2253 | cut -d= -f2-)" ] && \
   [ "$(openssl x509 -in "$CERT_PATH/fullchain.pem" -pubkey -noout)" = \
     "$(openssl pkey -in "$CERT_PATH/privkey.pem" -pubout)" ]; then
    echo "Bestehendes gültiges Certbot-Zertifikat gefunden."
    docker compose --profile vps up -d
    docker compose exec -T nginx nginx -s reload
    exit 0
fi

# Nginx's entrypoint installs a fallback when needed; keep it loaded during ACME.
mkdir -p ./data/certbot/www
docker compose up --force-recreate -d nginx

# Remove only a non-Certbot fallback. Preserve renewal metadata and archives.
if [ ! -f "$RENEWAL_PATH" ] && [ ! -d "./data/certbot/conf/archive/$DOMAIN_NAME" ]; then
    docker compose run --rm --entrypoint rm certbot -rf "/etc/letsencrypt/live/$DOMAIN_NAME"
fi
docker compose run --rm --entrypoint certbot certbot certonly \
    --webroot -w /var/www/certbot --email "$CERTBOT_EMAIL" \
    --cert-name "$DOMAIN_NAME" -d "$DOMAIN_NAME" --rsa-key-size 4096 \
    --agree-tos --no-eff-email --force-renewal

docker compose exec -T nginx nginx -t
docker compose exec -T nginx nginx -s reload
docker compose --profile vps up -d
echo "HTTPS-Einrichtung für https://$DOMAIN_NAME abgeschlossen."
