import logging
import signal
import threading
import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from configuration.heartbeat import touch_heartbeat
from emails.services import process_email_queue

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Verarbeitet ausstehende E-Mails aus der persistenten Outbox-Warteschlange (Transactional Outbox)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help="Maximale Anzahl der pro Durchlauf zu verarbeitenden E-Mails (Standard: 50).",
        )
        parser.add_argument(
            '--daemon',
            action='store_true',
            help="Startet den Worker als dauerhaften Hintergrundprozess.",
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=5,
            help="Wartezeit in Sekunden zwischen Abfragen im Daemon-Modus (Standard: 5).",
        )

    def handle(self, *args, **options):
        limit = options['limit']
        daemon = options['daemon']
        interval = options['interval']

        if not daemon:
            sent, failed = process_email_queue(limit=limit)
            self.stdout.write(
                self.style.SUCCESS(f"Queue-Durchlauf beendet: {sent} gesendet, {failed} fehlgeschlagen.")
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"Starte E-Mail Queue Worker im Daemon-Modus (Intervall: {interval}s, Limit: {limit})...")
        )
        stop = threading.Event()
        previous_handler = signal.signal(signal.SIGTERM, lambda *_: stop.set())
        try:
            while not stop.is_set():
                # Fehler eines Durchlaufs (z. B. DB-Verbindungsabbruch) beenden den Worker nicht.
                try:
                    close_old_connections()
                    sent, failed = process_email_queue(limit=limit)
                    touch_heartbeat()
                    if sent > 0 or failed > 0:
                        self.stdout.write(
                            self.style.SUCCESS(f"[{time.strftime('%X')}] {sent} gesendet, {failed} fehlgeschlagen.")
                        )
                except Exception:
                    logger.exception('Queue-Durchlauf fehlgeschlagen; neuer Versuch nach Intervall')
                stop.wait(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nE-Mail Queue Worker durch Benutzer beendet."))
        else:
            self.stdout.write(self.style.WARNING("E-Mail Queue Worker nach SIGTERM beendet."))
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
            close_old_connections()
