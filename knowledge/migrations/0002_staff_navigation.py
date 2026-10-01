from django.db import migrations


def add_navigation(apps, schema_editor):
    NavigationItem = apps.get_model('configuration', 'NavigationItem')
    NavigationItem.objects.using(schema_editor.connection.alias).get_or_create(
        url_name='knowledge:home', defaults={
            'title': 'Wissensbasis', 'icon_name': 'rules', 'order': 10,
            'visibility': 'STAFF', 'is_active': True,
            'icon_svg': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 3H20v19H6.5A2.5 2.5 0 0 1 4 19.5v-14A2.5 2.5 0 0 1 6.5 3Z"/></svg>',
        })


class Migration(migrations.Migration):
    dependencies = [('knowledge', '0001_initial'), ('configuration', '0020_navigationitem_visibility')]
    operations = [migrations.RunPython(add_navigation, migrations.RunPython.noop)]
