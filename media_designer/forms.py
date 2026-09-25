from django import forms

from media_designer.models import MediaTemplate
from media_designer.schema import default_elements


class MediaTemplateCreateForm(forms.ModelForm):
    class Meta:
        model = MediaTemplate
        fields = ('event', 'name', 'kind', 'paper_size', 'background')

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
        self.fields['kind'].disabled = True
