from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import ContactCategory


class ContactCategoryFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors) or not self.instance.contact_enabled:
            return
        if not any(
            form.cleaned_data.get('is_active') and not form.cleaned_data.get('DELETE')
            for form in self.forms
        ):
            raise ValidationError('Für das aktivierte Kontaktformular muss mindestens eine Betreffkategorie aktiv sein.')


class ContactCategoryInline(admin.TabularInline):
    model = ContactCategory
    formset = ContactCategoryFormSet
    fields = ('name', 'recipient_emails', 'order', 'is_active')
    extra = 1
