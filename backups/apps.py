from django.apps import AppConfig


class BackupsConfig(AppConfig):
    name = 'backups'
    verbose_name = 'Backups'

    def ready(self):
        from . import checks  # noqa: F401
