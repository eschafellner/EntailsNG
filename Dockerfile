# Build-Stufe: Wheels bauen bzw. laden; Compiler und -dev-Pakete bleiben hier (Befund F-038).
FROM python:3.12-slim-bookworm AS wheels

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir pip==26.2.1 && \
    python -m pip wheel --no-cache-dir --wheel-dir /wheels -r /tmp/requirements.txt


FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Laufzeit: curl (Healthcheck, PGDG-Schlüssel), Zertifikate und JPEG-Laufzeitbibliothek für Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Native backup tools must match the PostgreSQL 16 server (official PGDG repository).
RUN install -d /usr/share/postgresql-common/pgdg && \
    curl --fail --silent --show-error https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc && \
    echo 'deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' \
      > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 && \
    rm -rf /var/lib/apt/lists/*

# Non-Root-User für sicheren Betrieb anlegen
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -m -s /bin/bash appuser

COPY requirements.txt /app/
# Keep the installer itself on a corrected, audited version as well.
RUN --mount=type=bind,from=wheels,source=/wheels,target=/wheels \
    python -m pip install --no-cache-dir pip==26.2.1 && \
    python -m pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt && \
    python -m pip check

COPY . /app/

# Verzeichnisse für Static- und Media-Dateien anlegen und Rechte setzen
RUN mkdir -p /app/staticfiles /app/media /app/private_media /app/backups_data && \
    chown -R appuser:appuser /app && \
    chmod +x /app/entrypoint.sh

USER appuser

EXPOSE 8000

# Gunicorn liest WEB_CONCURRENCY selbst; .env kann den Standard überschreiben.
ENV WEB_CONCURRENCY=3

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--timeout", "60", "--forwarded-allow-ips=*", "--access-logfile", "-", "--error-logfile", "-"]


