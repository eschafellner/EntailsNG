from django.apps import AppConfig
from django.db.models.signals import post_migrate


import logging

logger = logging.getLogger(__name__)


def seed_default_email_templates(sender, **kwargs):
    try:
        from emails.defaults import DEFAULT_EMAIL_TEMPLATES
        from emails.models import EmailTemplate, GeneralEmailSettings
        GeneralEmailSettings.load()
        for key, tpl_data in DEFAULT_EMAIL_TEMPLATES.items():
            EmailTemplate.objects.get_or_create(
                key=key,
                defaults=tpl_data,
            )
    except Exception as exc:
        logger.warning("Automatisches Seeding der E-Mail-Templates fehlgeschlagen: %s", exc)



class EmailsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'emails'
    verbose_name = 'E-Mail Konfiguration'

    def ready(self):
        post_migrate.connect(seed_default_email_templates, sender=self)

