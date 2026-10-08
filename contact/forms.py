from django import forms

from configuration.models import ContactCategory
from configuration.translations import get_translation as tr
from .tokens import read_submission_token


class ContactForm(forms.Form):
    email = forms.EmailField(max_length=254, widget=forms.EmailInput(attrs={
        'class': 'form-control', 'autocomplete': 'email', 'aria-describedby': 'contact-email-help',
    }))
    category = forms.ModelChoiceField(queryset=ContactCategory.objects.none(), widget=forms.Select(attrs={
        'class': 'form-control',
    }))
    message = forms.CharField(max_length=10000, widget=forms.Textarea(attrs={
        'class': 'form-control', 'rows': 9, 'aria-describedby': 'contact-message-help',
    }))
    submission_token = forms.CharField(max_length=2048, widget=forms.HiddenInput)
    website = forms.CharField(required=False, max_length=200, widget=forms.TextInput(attrs={
        'tabindex': '-1', 'autocomplete': 'off',
    }))

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.fields['category'].queryset = ContactCategory.objects.filter(
            configuration_id=1, is_active=True,
        ).only('id', 'name', 'order', 'is_active', 'configuration_id')
        self.fields['category'].empty_label = tr('contact_category_empty')
        for name in ('email', 'category', 'message'):
            self.fields[name].label = tr(f'contact_{name}_label')
            self.fields[name].error_messages['required'] = tr('contact_required')
        self.fields['email'].error_messages['invalid'] = tr('contact_invalid_email')
        self.fields['email'].error_messages['max_length'] = tr('contact_invalid_email')
        self.fields['category'].error_messages['invalid_choice'] = tr('contact_invalid_category')
        self.fields['message'].error_messages['max_length'] = tr('contact_message_too_long')
        self.fields['submission_token'].error_messages['required'] = tr('contact_invalid_token')
        self.fields['submission_token'].error_messages['max_length'] = tr('contact_invalid_token')
        self.fields['website'].error_messages['max_length'] = tr('contact_spam_error')
        if self.is_bound:
            for name in ('email', 'category', 'message'):
                if self[name].errors:
                    widget = self.fields[name].widget
                    widget.attrs['aria-invalid'] = 'true'
                    widget.attrs['aria-describedby'] = ' '.join(filter(None, (
                        widget.attrs.get('aria-describedby'), f'id_{name}_errors',
                    )))

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean_submission_token(self):
        token = self.cleaned_data['submission_token']
        read_submission_token(self.request, token)
        return token

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError(tr('contact_spam_error'))
        return ''
