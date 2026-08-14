import os
from django import forms
from django.core.exceptions import ValidationError
from struct import unpack
from .models import Clan


def validate_clan_logo(file):
    """
    Validates uploaded clan logo:
    1. File extension must be .jpg, .jpeg, or .png
    2. Image dimensions must be at most 300x300 pixels
    """
    ext = os.path.splitext(file.name)[1].lower()
    valid_extensions = ['.jpg', '.jpeg', '.png']
    if ext not in valid_extensions:
        raise ValidationError(
            f"Ungültiges Format '{ext}'. Bitte lade ein Bild im Format .jpg, .jpeg oder .png hoch."
        )

    # Validate image dimensions without Pillow by inspecting binary headers
    try:
        file.seek(0)
        content = file.read()
        width = None
        height = None

        if ext == '.png':
            if len(content) >= 24 and content[:8] == b'\x89PNG\r\n\x1a\n':
                width, height = unpack('>II', content[16:24])
        elif ext in ['.jpg', '.jpeg']:
            # Parse JPEG markers
            i = 0
            size = len(content)
            while i < size:
                if content[i] == 0xFF:
                    marker = content[i + 1] if i + 1 < size else 0
                    # SOF0..SOF15 (except DHT, JPG, DAC)
                    if marker in [0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF]:
                        if i + 8. < size:
                            height, width = unpack('>HH', content[i + 5:i + 9])
                            break
                    elif marker in [0xD8, 0xD9]:
                        i += 2
                    else:
                        if i + 3 < size:
                            length = unpack('>H', content[i + 2:i + 4])[0]
                            i += 2 + length
                        else:
                            break
                else:
                    i += 1

        file.seek(0)  # Reset pointer for saving

        if width is not None and height is not None:
            if width > 300 or height > 300:
                raise ValidationError(
                    f"Das Bild ist {width}x{height} Pixel groß. Maximal erlaubt sind 300x300 Pixel."
                )

    except ValidationError:
        raise
    except Exception:
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
