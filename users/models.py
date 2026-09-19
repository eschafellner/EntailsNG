from django.contrib.auth.models import AbstractUser, UserManager as BaseUserManager
from django.db import models
from .exceptions import VerificationCodeCooldownError, VerificationCodeLimitError


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
        """Atomare Erfassung eines Fehlversuchs mit Zeilensperre.
        Erhöht den Zähler und sperrt das Konto für 15 Minuten ab dem 5. Fehlversuch.
        Gibt True zurück, wenn das Konto gesperrt ist/wurde.
        """
        from datetime import timedelta
        from django.db import transaction
        from django.utils import timezone

        if not self.pk:
            return False

        with transaction.atomic():
            locked_user = type(self).objects.select_for_update().get(pk=self.pk)
            now = timezone.now()

            # Wenn bereits gesperrt und Sperrzeit noch aktiv
            if locked_user.locked_until and now < locked_user.locked_until:
                self.failed_login_attempts = locked_user.failed_login_attempts
                self.locked_until = locked_user.locked_until
                return True

            # Wenn vorherige Sperre bereits abgelaufen ist, Zähler zurücksetzen
            if locked_user.locked_until and now >= locked_user.locked_until:
                locked_user.failed_login_attempts = 0
                locked_user.locked_until = None

            locked_user.failed_login_attempts += 1
            if locked_user.failed_login_attempts >= 5:
                locked_user.locked_until = now + timedelta(minutes=15)

            locked_user.save(update_fields=['failed_login_attempts', 'locked_until'])
            self.failed_login_attempts = locked_user.failed_login_attempts
            self.locked_until = locked_user.locked_until
            return bool(locked_user.locked_until and now < locked_user.locked_until)

    def reset_lockout(self):
        """Setzt Fehlversuchszähler und Sperre atomar mit Zeilensperre zurück."""
        from django.db import transaction

        if not self.pk:
            self.failed_login_attempts = 0
            self.locked_until = None
            return

        with transaction.atomic():
            locked_user = type(self).objects.select_for_update().get(pk=self.pk)
            if locked_user.failed_login_attempts > 0 or locked_user.locked_until is not None:
                locked_user.failed_login_attempts = 0
                locked_user.locked_until = None
                locked_user.save(update_fields=['failed_login_attempts', 'locked_until'])
            self.failed_login_attempts = 0
            self.locked_until = None


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
    new_email = models.EmailField(
        blank=True,
        null=True,
        verbose_name="Neue E-Mail-Adresse",
        help_text="Wird bei E-Mail-Änderungen im Profil gesetzt. Bleibt bei Erstregistrierung leer.",
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "E-Mail Verifizierungscode"
        verbose_name_plural = "E-Mail Verifizierungscodes"

    def __str__(self):
        target = f" (neue E-Mail: {self.new_email})" if self.new_email else ""
        return f"Code {self.code} für {self.user.username}{target} (Gültig bis {self.expires_at.strftime('%H:%M')})"

    COOLDOWN_SECONDS = 60
    MAX_CODES_PER_HOUR = 5

    @classmethod
    def generate_for_user(cls, user, valid_minutes=15, new_email=None, enforce_cooldown=True):
        """Erstellt einen neuen kryptografisch sicheren 6-stelligen Code und invalidiert alte unbenutzte Codes.
        Prüft zentral Cooldown und Stundenlimit, um Mail-Spamming und vorzeitige Code-Invalidierung zu verhindern.
        """
        import secrets
        from datetime import timedelta
        from django.utils import timezone

        now = timezone.now()

        # 1. Zentraler Cooldown-Schutz & Stundenlimit
        if enforce_cooldown:
            scope_query = cls.objects.filter(user=user)
            if new_email:
                scope_query = scope_query.filter(new_email__isnull=False)
            else:
                scope_query = scope_query.filter(new_email__isnull=True)

            last_code = scope_query.order_by('-created_at').first()
            if last_code:
                elapsed = (now - last_code.created_at).total_seconds()
                if elapsed < cls.COOLDOWN_SECONDS:
                    remaining = int(cls.COOLDOWN_SECONDS - elapsed)
                    if remaining <= 0:
                        remaining = 1
                    raise VerificationCodeCooldownError(
                        f"Bitte warte noch {remaining} Sekunde(n), bevor du einen neuen Code anforderst.",
                        retry_after=remaining,
                    )

            one_hour_ago = now - timedelta(hours=1)
            recent_count = scope_query.filter(created_at__gte=one_hour_ago).count()
            if recent_count >= cls.MAX_CODES_PER_HOUR:
                raise VerificationCodeLimitError(
                    "Du hast das Limit für Bestätigungscodes erreicht (maximal 5 pro Stunde). Bitte versuche es später erneut."
                )

        # 2. Vorherige unbenutzte Codes für diesen Benutzer und diesen Zweck entwerten
        query = cls.objects.filter(user=user, is_used=False)
        if new_email:
            query = query.filter(new_email__isnull=False)
        else:
            query = query.filter(new_email__isnull=True)
        query.update(is_used=True)

        # 3. Neuen Code erzeugen
        secure_code = f"{secrets.randbelow(900000) + 100000:06d}"
        expires_at = now + timedelta(minutes=valid_minutes)
        return cls.objects.create(
            user=user,
            code=secure_code,
            expires_at=expires_at,
            new_email=new_email,
        )

    def is_valid(self):
        from django.utils import timezone
        return not self.is_used and self.failed_attempts < 5 and timezone.now() < self.expires_at

    def register_failed_attempt(self):
        """Erhöht den Fehlversuchszähler atomar mit Zeilensperre.
        Sperrt den Code nach 5 Fehlversuchen (is_used = True).
        Gibt die Anzahl der verbleibenden Versuche zurück.
        """
        from django.db import transaction

        if not self.pk:
            return 0

        with transaction.atomic():
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            if locked.is_used or locked.failed_attempts >= 5:
                self.failed_attempts = locked.failed_attempts
                self.is_used = True
                return 0

            locked.failed_attempts += 1
            if locked.failed_attempts >= 5:
                locked.is_used = True
            locked.save(update_fields=['failed_attempts', 'is_used'])
            self.failed_attempts = locked.failed_attempts
            self.is_used = locked.is_used
            return max(0, 5 - locked.failed_attempts)

    @classmethod
    def verify_and_consume(cls, user, code_input, is_email_change=False):
        """Prüft und verbraucht einen Verifizierungscode atomar mit Zeilensperre.
        Schützt vor Race-Conditions bei parallelen Brute-Force-Versuchen und Mehrfachverbrauch.

        Rückgabe:
            (status, code_obj, remaining_attempts)
            status:
              - 'success': Code ist gültig, übereinstimmend und wurde verbraucht (sowie Benutzer aktiviert bzw. E-Mail geändert).
              - 'email_taken': Code korrekt, aber neue E-Mail ist inzwischen anderweitig vergeben.
              - 'wrong_code': Code war falsch, Fehlversuchszähler atomar erhöht.
              - 'locked': Code wurde durch 5 Fehlversuche gesperrt.
              - 'invalid_or_expired': Kein aktiver Code vorhanden oder abgelaufen/bereits verbraucht.
        """
        import secrets
        from django.db import transaction

        code_input = (code_input or "").strip()
        if not code_input:
            return ('invalid_or_expired', None, 0)

        with transaction.atomic():
            query = cls.objects.select_for_update().filter(user=user, is_used=False)
            if is_email_change:
                query = query.filter(new_email__isnull=False)
            else:
                query = query.filter(new_email__isnull=True)

            code_obj = query.order_by('-created_at').first()
            if not code_obj or not code_obj.is_valid():
                return ('invalid_or_expired', code_obj, 0)

            if secrets.compare_digest(code_obj.code, code_input):
                if is_email_change:
                    # Prüfen, ob die neue Adresse inzwischen anderweitig vergeben wurde
                    if User.objects.filter(email__iexact=code_obj.new_email).exclude(pk=user.pk).exists():
                        return ('email_taken', code_obj, 0)
                    # Neue E-Mail auf User übertragen und Code verbrauchen
                    locked_user = User.objects.select_for_update().get(pk=user.pk)
                    locked_user.email = code_obj.new_email
                    locked_user.save(update_fields=['email'])
                    user.email = locked_user.email
                else:
                    # Benutzer aktivieren und Code verbrauchen
                    locked_user = User.objects.select_for_update().get(pk=user.pk)
                    locked_user.is_active = True
                    locked_user.save(update_fields=['is_active'])
                    user.is_active = True

                code_obj.is_used = True
                code_obj.save(update_fields=['is_used'])
                return ('success', code_obj, 0)
            else:
                code_obj.failed_attempts += 1
                if code_obj.failed_attempts >= 5:
                    code_obj.is_used = True
                code_obj.save(update_fields=['failed_attempts', 'is_used'])
                remaining = max(0, 5 - code_obj.failed_attempts)
                status = 'locked' if code_obj.failed_attempts >= 5 else 'wrong_code'
                return (status, code_obj, remaining)


