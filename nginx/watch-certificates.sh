#!/bin/sh
# Certbot's deploy hook signals successful renewal through the shared volume.
# No Docker socket or remote command execution is needed.
set -eu
(
    previous=$(cat /etc/letsencrypt/.reload-nginx 2>/dev/null || true)
    while sleep 30; do
        current=$(cat /etc/letsencrypt/.reload-nginx 2>/dev/null || true)
        if [ "$current" != "$previous" ]; then
            if nginx -t && nginx -s reload; then
                previous=$current
            fi
        fi
    done
) &
