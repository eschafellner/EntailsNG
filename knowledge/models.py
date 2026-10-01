import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse

from .content import sanitize_content
from .storage import attachment_path, private_storage


class KnowledgeSpace(models.Model):
    name = models.CharField('Bereich', max_length=150)
    description = models.CharField('Beschreibung', max_length=500, blank=True)
    event = models.ForeignKey('events.Event', on_delete=models.SET_NULL, null=True, blank=True, related_name='knowledge_spaces', verbose_name='Veranstaltung')
    version = models.PositiveIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'pk']
        verbose_name = 'Wissensbereich'
        verbose_name_plural = 'Wissensbereiche'

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('knowledge:space', args=[self.pk])


class KnowledgePage(models.Model):
    space = models.ForeignKey(KnowledgeSpace, on_delete=models.CASCADE, related_name='pages', verbose_name='Bereich')
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='children', verbose_name='Übergeordnete Seite')
    title = models.CharField('Titel', max_length=200)
    content = models.TextField('Inhalt', blank=True)
    search_text = models.TextField(blank=True, editable=False)
    order = models.PositiveIntegerField('Reihenfolge', default=0)
    version = models.PositiveIntegerField(default=0, editable=False)
    published_revision = models.ForeignKey('KnowledgeRevision', on_delete=models.SET_NULL, null=True, blank=True, related_name='+', editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+', editable=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'title', 'pk']
        verbose_name = 'Wissensseite'
        verbose_name_plural = 'Wissensseiten'

    @property
    def display_title(self):
        return self.published_revision.title if self.published_revision_id else self.title

    @property
    def has_draft(self):
        return not self.published_revision_id or self.published_revision.number != self.version

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('knowledge:page', args=[self.pk])


class KnowledgeRevision(models.Model):
    page = models.ForeignKey(KnowledgePage, on_delete=models.CASCADE, related_name='revisions')
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True)
    search_text = models.TextField(blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    note = models.CharField('Änderungsnotiz', max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-number']
        constraints = [models.UniqueConstraint(fields=['page', 'number'], name='knowledge_unique_revision')]
        verbose_name = 'Seitenversion'
        verbose_name_plural = 'Seitenversionen'

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Gespeicherte Seitenversionen können nicht verändert werden.')
        self.content = sanitize_content(self.content)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.title} – Version {self.number}'


class KnowledgeAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(KnowledgePage, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(storage=private_storage, upload_to=attachment_path, max_length=300)
    original_name = models.CharField(max_length=200)
    size = models.PositiveIntegerField()
    mime_type = models.CharField(max_length=80, default='application/octet-stream')
    is_image = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['original_name', 'pk']
        verbose_name = 'Interner Anhang'
        verbose_name_plural = 'Interne Anhänge'

    def get_absolute_url(self):
        return reverse('knowledge:attachment', args=[self.pk])

    @property
    def image_url(self):
        return self.get_absolute_url() + '?inline=1'

    def __str__(self):
        return self.original_name
