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

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet."
            )
        return email

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

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        query = User.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise forms.ValidationError(
                "Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet."
            )
        return email


from django.contrib.auth.forms import AuthenticationForm

class CustomAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Benutzername oder E-Mail-Adresse",
        widget=forms.TextInput(attrs={"class": "form-control", "autofocus": True}),
    )
    password = forms.CharField(
        label="Passwort",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    def clean(self):
        try:
            return super().clean()
        except forms.ValidationError:
            if getattr(self.request, 'account_locked', False):
                raise forms.ValidationError(
                    "Dein Konto wurde wegen 5 fehlerhafter Anmeldeversuche für 15 Minuten gesperrt. "
                    "Du kannst dein Passwort zurücksetzen, um die Sperre sofort aufzuheben."
                )
            raise forms.ValidationError(
                "Benutzername/E-Mail-Adresse oder Passwort ist falsch. Bitte versuche es erneut."
            )


class CustomPasswordResetForm(forms.Form):
    email = forms.EmailField(
        label="E-Mail-Adresse",
        max_length=254,
        widget=forms.EmailInput(attrs={"class": "form-control", "autofocus": True}),
    )

    def save(self, domain_override=None, subject_template_name=None, email_template_name=None, use_https=False, token_generator=None, from_email=None, request=None, html_email_template_name=None, extra_email_context=None):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        from emails.services import send_system_email

        email = self.cleaned_data["email"]
        if token_generator is None:
            token_generator = default_token_generator

        active_users = User.objects.filter(email__iexact=email, is_active=True)
        for user in active_users:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = token_generator.make_token(user)

            protocol = "https" if use_https else "http"
            domain = domain_override or (request.get_host() if request else "127.0.0.1:8000")
            reset_link = f"{protocol}://{domain}/password-reset-confirm/{uid}/{token}/"

            context_data = {
                "username": user.username,
                "full_name": user.get_full_name() or user.username,
                "reset_link": reset_link,
            }
            send_system_email("password_reset", user.email, context_data)


