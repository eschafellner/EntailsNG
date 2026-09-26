from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from configuration.translations import get_translation
from media_designer.schema import PAPER_MM, validate_elements
from media_designer.validators import validate_background_image, validate_font_file


class MediaFont(models.Model):
    name = models.CharField(max_length=120, unique=True, verbose_name='Schriftname')
    file = models.FileField(
        upload_to='media_fonts/', verbose_name='Schriftdatei',
        help_text='TTF, OTF oder WOFF2 bis 5 MB. Beim Löschen verwenden betroffene Vorlagenfelder die Standardschrift.',
        validators=[FileExtensionValidator(['ttf', 'otf', 'woff2']), validate_font_file],
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'Medienschrift'
        verbose_name_plural = 'Medienschriften'

    def __str__(self):
        return self.name


class MediaTemplate(models.Model):
    class Kind(models.TextChoices):
        BADGE = 'BADGE', 'Teilnehmerbadge'
        CERTIFICATE = 'CERTIFICATE', 'Turnierurkunde'

    event = models.ForeignKey('events.Event', on_delete=models.CASCADE, related_name='media_templates', verbose_name='Veranstaltung')
    name = models.CharField(max_length=120, verbose_name='Name')
    kind = models.CharField(max_length=20, choices=Kind.choices, verbose_name='Art')
    paper_size = models.CharField(max_length=2, choices=[(key, key) for key in PAPER_MM], verbose_name='Format')
    background = models.ImageField(
        upload_to='media_templates/', blank=True, verbose_name='Hintergrundbild',
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp']), validate_background_image],
    )
    elements = models.JSONField(default=list, blank=True)
    schema_version = models.PositiveSmallIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['event__start_date', 'name']
        verbose_name = 'Medienvorlage'
        verbose_name_plural = 'Medienvorlagen'

    def clean(self):
        if self.schema_version != 1:
            raise ValidationError(get_translation('media_error_version', 'Unbekannte Vorlagenversion.'))
        if self.kind == self.Kind.CERTIFICATE and self.paper_size != 'A4':
            raise ValidationError({'paper_size': get_translation('media_error_certificate_size', 'Urkunden verwenden in dieser Version A4.')})
        if self.kind == self.Kind.BADGE and self.paper_size not in ('A6', 'A7', 'A8'):
            raise ValidationError({'paper_size': get_translation('media_error_badge_size', 'Badges verwenden A6, A7 oder A8.')})
        try:
            validate_elements(self.elements, self.kind)
        except ValidationError as exc:
            raise ValidationError({'elements': exc}) from exc

    def __str__(self):
        return f'{self.name} ({self.event.title})'


@receiver(post_delete, sender=MediaFont)
def reset_deleted_font(sender, instance, using, **kwargs):
    """Entfernt gelöschte Schriftverweise auch bei Admin-Sammellöschungen."""
    for template in MediaTemplate.objects.using(using).only('pk', 'elements').iterator():
        changed = False
        for element in template.elements:
            if element.get('font_id') == instance.pk:
                element.pop('font_id')
                changed = True
        if changed:
            MediaTemplate.objects.using(using).filter(pk=template.pk).update(elements=template.elements)

    if instance.file.name:
        name, storage = instance.file.name, instance.file.storage
        transaction.on_commit(lambda: storage.delete(name), using=using)
