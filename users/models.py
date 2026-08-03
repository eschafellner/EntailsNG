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
