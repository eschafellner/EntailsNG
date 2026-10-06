from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.text import slugify
from tinymce.models import HTMLField

from configuration.cache import safe_cache_delete
from configuration.models import SYSTEM_ICONS, NavigationItem, sanitize_html
from .embedding import https_origin, validate_embed_origin
from configuration.translations import get_translation


class EmbedProvider(models.Model):
    name = models.CharField(max_length=200, verbose_name='Name')
    origin = models.URLField(
        max_length=255, unique=True, validators=[validate_embed_origin],
        verbose_name='Erlaubte HTTPS-Origin',
        help_text='Nur Schema, Host und optional Port, z. B. https://galerie.example.com.',
    )
    is_active = models.BooleanField(default=True, verbose_name='Einbettung freigegeben?')

    class Meta:
        ordering = ['name', 'id']
        verbose_name = 'Einbettungsanbieter'
        verbose_name_plural = 'Einbettungsanbieter'

    def __str__(self):
        return f'{self.name} ({self.origin})'

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class EventInfo(models.Model):
    class PageType(models.TextChoices):
        TEXT = 'TEXT', 'Textseite'
        EMBED = 'EMBED', 'Externe Einbettung'

    class EmbedProfile(models.TextChoices):
        STATIC = 'STATIC', 'Statische Seite (ohne JavaScript)'
        GALLERY = 'GALLERY', 'Interaktive Galerie (JavaScript, Speicher, Downloads, Vollbild)'

    title = models.CharField(
        max_length=200,
        verbose_name="Seitentitel",
        default="Veranstaltungsinformationen",
    )
    slug = models.SlugField(
        max_length=100,
        unique=True,
        default="allgemein",
        verbose_name="URL-Kürzel (Slug)",
        help_text="Wird für die URL verwendet (z. B. 'allgemein', 'catering', 'regeln').",
    )
    subtitle = models.CharField(
        max_length=300,
        verbose_name="Untertitel",
        blank=True,
        default="Alle Fakten zur LAN im Überblick",
    )
    content = HTMLField(
        blank=True,
        verbose_name="Inhalt",
        help_text="Hier kannst du den Haupttext verfassen und bequem formatieren.",
    )
    page_type = models.CharField(
        max_length=10, choices=PageType.choices, default=PageType.TEXT, verbose_name='Seitentyp',
    )
    embed_provider = models.ForeignKey(
        EmbedProvider, on_delete=models.PROTECT, null=True, blank=True,
        verbose_name='Einbettungsanbieter',
    )
    embed_url = models.URLField(
        max_length=2048, blank=True, default='', verbose_name='Einbettungsadresse',
        help_text='HTTPS-Adresse auf der freigegebenen Origin. Keine Zugangsdaten eintragen.',
    )
    embed_profile = models.CharField(
        max_length=10, choices=EmbedProfile.choices, default=EmbedProfile.GALLERY,
        verbose_name='Einbettungsprofil',
    )
    embed_height = models.PositiveIntegerField(
        default=800, validators=[MinValueValidator(320), MaxValueValidator(2000)],
        verbose_name='Rahmenhöhe (Pixel)', help_text='Zwischen 320 und 2000 Pixeln.',
    )
    embed_wide = models.BooleanField(default=True, verbose_name='Breite Ansicht verwenden?')
    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Reihenfolge",
        help_text="Bestimmt die Position in der Tab-Leiste und im Menü.",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Veröffentlicht?",
        help_text="Inaktive Seiten sind für normale Besucher nicht sichtbar.",
    )
    login_required = models.BooleanField(
        default=False,
        verbose_name="Nur für angemeldete Benutzer?",
        help_text="Schützt sensible Informationen (z. B. WLAN-Zugang, Vor-Ort-Hinweise).",
    )
    show_in_nav = models.BooleanField(
        default=False,
        verbose_name="In Hauptnavigation anzeigen?",
        help_text="Erstellt automatisch einen Menüpunkt in der linken Seitenleiste.",
    )
    nav_icon = models.CharField(
        max_length=50,
        choices=NavigationItem.IconChoices.choices,
        default=NavigationItem.IconChoices.INFO,
        verbose_name="Menü-Icon",
        help_text="Icon für den Menüpunkt, falls im Hauptmenü angezeigt.",
    )
    nav_item = models.OneToOneField(
        NavigationItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='info_page',
        verbose_name="Verknüpfter Menüpunkt",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name="Erstellt am",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Zuletzt geändert",
    )

    class Meta:
        verbose_name = "Inhaltsseite / Infoseite"
        verbose_name_plural = "Inhaltsseiten / Infoseiten"
        ordering = ['order', 'id']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('event_info_page', kwargs={'slug': self.slug})

    @property
    def is_embed(self):
        return self.page_type == self.PageType.EMBED

    @property
    def embed_sandbox(self):
        if self.embed_profile == self.EmbedProfile.GALLERY:
            return 'allow-scripts allow-same-origin allow-downloads'
        return ''

    def validate_embedding(self):
        if not self.is_embed:
            return
        if not self.embed_provider_id:
            raise ValidationError({'embed_provider': get_translation('info_embed_provider_required')})
        if not self.embed_provider.is_active:
            raise ValidationError({'embed_provider': get_translation('info_embed_provider_disabled')})
        try:
            validate_embed_origin(self.embed_provider.origin)
        except ValidationError as exc:
            raise ValidationError({'embed_provider': exc.messages}) from exc
        try:
            origin = https_origin(self.embed_url)
        except ValidationError as exc:
            raise ValidationError({'embed_url': exc.messages}) from exc
        if origin != self.embed_provider.origin:
            raise ValidationError({'embed_url': get_translation('info_embed_url_mismatch')})
        if self.embed_profile not in self.EmbedProfile.values:
            raise ValidationError({'embed_profile': get_translation('info_embed_invalid_profile')})
        if not isinstance(self.embed_height, int):
            raise ValidationError({'embed_height': get_translation('info_embed_invalid_height')})
        for validator in (MinValueValidator(320), MaxValueValidator(2000)):
            try:
                validator(self.embed_height)
            except ValidationError as exc:
                raise ValidationError({'embed_height': exc.messages}) from exc

    def _generate_unique_slug(self):
        base_slug = slugify(self.title) or 'info'
        slug = base_slug
        counter = 2
        qs = EventInfo.objects.all()
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        while qs.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug

    def clean(self):
        super().clean()
        self.validate_embedding()
        if self.page_type == self.PageType.TEXT and not self.content:
            raise ValidationError({'content': get_translation('info_text_content_required')})
        if self.content:
            self.content = sanitize_html(self.content)

        if not self.slug:
            self.slug = self._generate_unique_slug()

        if self.show_in_nav:
            if len(self.title) > 200:
                raise ValidationError({
                    'title': 'Der Seitentitel darf bei Anzeige im Menü maximal 200 Zeichen lang sein.'
                })
            expected_slug = self.slug or 'info'
            url_path = f"/info/{expected_slug}/"
            if len(url_path) > 255:
                raise ValidationError({
                    'slug': f'Die Menü-Zieladresse darf maximal 255 Zeichen lang sein (aktuell: {len(url_path)}).'
                })

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.validate_embedding()
        if self.content:
            self.content = sanitize_html(self.content)

        if not self.slug:
            self.slug = self._generate_unique_slug()
        else:
            qs = EventInfo.objects.filter(slug=self.slug)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                self.slug = self._generate_unique_slug()

        super().save(*args, **kwargs)

        # Synchronisiere mit NavigationItem
        if self.show_in_nav:
            target_url = self.get_absolute_url()
            svg = SYSTEM_ICONS.get(self.nav_icon, '')
            if self.nav_item:
                item = self.nav_item
                item.title = self.title[:200]
                item.url_name = target_url
                item.icon_name = self.nav_icon
                item.icon_svg = svg
                item.order = 10 + self.order
                item.is_active = self.is_active
                if item.visibility != NavigationItem.Visibility.STAFF:
                    item.visibility = (
                        NavigationItem.Visibility.AUTHENTICATED if self.login_required
                        else NavigationItem.Visibility.PUBLIC
                    )
                item.save()
            else:
                item = NavigationItem.objects.create(
                    title=self.title[:200],
                    url_name=target_url,
                    icon_name=self.nav_icon,
                    icon_svg=svg,
                    order=10 + self.order,
                    is_active=self.is_active,
                    visibility=(NavigationItem.Visibility.AUTHENTICATED if self.login_required
                                else NavigationItem.Visibility.PUBLIC),
                )
                EventInfo.objects.filter(pk=self.pk).update(nav_item=item)
                self.nav_item = item
        else:
            if self.nav_item:
                old_item = self.nav_item
                EventInfo.objects.filter(pk=self.pk).update(nav_item=None)
                old_item.delete()
                self.nav_item = None

    def delete(self, *args, **kwargs):
        if self.nav_item:
            self.nav_item.delete()
        super().delete(*args, **kwargs)


@receiver(post_delete, sender=EventInfo)
def delete_nav_item_on_info_delete(sender, instance, **kwargs):
    if instance.nav_item_id:
        NavigationItem.objects.filter(pk=instance.nav_item_id).delete()
        safe_cache_delete('navigation_items')


@receiver(pre_delete, sender=NavigationItem)
def update_info_page_on_nav_item_delete(sender, instance, **kwargs):
    EventInfo.objects.filter(nav_item=instance).update(show_in_nav=False, nav_item=None)
