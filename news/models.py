from django.conf import settings
from django.db import models


class NewsArticle(models.Model):
    title = models.CharField(max_length=200, verbose_name="Titel")
    content = models.TextField(verbose_name="Inhalt")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Autor",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Erstellt am"
    )
    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Zuletzt geändert"
    )
    is_published = models.BooleanField(
        default=True,
        verbose_name="Veröffentlicht",
        help_text="Nur veröffentlichte News werden Gästen im Frontend angezeigt.",
    )
    is_pinned = models.BooleanField(
        default=False,
        verbose_name="Angepinnt (Sticky Banner)",
        help_text="Wichtige Durchsage/Ankündigung oben auf dem Dashboard fixieren.",
    )

    class Meta:
        verbose_name = "News-Beitrag"
        verbose_name_plural = "News-Beiträge"
        ordering = ["-is_pinned", "-created_at", "-id"]  # Angepinnte Beiträge zuerst, dann neueste

    def __str__(self):
        return self.title
