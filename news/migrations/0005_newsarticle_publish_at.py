import django.utils.timezone
from django.db import migrations, models


def copy_created_at(apps, schema_editor):
    """Bestehende News behalten ihr bisheriges Datum und ihre Reihenfolge."""
    NewsArticle = apps.get_model('news', 'NewsArticle')
    NewsArticle.objects.update(publish_at=models.F('created_at'))


class Migration(migrations.Migration):

    dependencies = [
        ('news', '0004_newsarticle_cover_image_newsarticle_cover_image_alt_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='newsarticle',
            name='publish_at',
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(copy_created_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='newsarticle',
            name='publish_at',
            field=models.DateTimeField(default=django.utils.timezone.now, help_text='Für eine geplante Veröffentlichung einen Zeitpunkt in der Zukunft eintragen. Zeitzone: Europe/Vienna.', verbose_name='Veröffentlichen ab'),
        ),
        migrations.AlterField(
            model_name='newsarticle',
            name='is_published',
            field=models.BooleanField(default=True, help_text='Nur veröffentlichte News werden Gästen im Frontend angezeigt, frühestens ab „Veröffentlichen ab“.', verbose_name='Veröffentlicht'),
        ),
        migrations.AlterModelOptions(
            name='newsarticle',
            options={'ordering': ['-is_pinned', '-publish_at', '-id'], 'verbose_name': 'News-Beitrag', 'verbose_name_plural': 'News-Beiträge'},
        ),
    ]
