from django.db import migrations, models


def number_existing_spaces(apps, schema_editor):
    KnowledgeSpace = apps.get_model('knowledge', 'KnowledgeSpace')
    # The overview has so far shown spaces in creation order; keep that visible order.
    spaces = list(KnowledgeSpace.objects.using(schema_editor.connection.alias).order_by('pk'))
    for position, space in enumerate(spaces, start=1):
        space.order = position * 10
    KnowledgeSpace.objects.using(schema_editor.connection.alias).bulk_update(spaces, ['order'])


class Migration(migrations.Migration):
    dependencies = [('knowledge', '0002_staff_navigation')]
    operations = [
        migrations.AddField(
            model_name='knowledgespace', name='order',
            field=models.PositiveIntegerField(default=0, verbose_name='Reihenfolge'),
        ),
        migrations.AlterModelOptions(
            name='knowledgespace',
            options={'ordering': ['order', 'name', 'pk'], 'verbose_name': 'Wissensbereich', 'verbose_name_plural': 'Wissensbereiche'},
        ),
        migrations.RunPython(number_existing_spaces, migrations.RunPython.noop),
    ]
