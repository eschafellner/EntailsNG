from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('users', '0009_user_unique_lower_email')]

    operations = [
        migrations.AddField(
            model_name='user',
            name='deleted_at',
            field=models.DateTimeField(
                null=True, blank=True, editable=False, verbose_name='Account gelöscht am',
            ),
        ),
    ]
