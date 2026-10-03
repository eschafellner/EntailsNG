from django.apps import AppConfig


class TournamentsConfig(AppConfig):
    name = 'tournaments'

    def ready(self):
        from . import recruitment_signals  # noqa: F401
