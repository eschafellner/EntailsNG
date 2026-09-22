import logging
from django.apps import AppConfig
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)


def seed_default_system_translations(sender, **kwargs):
    try:
        from configuration.translations import DEFAULT_TEXTS
        from configuration.models import SystemTranslation

        for key, text in DEFAULT_TEXTS.items():
            SystemTranslation.objects.get_or_create(
                key=key, defaults={'text': text}
            )
    except Exception as e:
        logger.error("Failed to seed default system translations: %s", e, exc_info=True)


class ConfigurationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'configuration'
    verbose_name = 'Konfiguration'

    def ready(self):
        post_migrate.connect(seed_default_system_translations, sender=self)
