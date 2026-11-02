import os
from io import BytesIO

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.contrib.auth.password_validation import validate_password
from PIL import Image, ImageOps, UnidentifiedImageError
from .models import Clan

# Knapp unter client_max_body_size von nginx (25 MB), damit eine Formularmeldung statt HTTP 413 erscheint.
MAX_LOGO_SIZE_BYTES = 20 * 1024 * 1024
# Schützt den Speicher: Die Pixelzahl lässt sich an der Dateigröße nicht ablesen.
MAX_LOGO_PIXELS = 40_000_000
MAX_LOGO_EDGE = 500
LOGO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
LOGO_FORMATS = {'JPEG', 'PNG', 'WEBP'}


def normalize_clan_logo(upload):
    """
    Prüft ein hochgeladenes Logo und kodiert es neu, ohne Metadaten und mit höchstens 500 px Kantenlänge.
    JPEG bleibt JPEG; PNG und WebP werden zu PNG, damit Transparenz erhalten bleibt.
    """
    base_name, extension = os.path.splitext(os.path.basename(upload.name))
    if extension.lower() not in LOGO_EXTENSIONS:
        raise ValidationError(
            f"Ungültiges Dateiformat '{extension}'. Erlaubte Formate: .jpg, .jpeg, .png, .webp"
        )
    if upload.size > MAX_LOGO_SIZE_BYTES:
        raise ValidationError(
            f"Die Datei ist mit {upload.size / (1024 * 1024):.1f} MB zu groß. "
            f"Maximal erlaubt sind {MAX_LOGO_SIZE_BYTES // (1024 * 1024)} MB."
        )

    invalid = ValidationError("Die hochgeladene Datei ist kein gültiges oder ein beschädigtes Bild.")
    try:
        upload.seek(0)
        with Image.open(upload) as image:
            if image.format not in LOGO_FORMATS:
                raise invalid
            width, height = image.size
            if width * height > MAX_LOGO_PIXELS:
                raise ValidationError(
                    f"Das Bild ist mit {width}x{height} Pixeln zu groß. "
                    f"Maximal erlaubt sind {MAX_LOGO_PIXELS // 1_000_000} Megapixel."
                )
            is_jpeg = image.format == 'JPEG'
            if is_jpeg:
                image.draft('RGB', (MAX_LOGO_EDGE * 2, MAX_LOGO_EDGE * 2))
            # Ausrichtung übernehmen, bevor die Metadaten verworfen werden.
            logo = ImageOps.exif_transpose(image).convert('RGB' if is_jpeg else 'RGBA')
        logo.thumbnail((MAX_LOGO_EDGE, MAX_LOGO_EDGE))
        output = BytesIO()
        if is_jpeg:
            logo.save(output, format='JPEG', quality=90, optimize=True)
        else:
            logo.save(output, format='PNG', optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise invalid
    finally:
        upload.seek(0)
    return ContentFile(output.getvalue(), name=f"{base_name}{'.jpg' if is_jpeg else '.png'}")


class ClanForm(forms.ModelForm):
    password = forms.CharField(
        label="Clan-Passwort",
        required=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Passwort für Beitritt (unverändert lassen wenn leer)"}
        ),
        help_text="Passwort, mit dem andere Gäste dem Clan sofort beitreten können.",
    )

    class Meta:
        model = Clan
        fields = ("name", "tag", "website", "logo", "password")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "z. B. Team Alternate", "maxlength": "32"}),
            "tag": forms.TextInput(attrs={"class": "form-control", "placeholder": "z. B. HNX", "maxlength": "5"}),
            # URLField adds https:// server-side; type="url" would reject bare domains in the browser.
            "website": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "www.clan.at",
                "inputmode": "url", "autocapitalize": "none", "spellcheck": "false",
            }),
            "logo": forms.FileInput(attrs={"class": "form-control", "accept": ".jpg,.jpeg,.png,.webp"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_password = self.instance.password if self.instance.pk else ''
        self._password_changed = False

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if len(name) > 32:
            raise ValidationError("Der Clanname darf maximal 32 Zeichen lang sein.")
        return name

    def clean_tag(self):
        tag = self.cleaned_data.get('tag', '').strip().upper()
        if len(tag) > 5:
            raise ValidationError("Der Clan-Tag darf maximal 5 Zeichen lang sein.")
        return tag

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        # Ohne neuen Upload liefert das Feld das gespeicherte Logo; das bleibt unverändert.
        if isinstance(logo, UploadedFile):
            return normalize_clan_logo(logo)
        return logo

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not password and self.instance and self.instance.pk:
            # Keep existing password when editing and field is left blank
            return self._original_password
        if not password and (not self.instance or not self.instance.pk):
            raise ValidationError("Bei der Neuerstellung eines Clans muss ein Passwort angegeben werden.")
        validate_password(password)
        self._password_changed = bool(password)
        return password

    def save(self, commit=True):
        clan = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if self._password_changed:
            clan.set_password(password)
        else:
            clan.password = self._original_password
        if commit:
            clan.save()
            self.save_m2m()
        return clan


class ClanJoinPasswordForm(forms.Form):
    password = forms.CharField(
        label="Clan-Passwort eingeben",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Clan-Passwort"}
        ),
    )
