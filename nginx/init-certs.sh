#!/bin/sh
set -e

DOMAIN="${DOMAIN_NAME:-localhost}"
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"

# Falls für diese Domain noch kein Zertifikat existiert (z.B. bei Cloudflare Tunnel oder Erststart):
# Fallback-Zertifikat kopieren, damit Nginx beim Starten niemals mit einem Fehler abbricht.
if [ ! -f "$CERT_DIR/fullchain.pem" ] || [ ! -f "$CERT_DIR/privkey.pem" ]; then
    echo "ℹ️ [Nginx-Init] Kein SSL-Zertifikat unter $CERT_DIR gefunden."
    echo "ℹ️ [Nginx-Init] Richte sicheres Fallback-Zertifikat ein, damit Nginx sauber startet..."
    mkdir -p "$CERT_DIR"
    cp /etc/nginx/dummy-certs/fullchain.pem "$CERT_DIR/fullchain.pem"
    cp /etc/nginx/dummy-certs/privkey.pem "$CERT_DIR/privkey.pem"
    chmod 644 "$CERT_DIR/fullchain.pem"
    chmod 600 "$CERT_DIR/privkey.pem"
    echo "✓ [Nginx-Init] Fallback-Zertifikat erfolgreich hinterlegt."
fi
