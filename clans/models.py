from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils.text import slugify


class Clan(models.Model):
    name = models.CharField(
        max_length=100, unique=True, verbose_name="Clanname"
    )
    slug = models.SlugField(
        max_length=100, unique=True, blank=True, verbose_name="URL-Slug"
    )
    website = models.URLField(blank=True, verbose_name="Website URL")
    logo = models.ImageField(
        upload_to="clan_logos/",
        blank=True,
        null=True,
        verbose_name="Clan-Logo",
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp'])],
    )
    password = models.CharField(
        max_length=128,
        verbose_name="Clan-Passwort (Gehasht)",
        help_text="Passwort für sofortigen Direktbeitritt (wird sicher gehasht gespeichert)",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Erstellt am"
    )
    updated_at = models.DateTimeField(
        auto_now=True, verbose_name="Zuletzt geändert"
    )

    class Meta:
        verbose_name = "Clan"
        verbose_name_plural = "Clans"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def set_password(self, raw_password):
        if raw_password:
            self.password = make_password(raw_password)
        else:
            self.password = ''

    def check_password(self, raw_password):
        if not self.password or not raw_password:
            return False
        return check_password(raw_password, self.password)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or "clan"
            slug = base_slug
            count = 1
            while Clan.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{count}"
                count += 1
            self.slug = slug
        if self.password and not (
            self.password.startswith('pbkdf2_') or
            self.password.startswith('argon2') or
            self.password.startswith('bcrypt') or
            self.password.startswith('scrypt')
        ):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

    def get_accepted_memberships(self):
        return self.memberships.filter(status=ClanMembership.Status.ACCEPTED).select_related('user')

    def get_pending_memberships(self):
        return self.memberships.filter(status=ClanMembership.Status.PENDING).select_related('user')

    def is_admin(self, user):
        if not user or not user.is_authenticated:
            return False
        return self.memberships.filter(
            user=user,
            role=ClanMembership.Role.ADMIN,
            status=ClanMembership.Status.ACCEPTED,
        ).exists()

    def get_user_membership(self, user):
        if not user or not user.is_authenticated:
            return None
        return self.memberships.filter(user=user).first()


class ClanMembership(models.Model):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Clan-Admin'
        MEMBER = 'MEMBER', 'Clan-Mitglied'

    class Status(models.TextChoices):
        ACCEPTED = 'ACCEPTED', 'Mitglied'
        PENDING = 'PENDING', 'Anfrage ausstehend'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='clan_memberships',
        verbose_name="Benutzer",
    )
    clan = models.ForeignKey(
        Clan,
        on_delete=models.CASCADE,
        related_name='memberships',
        verbose_name="Clan",
    )
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.MEMBER,
        verbose_name="Rolle",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACCEPTED,
        verbose_name="Status",
    )
    created_at = models.DateTimeField(
        auto_now_add=True, verbose_name="Beigetreten / Angefragt am"
    )

    class Meta:
        verbose_name = "Clan-Mitgliedschaft"
        verbose_name_plural = "Clan-Mitgliedschaften"
        unique_together = ('user', 'clan')
        ordering = ['role', 'created_at']

    def __str__(self):
        return f"{self.user.username} @ {self.clan.name} ({self.get_role_display()} - {self.get_status_display()})"

    @classmethod
    def get_user_active_membership(cls, user):
        if not user or not user.is_authenticated:
            return None
        return cls.objects.filter(user=user, status=cls.Status.ACCEPTED).select_related('clan').first()
