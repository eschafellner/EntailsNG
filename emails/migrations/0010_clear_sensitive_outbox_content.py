from django.db import migrations


def clear_sensitive_content(apps, schema_editor):
    # F-020: Bereits abgeschlossene Passwort-Reset-Mails enthalten noch gültige oder
    # abgelaufene Reset-Links im Klartext; der Inhalt wird für den Betrieb nicht benötigt.
    OutgoingEmail = apps.get_model('emails', 'OutgoingEmail')
    OutgoingEmail.objects.filter(
        template_key='password_reset', status__in=['SENT', 'FAILED', 'EXPIRED'],
    ).update(body_text='', body_html='')


class Migration(migrations.Migration):

    dependencies = [
        ('emails', '0009_contact_form'),
    ]

    operations = [
        migrations.RunPython(clear_sensitive_content, migrations.RunPython.noop),
    ]
