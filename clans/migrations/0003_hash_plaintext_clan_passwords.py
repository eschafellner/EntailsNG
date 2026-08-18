from django.contrib.auth.hashers import make_password
from django.db import migrations


def hash_clan_passwords(apps, schema_editor):
    Clan = apps.get_model('clans', 'Clan')
    for clan in Clan.objects.all():
        pwd = clan.password
        if pwd and not (
            pwd.startswith('pbkdf2_') or
            pwd.startswith('argon2') or
            pwd.startswith('bcrypt') or
            pwd.startswith('scrypt')
        ):
            clan.password = make_password(pwd)
            clan.save(update_fields=['password'])


class Migration(migrations.Migration):

    dependencies = [
        ('clans', '0002_alter_clan_logo_alter_clan_password'),
    ]

    operations = [
        migrations.RunPython(hash_clan_passwords, reverse_code=migrations.RunPython.noop),
    ]
