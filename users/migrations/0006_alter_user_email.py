from django.db import migrations, models


def ensure_unique_emails_for_existing_users(apps, schema_editor):
    User = apps.get_model('users', 'User')
    seen_emails = set()

    for user in User.objects.all():
        email = (user.email or '').strip().lower()
        if not email or email in seen_emails:
            email = f"{user.username.lower()}_{user.pk}@entailsng.local"
        seen_emails.add(email)
        user.email = email
        user.save(update_fields=['email'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_emailverificationcode_failed_attempts'),
    ]

    operations = [
        migrations.RunPython(
            ensure_unique_emails_for_existing_users,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(
                error_messages={'unique': 'Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet.'},
                max_length=254,
                unique=True,
                verbose_name='E-Mail-Adresse',
            ),
        ),
    ]
