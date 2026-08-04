from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    class Roles(models.TextChoices):
        SUPERADMIN = 'SUPERADMIN', 'Superadmin'
        ADMIN = 'ADMIN', 'Admin'
        MODERATOR = 'MODERATOR', 'Moderator'
        USER = 'USER', 'Normaler User'

    # Standard-Rolle für neu registrierte Benutzer ist 'USER'
    role = models.CharField(
        max_length=20,
        choices=Roles.choices,
        default=Roles.USER,
        verbose_name="Rolle"
    )

    # Das einzige zusätzliche Stammdaten-Feld für den MVP:
    birthday = models.DateField(
        null=True,
        blank=True,
        verbose_name="Geburtsdatum"
    )



    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class EmailVerificationCode(models.Model):
    """Modell für den 6-stelligen Double Opt-In Verifizierungscode"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='verification_codes'
    )
    code = models.CharField(max_length=6, verbose_name="6-stelliger Code")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(verbose_name="Ablaufdatum")
    is_used = models.BooleanField(default=False, verbose_name="Verwendet")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "E-Mail Verifizierungscode"
        verbose_name_plural = "E-Mail Verifizierungscodes"

    def __str__(self):
        return f"Code {self.code} für {self.user.username} (Gültig bis {self.expires_at.strftime('%H:%i')})"

    def is_valid(self):
        from django.utils import timezone
        return not self.is_used and timezone.now() < self.expires_at

