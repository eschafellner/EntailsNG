import logging
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)
User = get_user_model()


def validate_birthday_date(birthday):
    if not birthday:
        return birthday
    today = timezone.now().date()
    if birthday > today:
        raise forms.ValidationError("Das Geburtsdatum darf nicht in der Zukunft liegen.")
    if birthday.year < 1900 or len(str(birthday.year)) != 4:
        raise forms.ValidationError("Bitte gib ein gültiges Geburtsdatum mit 4-stelligem Jahr an (ab 1900).")
    return birthday


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
            attrs={
                "class": "form-control",
                "type": "date",
                "min": "1900-01-01",
            }
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "birthday")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"class": "form-control"})
        # Maximales Datum dynamisch auf heute setzen
        today_str = timezone.now().date().isoformat()
        self.fields["birthday"].widget.attrs["max"] = today_str

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if '@' in username:
            raise forms.ValidationError("Der Benutzername darf kein @-Zeichen enthalten.")
        if User.objects.filter(email__iexact=username).exists():
            raise forms.ValidationError("Dieser Benutzername entspricht einer bereits registrierten E-Mail-Adresse.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet."
            )
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError(
                "Diese E-Mail-Adresse wird bereits als Benutzername verwendet."
            )
        return email

    def clean_birthday(self):
        birthday = self.cleaned_data.get('birthday')
        return validate_birthday_date(birthday)


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
            attrs={
                "class": "form-control",
                "type": "date",
                "min": "1900-01-01",
            }
        ),
    )

    class Meta:
        model = User
        fields = ("email", "birthday")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_email = self.instance.email if (self.instance and self.instance.pk) else ""
        self.pending_new_email = None
        today_str = timezone.now().date().isoformat()
        self.fields["birthday"].widget.attrs["max"] = today_str

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        query = User.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise forms.ValidationError(
                "Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet."
            )
        if User.objects.filter(username__iexact=email).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise forms.ValidationError(
                "Diese E-Mail-Adresse wird bereits als Benutzername verwendet."
            )
        return email

    def clean_birthday(self):
        birthday = self.cleaned_data.get('birthday')
        return validate_birthday_date(birthday)

    def save(self, commit=True):
        user = super().save(commit=False)
        submitted_email = self.cleaned_data.get('email', '').strip().lower()
        if self.original_email and submitted_email != self.original_email.lower():
            # Bisherige E-Mail beibehalten bis zur Double-Opt-In Bestätigung
            user.email = self.original_email
            self.pending_new_email = submitted_email
        else:
            self.pending_new_email = None

        if commit:
            # Punkt 2: Ausschließlich die tatsächlich bearbeiteten Profilfelder persistieren!
            # Sicherheitsfelder (is_active, locked_until, failed_login_attempts) dürfen nicht überschrieben werden.
            user.save(update_fields=['birthday'])
        return user


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
            if getattr(self.request, 'ip_rate_limited', False):
                raise forms.ValidationError(
                    "Zu viele fehlgeschlagene Anmeldeversuche von deiner IP-Adresse. "
                    "Bitte warte 5 Minuten, bevor du es erneut versuchst."
                )
            if getattr(self.request, 'account_locked', False):
                raise forms.ValidationError(
                    "Dein Konto wurde wegen 5 fehlerhafter Anmeldeversuche für 15 Minuten gesperrt. "
                    "Du kannst dein Passwort zurücksetzen, um die Sperre sofort aufzuheben."
                )
            if getattr(self.request, 'unverified_user', None):
                unverified = getattr(self.request, 'unverified_user')
                if self.request:
                    self.request.session['pending_verification_user_id'] = unverified.id
                raise forms.ValidationError(
                    "Dein Konto ist noch nicht aktiviert. Bitte bestätige deine E-Mail-Adresse mit deinem Bestätigungscode.",
                    code='unverified_account'
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
        from emails.services import queue_system_email
        from .auth_backends import get_client_ip

        email = self.cleaned_data["email"].strip().lower()

        # Rate Limiting: IP-basiert (max 5 Requests pro 10 Minuten)
        client_ip = get_client_ip(request) if request else '127.0.0.1'
        ip_key = f"rate_limit_pwd_reset_ip_{client_ip}"
        ip_count = cache.get(ip_key, 0)
        if ip_count >= 5:
            logger.warning("Password reset IP-Rate-Limit erreicht für IP %s", client_ip)
            return

        try:
            cache.set(ip_key, ip_count + 1, 600)
        except Exception:
            pass

        # Rate Limiting: E-Mail-basiert (max 3 Requests pro Stunde pro Zieladresse)
        email_key = f"rate_limit_pwd_reset_email_{email}"
        email_count = cache.get(email_key, 0)
        if email_count >= 3:
            logger.warning("Password reset E-Mail-Rate-Limit erreicht für %s", email)
            return

        try:
            cache.set(email_key, email_count + 1, 3600)
        except Exception:
            pass

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
            queue_system_email("password_reset", user.email, context_data)




