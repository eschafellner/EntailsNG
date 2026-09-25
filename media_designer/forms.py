from django import forms

from configuration.translations import get_translation
from media_designer.models import MediaTemplate
from media_designer.schema import default_elements


def translate_media_fields(form):
    labels = {
        'event': ('media_form_event', 'Veranstaltung'),
        'name': ('media_form_name', 'Name'),
        'kind': ('media_form_kind', 'Art'),
        'paper_size': ('media_form_paper_size', 'Format'),
        'background': ('media_form_background', 'Hintergrundbild'),
    }
    for field_name, (key, default) in labels.items():
        form.fields[field_name].label = get_translation(key, default)
    kind_labels = {
        MediaTemplate.Kind.BADGE: get_translation('media_kind_badge', 'Teilnehmerbadge'),
        MediaTemplate.Kind.CERTIFICATE: get_translation('media_kind_certificate', 'Turnierurkunde'),
    }
    form.fields['kind'].choices = [
        (value, kind_labels.get(value, label))
        for value, label in form.fields['kind'].choices
    ]


class MediaTemplateCreateForm(forms.ModelForm):
    class Meta:
        model = MediaTemplate
        fields = ('event', 'name', 'kind', 'paper_size', 'background')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        translate_media_fields(self)

    def save(self, commit=True):
        template = super().save(commit=False)
        template.elements = default_elements(template.kind)
        if commit:
            template.save()
        return template


class MediaTemplateForm(forms.ModelForm):
    class Meta:
        model = MediaTemplate
        fields = ('event', 'name', 'kind', 'paper_size', 'background', 'elements')
        widgets = {'elements': forms.HiddenInput}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        translate_media_fields(self)
        self.fields['kind'].disabled = True
