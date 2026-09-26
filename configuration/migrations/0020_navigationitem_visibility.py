from django.core.cache import cache
from django.db import migrations, models, transaction


def restrict_media_designer_navigation(apps, schema_editor):
    NavigationItem = apps.get_model('configuration', 'NavigationItem')
    NavigationItem.objects.using(schema_editor.connection.alias).filter(
        url_name__in=('media_template_list', '/media-designer/', '/media-designer')
    ).update(visibility='STAFF')

    def clear_navigation_cache():
        try:
            cache.delete('navigation_items')
        except Exception:
            pass

    transaction.on_commit(clear_navigation_cache, using=schema_editor.connection.alias)


class Migration(migrations.Migration):
    dependencies = [
        ('configuration', '0019_alter_sitecustomization_datenschutz_content'),
    ]

    operations = [
        migrations.AddField(
            model_name='navigationitem',
            name='visibility',
            field=models.CharField(
                choices=[
                    ('PUBLIC', 'Alle Besucher'),
                    ('AUTHENTICATED', 'Nur angemeldete Benutzer'),
                    ('STAFF', 'Nur Mitarbeiter'),
                ],
                default='PUBLIC',
                help_text='Legt fest, für welche Besucher dieser Menüpunkt sichtbar ist. Die Zielseite prüft ihre Zugriffsrechte weiterhin selbst.',
                max_length=20,
                verbose_name='Sichtbarkeit',
            ),
        ),
        migrations.RunPython(
            restrict_media_designer_navigation,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
