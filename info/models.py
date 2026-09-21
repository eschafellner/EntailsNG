from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.text import slugify
from tinymce.models import HTMLField

from configuration.cache import safe_cache_delete
from configuration.models import SYSTEM_ICONS, NavigationItem, sanitize_html


class EventInfo(models.Model):
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
        verbose_name="Inhalt",
        help_text="Hier kannst du den Haupttext verfassen und bequem formatieren.",
    )
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
                item.save()
            else:
                item = NavigationItem.objects.create(
                    title=self.title[:200],
                    url_name=target_url,
                    icon_name=self.nav_icon,
                    icon_svg=svg,
                    order=10 + self.order,
                    is_active=self.is_active,
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

