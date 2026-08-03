from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

User = get_user_model()


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(
        label="E-Mail-Adresse",
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    birthday = forms.DateField(
        label="Geburtsdatum",
        required=True,
        widget=forms.DateInput(
            attrs={"class": "form-control", "type": "date"}
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "birthday")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # CSS-Klasse auch für den Usernamen setzen
        self.fields["username"].widget.attrs.update({"class": "form-control"})


class UserProfileForm(forms.ModelForm):
    email = forms.EmailField(
        label="E-Mail-Adresse",
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    birthday = forms.DateField(
        label="Geburtsdatum",
        required=False,
        widget=forms.DateInput(
            attrs={"class": "form-control", "type": "date"}
        ),
    )

    class Meta:
        model = User
        fields = ("email", "birthday")

