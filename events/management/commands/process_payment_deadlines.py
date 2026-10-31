from django.core.management.base import BaseCommand

from backups.locking import access_guard
from events.services import PaymentDeadlineService


class Command(BaseCommand):
    help = ('Storniert offene kostenpflichtige Anmeldungen mit abgelaufener Ticket-Zahlungsfrist. '
            'Läuft im Betrieb automatisch im Worker process_clan_seat_holds mit.')

    def handle(self, *args, **options):
        with access_guard():
            count = PaymentDeadlineService.cancel_overdue_registrations()
        self.stdout.write(self.style.SUCCESS(f'{count} Anmeldung(en) wegen abgelaufener Zahlungsfrist storniert.'))
