from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from tinymce.models import HTMLField
from events.models import Event


class SponsorQuerySet(models.QuerySet):
    """QuerySet mit Hilfsmethoden für Sponsoren-Filterung."""

    def aktiv(self):
        """
        Filtert alle aktuell aktiven Sponsoren basierend auf ihrem Modus:
        - dauerhaft: immer aktiv
        - datum: bis einschließlich aktiv_bis aktiv
        - veranstaltung: aktiv, solange die verknüpfte Veranstaltung aktiv/laufend ist
        - inaktiv: nie aktiv
        """
        today = timezone.localdate()
        now = timezone.now()

        dauerhaft_q = models.Q(aktiv_modus=Sponsor.AktivModus.DAUERHAFT)
        datum_q = models.Q(aktiv_modus=Sponsor.AktivModus.DATUM) & models.Q(aktiv_bis__gte=today)
        veranstaltung_q = (
            models.Q(aktiv_modus=Sponsor.AktivModus.VERANSTALTUNG)
            & models.Q(veranstaltung__isnull=False)
            & models.Q(veranstaltung__is_active=True)
            & ~models.Q(veranstaltung__status=Event.Status.CANCELLED)
            & (models.Q(veranstaltung__end_date__gte=now) | models.Q(veranstaltung__end_date__isnull=True))
        )

        return self.filter(dauerhaft_q | datum_q | veranstaltung_q)


class SponsorManager(models.Manager.from_queryset(SponsorQuerySet)):
    """Standard-Manager für Sponsor mit QuerySet-Methoden."""
    pass


def validate_sponsor_image_file_size(file):
    """Beschränkt die maximale Dateigröße für Sponsor-Bilder auf 10 MB."""
    max_size_mb = 10
    if file and hasattr(file, 'size') and file.size > max_size_mb * 1024 * 1024:
        raise ValidationError(
            f"Die Dateigröße darf maximal {max_size_mb} MB betragen (hochgeladen: {file.size / (1024 * 1024):.1f} MB)."
        )


class Sponsor(models.Model):
    """
    Datenmodell zur Verwaltung von Veranstaltungs- und Community-Sponsoren.
    """

    class LogoTyp(models.TextChoices):
        LOGO = 'logo', 'Quadratisches Logo'
        BANNER = 'banner', 'Rechteckiges Banner'

    class AktivModus(models.TextChoices):
        DAUERHAFT = 'dauerhaft', 'Dauerhaft aktiv'
        VERANSTALTUNG = 'veranstaltung', 'An Veranstaltung gekoppelt'
        DATUM = 'datum', 'Bis zu einem bestimmten Datum'
        INAKTIV = 'inaktiv', 'Inaktiv'

    name = models.CharField(
        max_length=200,
        verbose_name="Name des Sponsors",
    )
    logo_typ = models.CharField(
        max_length=20,
        choices=LogoTyp.choices,
        default=LogoTyp.LOGO,
        verbose_name="Logo-Typ",
        help_text="Steuert die Darstellung: Logo (quadratisch mit Name) oder Banner (volle Breite)",
    )
    bild = models.ImageField(
        upload_to='sponsors/',
        verbose_name="Logo- oder Banner-Datei",
        help_text="Logo- oder Banner-Datei. Erlaubte Formate: JPG, PNG, WebP, GIF, SVG. Maximale Dateigröße: 10 MB.",
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp', 'gif', 'svg']),
            validate_sponsor_image_file_size,
        ],
    )
    url = models.URLField(
        blank=True,
        verbose_name="Website URL",
        help_text="Website des Sponsors (optional)",
    )
    beschreibung = HTMLField(
        blank=True,
        verbose_name="Beschreibung",
        help_text="Beschreibungstext über den django-tinymce-Editor",
    )
    aktiv_modus = models.CharField(
        max_length=20,
        choices=AktivModus.choices,
        default=AktivModus.DAUERHAFT,
        verbose_name="Aktiv-Modus",
        help_text="Steuert, wie der Sponsor aktiv/inaktiv geschaltet wird",
    )
    veranstaltung = models.ForeignKey(
        'events.Event',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sponsors',
        verbose_name="Verknüpfte Veranstaltung",
        help_text="Nur relevant, wenn Aktiv-Modus 'An Veranstaltung gekoppelt' gewählt ist",
    )
    aktiv_bis = models.DateField(
        null=True,
        blank=True,
        verbose_name="Aktiv bis (inklusive)",
        help_text="Nur relevant, wenn Aktiv-Modus 'Bis Datum' gewählt ist. Am angegebenen Tag noch aktiv, danach inaktiv.",
    )
    rang = models.PositiveIntegerField(
        default=100,
        verbose_name="Rang / Reihenfolge",
        help_text="Je kleiner die Zahl, desto weiter oben in der Liste.",
    )
    erstellt_am = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Erstellt am",
    )
    aktualisiert_am = models.DateTimeField(
        auto_now=True,
        verbose_name="Zuletzt geändert",
    )

    objects = SponsorManager()

    class Meta:
        verbose_name = "Sponsor"
        verbose_name_plural = "Sponsoren"
        ordering = ['rang', 'erstellt_am', 'id']

    def __str__(self):
        return f"{self.name} ({self.get_logo_typ_display()})"

    @property
    def ist_aktiv(self) -> bool:
        """
        Berechnet den tatsächlichen Aktiv-Status des Sponsors:
        - dauerhaft: immer aktiv
        - inaktiv: immer inaktiv
        - datum: aktiv, solange heute <= aktiv_bis
        - veranstaltung: aktiv, solange verknüpfte Veranstaltung existiert, is_active=True ist,
          nicht abgesagt und das Enddatum noch nicht überschritten ist.
        """
        if self.aktiv_modus == self.AktivModus.DAUERHAFT:
            return True
        elif self.aktiv_modus == self.AktivModus.INAKTIV:
            return False
        elif self.aktiv_modus == self.AktivModus.DATUM:
            if not self.aktiv_bis:
                return False
            return timezone.localdate() <= self.aktiv_bis
        elif self.aktiv_modus == self.AktivModus.VERANSTALTUNG:
            if not self.veranstaltung:
                return False
            event = self.veranstaltung
            now = timezone.now()
            if not event.is_active or event.status == Event.Status.CANCELLED:
                return False
            if event.end_date and now > event.end_date:
                return False
            return True
        return False

    def clean(self):
        super().clean()
        if self.aktiv_modus == self.AktivModus.VERANSTALTUNG and not self.veranstaltung_id:
            raise ValidationError({
                'veranstaltung': 'Für den Modus "An Veranstaltung gekoppelt" muss eine Veranstaltung ausgewählt werden.'
            })
        if self.aktiv_modus == self.AktivModus.DATUM and not self.aktiv_bis:
            raise ValidationError({
                'aktiv_bis': 'Für den Modus "Bis Datum" muss ein Enddatum angegeben werden.'
            })
