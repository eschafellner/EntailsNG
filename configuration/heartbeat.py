"""Heartbeat-Datei für Compose-Healthchecks der Hintergrund-Worker (Befund F-039)."""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def touch_heartbeat():
    """Markiert einen erfolgreichen Worker-Durchlauf; ohne WORKER_HEARTBEAT_FILE wirkungslos."""
    path = os.environ.get('WORKER_HEARTBEAT_FILE')
    if not path:
        return
    try:
        Path(path).touch()
    except OSError:
        logger.warning('Heartbeat-Datei %s konnte nicht geschrieben werden.', path)
