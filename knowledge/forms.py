import re
from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError
from tinymce.widgets import TinyMCE

from events.models import Event
from configuration.translations import get_translation
from .models import KnowledgeSpace, KnowledgePage


def translate_labels(form):
    labels = {'name': 'Bereich', 'description': 'Beschreibung', 'event': 'Veranstaltung',
        'title': 'Titel', 'parent': 'Übergeordnete Seite', 'order': 'Reihenfolge',
        'content': 'Inhalt', 'note': 'Änderungsnotiz', 'file': 'Datei'}
    for field, label in labels.items():
        if field in form.fields:
            form.fields[field].label = get_translation('knowledge_field_' + field, label)


class SpaceForm(forms.ModelForm):
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    class Meta:
        model = KnowledgeSpace
        fields = ['name', 'description', 'event']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        translate_labels(self)
        self.fields['event'].queryset = Event.objects.order_by('-start_date', 'pk')
        self.fields['event'].empty_label = get_translation('knowledge_global', 'Veranstaltungsübergreifend')
        self.fields['expected_version'].initial = self.instance.version if self.instance.pk else 0


class PageForm(forms.Form):
    title = forms.CharField(label='Titel', max_length=200)
    parent = forms.ModelChoiceField(label='Übergeordnete Seite', queryset=KnowledgePage.objects.none(), required=False)
    order = forms.IntegerField(label='Reihenfolge', min_value=0, max_value=100000, initial=0)
    content = forms.CharField(label='Inhalt', required=False, max_length=500000, widget=TinyMCE(mce_attrs={
        'height': 540, 'menubar': False, 'license_key': 'gpl',
        'plugins': 'lists link image table code searchreplace',
        'toolbar': 'undo redo | blocks | bold italic | bullist numlist | link image table | removeformat code',
        'branding': False, 'promotion': False, 'relative_urls': False, 'remove_script_host': True,
        'images_upload_handler': 'knowledgeUploadImage', 'paste_data_images': False,
    }))
    note = forms.CharField(label='Änderungsnotiz', max_length=255, required=False)
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(self, *args, space, page=None, parent=None, **kwargs):
        initial = kwargs.setdefault('initial', {})
        initial.update({'expected_version': page.version if page else 0})
        if page:
            initial.update({'title': page.title, 'content': page.content, 'parent': page.parent_id, 'order': page.order})
        elif parent:
            initial['parent'] = parent.pk
        super().__init__(*args, **kwargs)
        translate_labels(self)
        self.fields['parent'].queryset = space.pages.exclude(pk=page.pk if page else None).select_related('published_revision')
        self.fields['parent'].label_from_instance = lambda item: item.display_title
        self.fields['parent'].empty_label = get_translation('knowledge_root', 'Oberste Ebene')


class VersionForm(forms.Form):
    expected_version = forms.IntegerField(min_value=0)


class AttachmentForm(forms.Form):
    file = forms.FileField(label='Datei', max_length=200)
    metadata = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        translate_labels(self)

    def clean_file(self):
        upload = self.cleaned_data['file']
        name = re.split(r'[/\\]', upload.name)[-1]
        extension = Path(name).suffix.lower()
        image_formats = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP'}
        allowed = set(image_formats) | {'.pdf', '.txt', '.md', '.csv', '.docx', '.xlsx', '.odt', '.ods', '.zip'}
        if extension not in allowed:
            raise ValidationError(get_translation('knowledge_file_type', 'Erlaubt sind PNG, JPG, WebP, PDF, Text, Markdown, CSV, DOCX, XLSX, ODT, ODS und ZIP.'))
        if upload.size > 10 * 1024 * 1024:
            raise ValidationError(get_translation('knowledge_file_size', 'Eine Datei darf höchstens 10 MB groß sein.'))
        mime, is_image = 'application/octet-stream', extension in image_formats
        if is_image:
            try:
                with Image.open(upload) as image:
                    if image.format != image_formats[extension] or image.width * image.height > 25000000:
                        raise ValueError('Invalid image')
                    image.verify()
                mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}[image_formats[extension]]
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                raise ValidationError(get_translation('knowledge_file_image', 'Das Bild ist beschädigt, zu groß oder passt nicht zur Dateiendung.'))
            finally:
                upload.seek(0)
        self.metadata = {'original_name': name, 'size': upload.size, 'mime_type': mime, 'is_image': is_image}
        return upload
