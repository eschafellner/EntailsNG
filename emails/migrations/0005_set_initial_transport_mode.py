from django.db import migrations


def set_transport_mode(apps, schema_editor):
    Model = apps.get_model('emails', 'GeneralEmailSettings')
    for obj in Model.objects.all():
        if obj.smtp_host:
            obj.transport_mode = 'smtp'
        else:
            # Kein DB-Host: bisher lief der .env-Fallback.
            # Nur als eingerichtet markieren, wenn eine Absenderadresse
            # gesetzt ist, die nicht der alte Fake-Default ist.
            if obj.sender_email and obj.sender_email != 'noreply@entailsng.de':
                obj.transport_mode = 'env'
            else:
                obj.transport_mode = 'unconfigured'

        # Fake-Default aus dem Feld entfernen, damit das Admin ihn nicht
        # als gültige Konfiguration anzeigt
        if obj.sender_email == 'noreply@entailsng.de':
            obj.sender_email = ''

        if obj.sender_name == 'EntailsNG Event-Team':
            obj.sender_name = ''

        obj.save(update_fields=['transport_mode', 'sender_email', 'sender_name'])


def reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('emails', '0004_generalemailsettings_credentials_broken_and_more'),
    ]

    operations = [
        migrations.RunPython(set_transport_mode, reverse),
    ]
