from django.apps import AppConfig


class SeatingConfig(AppConfig):
    name = 'seating'

    def ready(self):
        import seating.signals  # noqa

