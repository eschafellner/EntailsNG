from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import models
from django.urls import NoReverseMatch, reverse


class NavigationItem(models.Model):
    title = models.CharField(
        max_length=100,
        help_text='Anzeigename im Menü (z. B. Übersicht, Sitzplan)',
    )
    url_name = models.CharField(
        max_length=100,
        help_text='Django URL-Name, z. B. dashboard, news_list, seating_plan',
    )
    icon_svg = models.TextField(
        blank=True, help_text='SVG-Code für das Icon (20x20px empfohlen)'
    )
    badge_text = models.CharField(
        max_length=10, blank=True, default='',
        help_text='Optionales Badge, z. B. "2" oder "NEU"',
    )
    order = models.PositiveIntegerField(
        default=0, help_text='Kleinere Zahlen stehen weiter oben bzw. links'
    )
    is_active = models.BooleanField(default=True, help_text='Im Menü anzeigen?')

    ALIAS_MAP = {
        'info': 'event_info_detail',
        'seating': 'seating_plan',
        'news': 'news_list',
    }

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Menüpunkt'
        verbose_name_plural = 'Menüpunkte'

    def __str__(self):
        return f'{self.order}. {self.title} ({self.url_name})'

    def clean(self):
        """Verhindert Tippfehler: der URL-Name muss auflösbar sein."""
        target = self.ALIAS_MAP.get(self.url_name, self.url_name)
        try:
            reverse(target)
        except NoReverseMatch:
            raise ValidationError({
                'url_name': (
                    f'"{self.url_name}" ist kein bekannter URL-Name. '
                    'Gültig sind z. B.: dashboard, event_info_detail, '
                    'news_list, seating_plan.'
                )
            })

    def get_url(self):
        target = self.ALIAS_MAP.get(self.url_name, self.url_name)
        try:
            return reverse(target)
        except NoReverseMatch:
            return ''

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete('navigation_items')

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        cache.delete('navigation_items')


class SystemTranslation(models.Model):
    key = models.CharField(
        max_length=255,
        unique=True,
        help_text='Eindeutiger Übersetzungsschlüssel (z. B. seat_card_title)',
    )
    text = models.TextField(
        blank=True,
        default='',
        help_text='Der im Frontend angezeigte Text für diesen Schlüssel',
    )

    class Meta:
        ordering = ['key']
        verbose_name = 'Übersetzung'
        verbose_name_plural = 'Übersetzungen'

    def __str__(self):
        return f'{self.key}: {self.text[:30]}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete('system_translations')

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        cache.delete('system_translations')


class FeatureFlag(models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name='Feature Name',
        help_text='Lesbarer Name der Funktion (z. B. Onboarding Ticket)',
    )
    key = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Schlüssel (Key)',
        help_text='Eindeutiger Bezeichner (z. B. onboarding_ticket, seating_module)',
    )
    is_enabled = models.BooleanField(
        default=True,
        verbose_name='Aktiviert',
        help_text='Schaltet dieses Feature im System ein oder aus',
    )
    description = models.TextField(
        blank=True,
        verbose_name='Beschreibung',
        help_text='Erläuterung zur Funktion dieses Feature Flags',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'Feature Flag'
        verbose_name_plural = 'Feature Flags'

    def __str__(self):
        status = 'Aktiv' if self.is_enabled else 'Inaktiv'
        return f'{self.name} ({self.key}): {status}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete('feature_flags_dict')

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        cache.delete('feature_flags_dict')


