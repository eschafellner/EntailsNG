from django.contrib.auth.models import AbstractUser, UserManager as BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def _create_user(self, username, email, password, **extra_fields):
        if not email:
            email = f"{str(username).lower()}@entailsng.local"
        email = self.normalize_email(email)
        return super()._create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    class Roles(models.TextChoices):
        SUPERADMIN = 'SUPERADMIN', 'Superadmin'
        ADMIN = 'ADMIN', 'Admin'
        MODERATOR = 'MODERATOR', 'Moderator'
        USER = 'USER', 'Normaler User'

    objects = UserManager()

    # Standard-Rolle für neu registrierte Benutzer ist 'USER'
    role = models.CharField(
        max_length=20,
        choices=Roles.choices,
        default=Roles.USER,
        verbose_name="Rolle"
    )

    # E-Mail-Adresse ist eindeutig (Single Source of Truth)
    email = models.EmailField(
        unique=True,
        verbose_name="E-Mail-Adresse",
        error_messages={
            'unique': "Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet.",
        },
    )

    # Stammdaten-Feld
    birthday = models.DateField(
        null=True, blank=True, verbose_name="Geburtsdatum"
    )

    # Sicherheit & Login-Sperre
    failed_login_attempts = models.PositiveIntegerField(
        default=0, verbose_name="Fehlgeschlagene Anmeldeversuche"
    )
    locked_until = models.DateTimeField(
        null=True, blank=True, verbose_name="Gesperrt bis"
    )

    def save(self, *args, **kwargs):
        if not self.email:
            self.email = f"{str(self.username).lower()}@entailsng.local"
        super().save(*args, **kwargs)


    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    def is_locked(self):
        from django.utils import timezone
        if self.locked_until:
            if timezone.now() < self.locked_until:
                return True
            # Sperrzeit ist abgelaufen -> Zähler & Sperre automatisch zurücksetzen!
            self.reset_lockout()
        return False

    def register_failed_login(self):
        from datetime import timedelta
        from django.utils import timezone

        # Falls die vorherige Sperre bereits abgelaufen ist, Zähler zurücksetzen
        if self.locked_until and timezone.now() >= self.locked_until:
            self.failed_login_attempts = 0
            self.locked_until = None

        self.failed_login_attempts += 1
        if self.failed_login_attempts >= 5:
            self.locked_until = timezone.now() + timedelta(minutes=15)
        self.save(update_fields=['failed_login_attempts', 'locked_until'])

    def reset_lockout(self):
        if self.failed_login_attempts > 0 or self.locked_until is not None:
            self.failed_login_attempts = 0
            self.locked_until = None
            self.save(update_fields=['failed_login_attempts', 'locked_until'])


class EmailVerificationCode(models.Model):
    """Modell für den 6-stelligen Double Opt-In Verifizierungscode"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='verification_codes'
    )
    code = models.CharField(max_length=6, verbose_name="6-stelliger Code")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(verbose_name="Ablaufdatum")
    is_used = models.BooleanField(default=False, verbose_name="Verwendet")
    failed_attempts = models.PositiveSmallIntegerField(
        default=0, verbose_name="Fehlgeschlagene Versuche"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "E-Mail Verifizierungscode"
        verbose_name_plural = "E-Mail Verifizierungscodes"

    def __str__(self):
        return f"Code {self.code} für {self.user.username} (Gültig bis {self.expires_at.strftime('%H:%M')})"

    @classmethod
    def generate_for_user(cls, user, valid_minutes=15):
        """Erstellt einen neuen kryptografisch sicheren 6-stelligen Code und invalidiert alte unbenutzte Codes."""
        import secrets
        from datetime import timedelta
        from django.utils import timezone

        # Vorherige unbenutzte Codes für diesen Benutzer entwerten
        cls.objects.filter(user=user, is_used=False).update(is_used=True)

        secure_code = f"{secrets.randbelow(900000) + 100000:06d}"
        expires_at = timezone.now() + timedelta(minutes=valid_minutes)
        return cls.objects.create(user=user, code=secure_code, expires_at=expires_at)

    def is_valid(self):
        from django.utils import timezone
        return not self.is_used and self.failed_attempts < 5 and timezone.now() < self.expires_at

    def register_failed_attempt(self):
        self.failed_attempts += 1
        if self.failed_attempts >= 5:
            self.is_used = True  # Code nach 5 Fehlversuchen sperren
        self.save(update_fields=['failed_attempts', 'is_used'])


