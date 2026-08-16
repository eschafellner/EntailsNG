from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seating', '0005_seatingplan_is_template'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='seatingcell',
            index=models.Index(fields=['plan', 'cell_type', 'reservation_status'], name='seating_plan_type_res_idx'),
        ),
        migrations.AddIndex(
            model_name='seatingcell',
            index=models.Index(fields=['registration'], name='seating_cell_reg_idx'),
        ),
    ]
