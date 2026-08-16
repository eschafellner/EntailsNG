import secrets
from django.db import migrations, models
import events.models


def generate_unique_short_codes(apps, schema_editor):
    EventRegistration = apps.get_model('events', 'EventRegistration')
    alphabet = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
    existing_codes = set()

    for reg in EventRegistration.objects.all():
        while True:
            code = ''.join(secrets.choice(alphabet) for _ in range(8))
            if code not in existing_codes:
                existing_codes.add(code)
                reg.short_code = code
                reg.save(update_fields=['short_code'])
                break


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0009_event_event_end_date_after_start_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='eventregistration',
            name='short_code',
            field=models.CharField(
                default=events.models.generate_short_code,
                editable=False,
                help_text='8-stelliger unerratbarer Code für die manuelle Einlass-Eingabe',
                max_length=12,
                null=True,
                verbose_name='Ticket-Kurzcode',
            ),
        ),
        migrations.RunPython(
            generate_unique_short_codes,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='eventregistration',
            name='short_code',
            field=models.CharField(
                db_index=True,
                default=events.models.generate_short_code,
                editable=False,
                help_text='8-stelliger unerratbarer Code für die manuelle Einlass-Eingabe',
                max_length=12,
                unique=True,
                verbose_name='Ticket-Kurzcode',
            ),
        ),
    ]
