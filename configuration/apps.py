from django.apps import AppConfig
from django.db.models.signals import post_migrate


def seed_default_system_translations(sender, **kwargs):
    try:
        from configuration.context_processors import DEFAULT_TEXTS
        from configuration.models import SystemTranslation

        for key, text in DEFAULT_TEXTS.items():
            SystemTranslation.objects.get_or_create(
                key=key, defaults={'text': text}
            )
    except Exception:
        pass


class ConfigurationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'configuration'
    verbose_name = 'Konfiguration'

    def ready(self):
        post_migrate.connect(seed_default_system_translations, sender=self)
