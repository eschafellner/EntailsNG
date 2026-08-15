import os
from django import forms
from django.core.exceptions import ValidationError
from PIL import Image
from .models import Clan

MAX_LOGO_SIZE_BYTES = 2 * 1024 * 1024  # Maximal 2 Megabyte
MAX_DIMENSION = 300


def validate_clan_logo(file):
    """
    Validiert hochgeladene Clan-Logos sicher und robust:
    1. Dateiendung (.jpg, .jpeg, .png, .webp)
    2. Maximale Dateigröße (2 MB) zum Schutz vor DoS
    3. Echte Bild-Header & Dimensionen (max. 300x300 px) via Pillow
    """
    ext = os.path.splitext(file.name)[1].lower()
    valid_extensions = ['.jpg', '.jpeg', '.png', '.webp']
    if ext not in valid_extensions:
        raise ValidationError(
            f"Ungültiges Dateiformat '{ext}'. Erlaubte Formate: .jpg, .jpeg, .png, .webp"
        )

    # 1. Dateigrößen-Check vor dem Laden in den RAM
    file_size = getattr(file, 'size', None)
    if file_size and file_size > MAX_LOGO_SIZE_BYTES:
        raise ValidationError(
            f"Die Datei ist mit {file_size / (1024 * 1024):.1f} MB zu groß. Maximal erlaubt sind 2 MB."
        )

    # 2. Sichere Header-Prüfung mittels Pillow ohne Dekomprimierung der gesamten Pixeldaten
    try:
        file.seek(0)
        with Image.open(file) as img:
            img.verify()

        file.seek(0)
        with Image.open(file) as img:
            width, height = img.size
            if width > MAX_DIMENSION or height > MAX_DIMENSION:
                raise ValidationError(
                    f"Das Bild ist {width}x{height} Pixel groß. Maximal erlaubt sind {MAX_DIMENSION}x{MAX_DIMENSION} Pixel."
                )
    except ValidationError:
        raise
    except Exception:
        raise ValidationError("Die hochgeladene Datei ist kein gültiges oder ein beschädigtes Bild.")
    finally:
        file.seek(0)



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
        fields = ("name", "website", "logo", "password")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "z. B. Team Alternate"}),
            "website": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://clan.de"}),
            "logo": forms.FileInput(attrs={"class": "form-control", "accept": ".jpg,.jpeg,.png"}),
        }

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if logo and hasattr(logo, 'file'):
            validate_clan_logo(logo)
        return logo

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if not password and self.instance and self.instance.pk:
            # Keep existing password when editing and field is left blank
            return self.instance.password
        if not password and (not self.instance or not self.instance.pk):
            raise ValidationError("Bei der Neuerstellung eines Clans muss ein Passwort angegeben werden.")
        return password

    def save(self, commit=True):
        clan = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            if not (self.instance.pk and password == self.instance.password):
                clan.set_password(password)
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
