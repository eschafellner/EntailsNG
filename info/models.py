from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.text import slugify
from tinymce.models import HTMLField
from configuration.models import NavigationItem


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

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title) or 'info'

        super().save(*args, **kwargs)

        # Synchronisiere mit NavigationItem
        if self.show_in_nav:
            target_url = self.get_absolute_url()
            if self.nav_item:
                item = self.nav_item
                item.title = self.title
                item.url_name = target_url
                item.icon_name = self.nav_icon
                item.is_active = self.is_active
                item.save()
            else:
                item = NavigationItem.objects.create(
                    title=self.title,
                    url_name=target_url,
                    icon_name=self.nav_icon,
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


from django.db.models.signals import pre_delete, post_delete


@receiver(post_delete, sender=EventInfo)
def delete_nav_item_on_info_delete(sender, instance, **kwargs):
    if instance.nav_item_id:
        NavigationItem.objects.filter(pk=instance.nav_item_id).delete()


@receiver(pre_delete, sender=NavigationItem)
def update_info_page_on_nav_item_delete(sender, instance, **kwargs):
    EventInfo.objects.filter(nav_item=instance).update(show_in_nav=False, nav_item=None)

