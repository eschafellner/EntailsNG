from django.db import migrations, models


def set_is_template(apps, schema_editor):
    SeatingPlan = apps.get_model('seating', 'SeatingPlan')
    for plan in SeatingPlan.objects.all():
        plan.is_template = (plan.event_id is None)
        plan.save(update_fields=['is_template'])


class Migration(migrations.Migration):

    dependencies = [
        ('seating', '0004_seatingcell_seating_cell_coords_positive'),
    ]

    operations = [
        migrations.AddField(
            model_name='seatingplan',
            name='is_template',
            field=models.BooleanField(
                default=False,
                help_text='Kennzeichnet diesen Plan als wiederverwendbare Vorlage ohne feste Event-Zuweisung.',
                verbose_name='Ist Vorlage',
            ),
        ),
        migrations.RunPython(
            set_is_template,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
