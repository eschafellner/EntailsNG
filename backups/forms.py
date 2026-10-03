from django import forms
from configuration.translations import get_translation


class CreateForm(forms.Form):
    description = forms.CharField(max_length=200, required=False)
    confirm = forms.BooleanField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].label = get_translation('backup_description')
        self.fields['confirm'].label = get_translation('backup_maintenance_confirm')


class UploadForm(forms.Form):
    file = forms.FileField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['file'].label = get_translation('backup_file')
        self.fields['file'].widget.attrs['accept'] = '.entailsbackup'


class RestoreForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput, strip=False)
    confirm = forms.BooleanField()

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields['password'].label = get_translation('backup_password')
        self.fields['confirm'].label = get_translation('backup_confirm')

    def clean_password(self):
        password = self.cleaned_data['password']
        if not self.user.check_password(password):
            raise forms.ValidationError(get_translation('backup_err_password'))
        return password
