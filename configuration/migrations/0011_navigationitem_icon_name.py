from django.db import migrations, models


def set_default_icon_names(apps, schema_editor):
    NavigationItem = apps.get_model('configuration', 'NavigationItem')
    mapping = {
        'dashboard': 'dashboard',
        'tournament_list': 'tournaments',
        'tournaments': 'tournaments',
        'team_list': 'teams',
        'teams': 'teams',
        'seating_plan': 'seating',
        'seating': 'seating',
        'event_info_detail': 'info',
        'info': 'info',
        'news_list': 'news',
        'news': 'news',
        'clan_list': 'clans',
        'clans': 'clans',
    }
    for item in NavigationItem.objects.all():
        item.icon_name = mapping.get(item.url_name, 'dashboard')
        item.save(update_fields=['icon_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('configuration', '0010_generalconfiguration_debug_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='navigationitem',
            name='icon_name',
            field=models.CharField(
                choices=[
                    ('dashboard', 'Dashboard / Übersicht (Home)'),
                    ('tournaments', 'Turniere (Pokal / Trophy)'),
                    ('teams', 'Teams (Spielergruppe)'),
                    ('seating', 'Sitzplan (Raster / Grid)'),
                    ('info', 'Informationen (Info-Kreis)'),
                    ('news', 'Neuigkeiten (Zeitung / Feed)'),
                    ('clans', 'Clans (Schild / Wappen)'),
                    ('rules', 'Regeln & FAQ (Buch / Dokument)'),
                    ('support', 'Support & Hilfe (Rettungsring)'),
                    ('shop', 'Shop & Catering (Einkaufswagen)'),
                    ('settings', 'Einstellungen (Regler)'),
                    ('custom', 'Benutzerdefiniertes SVG (Nur Superuser)'),
                ],
                default='dashboard',
                help_text='Wähle ein sicheres Standard-Icon aus der Liste.',
                max_length=50,
                verbose_name='Icon-Auswahl',
            ),
        ),
        migrations.AlterField(
            model_name='navigationitem',
            name='icon_svg',
            field=models.TextField(
                blank=True,
                help_text='Optionaler SVG-Code für das Icon (nur bei Auswahl "Benutzerdefiniertes SVG")',
            ),
        ),
        migrations.RunPython(
            set_default_icon_names,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
