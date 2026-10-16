from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('configuration', '0024_contact_form')]
    operations = [migrations.CreateModel(name='DemoDataset', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('name', models.CharField(max_length=64, unique=True)),
        ('version', models.PositiveIntegerField()),
        ('objects_manifest', models.JSONField(default=list)),
        ('created_at', models.DateTimeField(auto_now_add=True)),
    ])]
