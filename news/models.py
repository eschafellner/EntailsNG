from django.conf import settings
from django.db import models
from django.core.validators import FileExtensionValidator
from django.utils.html import linebreaks, strip_tags
from django.utils.safestring import mark_safe
from django.utils.functional import cached_property

from .images import get_embedded_image, get_preview_text, validate_news_image_size


class NewsArticle(models.Model):
    title = models.CharField(max_length=200, verbose_name="Titel")
    content = models.TextField(verbose_name="Inhalt")
    cover_image = models.ImageField(
        upload_to="news/", blank=True, verbose_name="Titelbild",
        help_text="Optionales Vorschaubild. JPG, PNG oder WebP, maximal 10 MB. Fotos idealerweise im Querformat.",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"]), validate_news_image_size],
    )
    cover_image_alt = models.CharField(
        max_length=250, blank=True, verbose_name="Bildbeschreibung",
        help_text="Beschreibe den Bildinhalt für Besucher mit Screenreader.",
    )
    image_fit = models.CharField(
        max_length=10, default="cover", verbose_name="Bilddarstellung",
        choices=[("cover", "Foto: Vorschau proportional zuschneiden"),
                 ("contain", "Flyer: Bild vollständig anzeigen")],
        help_text="Gilt auch für die Vorschau eines vorhandenen Bildes im Artikeltext.",
    )
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

    @cached_property
    def preview_image(self):
        if self.cover_image:
            return {"url": self.cover_image.url, "alt": self.cover_image_alt}
        return get_embedded_image(self.content)

    @cached_property
    def preview_text(self):
        return get_preview_text(self.content)

    @property
    def rendered_content(self):
        """Render staff-authored HTML; preserve line breaks in existing plain text."""
        if strip_tags(self.content) == self.content:
            return mark_safe(linebreaks(self.content, autoescape=True))
        return mark_safe(self.content)
