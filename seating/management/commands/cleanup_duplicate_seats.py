from django.core.management.base import BaseCommand
from django.db import transaction
from seating.models import SeatingPlan, SeatingCell


class Command(BaseCommand):
    help = 'Findet und bereinigt doppelte Sitzplatzbezeichnungen (seat_label) in allen Sitzplänen.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Nur prüfen und anzeigen, welche Plätze geändert würden, ohne Änderungen zu speichern.',
        )
        parser.add_argument(
            '--plan-id',
            type=int,
            default=None,
            help='Nur einen bestimmten Sitzplan prüfen.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        plan_id = options['plan_id']

        if dry_run:
            self.stdout.write(self.style.WARNING('🔍 DRY-RUN-MODUS: Keine Änderungen werden in die Datenbank geschrieben.'))

        plans = SeatingPlan.objects.all()
        if plan_id is not None:
            plans = plans.filter(pk=plan_id)

        total_cleaned = 0

        for plan in plans:
            cells = list(plan.cells.filter(cell_type=SeatingCell.CellType.SEAT).order_by('pk'))
            seen_labels = {}
            duplicates_found = []

            for cell in cells:
                label = (cell.seat_label or '').strip()
                if not label:
                    continue

                if label not in seen_labels:
                    seen_labels[label] = cell
                else:
                    # Doppelter Sitzplatz gefunden!
                    # Falls die aktuelle Zelle belegt ist und die vorherige Zelle frei ist, behalten wir die belegte
                    prev_cell = seen_labels[label]
                    if cell.registration_id and not prev_cell.registration_id:
                        # Behalte die aktuelle Zelle als Original, benenne die vorherige um
                        duplicates_found.append(prev_cell)
                        seen_labels[label] = cell
                    else:
                        duplicates_found.append(cell)

            if not duplicates_found:
                self.stdout.write(self.style.SUCCESS(f'✓ Sitzplan #{plan.id} ("{plan.name}"): Keine Duplikate.'))
                continue

            self.stdout.write(self.style.WARNING(
                f'⚠️ Sitzplan #{plan.id} ("{plan.name}"): {len(duplicates_found)} doppelte Sitzplätze gefunden!'
            ))

            with transaction.atomic():
                all_current_labels = {c.seat_label for c in cells if c.seat_label}
                for dup in duplicates_found:
                    old_label = dup.seat_label
                    # Neues Label nach Koordinatenschema generieren
                    new_label = f'R{dup.y}-P{dup.x}'
                    counter = 1
                    while new_label in all_current_labels:
                        new_label = f'R{dup.y}-P{dup.x}_{counter}'
                        counter += 1

                    all_current_labels.add(new_label)
                    self.stdout.write(
                        f'   - Position ({dup.x},{dup.y}): "{old_label}" -> "{new_label}"'
                    )

                    if not dry_run:
                        dup.seat_label = new_label
                        dup.save(update_fields=['seat_label'])
                        total_cleaned += 1

        if dry_run:
            self.stdout.write(self.style.SUCCESS('Scan abgeschlossen (Dry-Run).'))
        else:
            self.stdout.write(self.style.SUCCESS(f'🎉 Bereinigung abgeschlossen. {total_cleaned} Plätze aktualisiert.'))
