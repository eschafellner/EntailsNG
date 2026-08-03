from django.db import models
from tinymce.models import HTMLField  # <-- NEUER IMPORT


class EventInfo(models.Model):
    title = models.CharField(
        max_length=200,
        verbose_name="Seitentitel",
        default="Veranstaltungsinformationen",
    )
    subtitle = models.CharField(
        max_length=300,
        verbose_name="Untertitel",
        blank=True,
        default="Alle Fakten zur LAN im Überblick",
    )

    # Hier nutzen wir jetzt das HTMLField statt TextField:
    content = HTMLField(
        verbose_name="Inhalt",
        help_text="Hier kannst du den Haupttext verfassen und bequem formatieren.",
    )

    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Zuletzt geändert"
    )

    class Meta:
        verbose_name = "Veranstaltungsinformation"
        verbose_name_plural = "Veranstaltungsinformationen"

    def __str__(self):
        return self.title
