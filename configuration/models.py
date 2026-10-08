import re
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.urls import NoReverseMatch, reverse

from .validators import (
    parse_contact_recipients, validate_contact_recipients,
    validate_bic, validate_iban, validate_hex_color,
)
from .default_data import DEFAULT_DATENSCHUTZ_CONTENT, SYSTEM_ICONS
from .themes import THEME_PRESETS, SCALE_MAP, build_css_variables
from .sanitizer import (
    ALLOWED_SVG_TAGS,
    DANGEROUS_CSS_PATTERNS,
    DANGEROUS_PROTOCOLS_REGEX,
    DISALLOWED_ATTRIBUTES_REGEX,
    SafeHTMLSanitizer,
    sanitize_html,
    validate_custom_css,
    sanitize_and_validate_svg,
)
from configuration.cache import (
    safe_cache_delete,
    safe_cache_delete_many,
    safe_cache_get_or_set,
    invalidate_event_capacity_cache,
    invalidate_general_configuration_cache,
    invalidate_navigation_cache,
    invalidate_site_customization_cache,
    invalidate_system_translations_cache,
)


class NavigationItem(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = 'PUBLIC', 'Alle Besucher'
        AUTHENTICATED = 'AUTHENTICATED', 'Nur angemeldete Benutzer'
        STAFF = 'STAFF', 'Nur Mitarbeiter'

    class IconChoices(models.TextChoices):
        DASHBOARD = 'dashboard', 'Dashboard / Übersicht (Home)'
        TOURNAMENTS = 'tournaments', 'Turniere (Pokal / Trophy)'
        TEAMS = 'teams', 'Teams (Spielergruppe)'
        SEATING = 'seating', 'Sitzplan (Raster / Grid)'
        INFO = 'info', 'Informationen (Info-Kreis)'
        NEWS = 'news', 'Neuigkeiten (Zeitung / Feed)'
        CLANS = 'clans', 'Clans (Schild / Wappen)'
        RULES = 'rules', 'Regeln & FAQ (Buch / Dokument)'
        SUPPORT = 'support', 'Support & Hilfe (Rettungsring)'
        SHOP = 'shop', 'Shop & Catering (Einkaufswagen)'
        SETTINGS = 'settings', 'Einstellungen (Regler)'
        SPONSORS = 'sponsors', 'Sponsoren (Stern / Partner)'
        CUSTOM = 'custom', 'Benutzerdefiniertes SVG (Nur Superuser)'

    title = models.CharField(
        max_length=200,
        help_text='Anzeigename im Menü (z. B. Übersicht, Sitzplan)',
    )
    url_name = models.CharField(
        max_length=255,
        help_text='Django URL-Name oder Modulkürzel, z. B. dashboard, teams, tournaments, seating, news, info, clans, sponsors',
    )
    icon_name = models.CharField(
        max_length=50,
        choices=IconChoices.choices,
        default=IconChoices.DASHBOARD,
        verbose_name='Icon-Auswahl',
        help_text='Wähle ein sicheres Standard-Icon aus der Liste.',
    )
    icon_svg = models.TextField(
        blank=True, help_text='Optionaler SVG-Code für das Icon (nur bei Auswahl "Benutzerdefiniertes SVG")'
    )
    badge_text = models.CharField(
        max_length=10, blank=True, default='',
        help_text='Optionales Badge, z. B. "2" oder "NEU"',
    )
    order = models.PositiveIntegerField(
        default=0, help_text='Kleinere Zahlen stehen weiter oben bzw. links'
    )
    is_active = models.BooleanField(default=True, help_text='Im Menü anzeigen?')
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        verbose_name='Sichtbarkeit',
        help_text='Legt fest, für welche Besucher dieser Menüpunkt sichtbar ist. Die Zielseite prüft ihre Zugriffsrechte weiterhin selbst.',
    )

    ALIAS_MAP = {
        'teams': 'team_list',
        'tournaments': 'tournament_list',
        'turniere': 'tournament_list',
        'clans': 'clan_list',
        'info': 'event_info_detail',
        'infos': 'event_info_detail',
        'seating': 'seating_plan',
        'news': 'news_list',
        'sponsors': 'sponsor_list',
        'sponsoren': 'sponsor_list',
        'contact': 'contact:form',
        'kontakt': 'contact:form',
    }

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Menüpunkt'
        verbose_name_plural = 'Menüpunkte'

    def __str__(self):
        return f'{self.order}. {self.title} ({self.url_name})'

    def is_visible_to(self, user):
        if not self.is_active:
            return False
        if self.visibility == self.Visibility.PUBLIC:
            return True
        if not user or not user.is_authenticated:
            return False
        if self.visibility == self.Visibility.AUTHENTICATED:
            return True
        return self.visibility == self.Visibility.STAFF and user.is_staff

    def clean(self):
        """Verhindert Tippfehler und schützt vor XSS in SVG-Icons."""
        if self.url_name and (self.url_name.startswith('/') or self.url_name.startswith(('http://', 'https://'))):
            pass
        else:
            target = self.ALIAS_MAP.get(self.url_name, self.url_name)
            try:
                reverse(target)
            except NoReverseMatch:
                raise ValidationError({
                    'url_name': (
                        f'"{self.url_name}" ist kein bekannter URL-Name und kein gültiger Pfad. '
                        'Gültig sind z. B.: dashboard, teams (team_list), '
                        'tournaments (tournament_list), seating (seating_plan), '
                        'news (news_list), info (event_info_detail), clans (clan_list), '
                        'sponsors (sponsor_list) oder absolute Pfade wie /info/catering/.'
                    )
                })

        if self.icon_name == self.IconChoices.CUSTOM and self.icon_svg:
            self.icon_svg = sanitize_and_validate_svg(self.icon_svg)
        elif self.icon_name != self.IconChoices.CUSTOM:
            self.icon_svg = SYSTEM_ICONS.get(self.icon_name, '')

    def get_icon_svg(self):
        """Liefert den sicheren SVG-Code des Icons."""
        if self.icon_name != self.IconChoices.CUSTOM and self.icon_name in SYSTEM_ICONS:
            return SYSTEM_ICONS[self.icon_name]
        return self.icon_svg or SYSTEM_ICONS.get('dashboard', '')

    def get_url(self):
        if self.url_name and (self.url_name.startswith('/') or self.url_name.startswith(('http://', 'https://'))):
            return self.url_name
        target = self.ALIAS_MAP.get(self.url_name, self.url_name)
        try:
            return reverse(target)
        except NoReverseMatch:
            return ''

    def save(self, *args, **kwargs):
        if self.icon_name != self.IconChoices.CUSTOM:
            self.icon_svg = SYSTEM_ICONS.get(self.icon_name, '')
        elif not self.icon_svg:
            self.icon_svg = SYSTEM_ICONS.get('dashboard', '')
        super().save(*args, **kwargs)
        invalidate_navigation_cache()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        invalidate_navigation_cache()


class SystemTranslation(models.Model):
    key = models.CharField(
        max_length=255,
        unique=True,
        help_text='Eindeutiger Übersetzungsschlüssel (z. B. seat_card_title)',
    )
    text = models.TextField(
        blank=True,
        default='',
        help_text='Der im Frontend angezeigte Text für diesen Schlüssel',
    )

    class Meta:
        ordering = ['key']
        verbose_name = 'Übersetzung'
        verbose_name_plural = 'Übersetzungen'

    def __str__(self):
        return f'{self.key}: {self.text[:30]}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        invalidate_system_translations_cache()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        invalidate_system_translations_cache()


class ClanSeatConfiguration(models.Model):
    class Duration(models.TextChoices):
        EVENT = 'EVENT', 'Veranstaltungszeitraum'
        DAYS = 'DAYS', 'Zeitraum ab erster Vormerkung des Clans'
        FIXED = 'FIXED', 'Fixer Zeitpunkt'

    enabled = models.BooleanField(default=False, verbose_name='Aktiv', help_text='Deaktivieren gibt offene Vormerkungen ohne Sammelauftrag frei. Sammelaufträge und persönliche Buchungen bleiben erhalten.')
    default_limit = models.PositiveIntegerField(default=8, verbose_name='Anzahl vormerkbarer Sitzplätze', help_text='Kontingent pro Clan und Veranstaltung. Bereits übernommene Plätze zählen mit.')
    duration = models.CharField(max_length=5, choices=Duration.choices, default=Duration.EVENT, verbose_name='Dauer der Vormerkung')
    days = models.PositiveIntegerField(default=14, verbose_name='Dauer in Tagen', help_text='Nur beim Tagesmodus; jeder Clan startet mit seiner ersten bestätigten Vormerkung.')
    deadline = models.DateTimeField(null=True, blank=True, verbose_name='Gültig bis', help_text='Nur beim fixen Zeitpunkt. Zeitzone: Europe/Vienna.')
    payment_ticket_type = models.ForeignKey('events.TicketType', null=True, blank=True, on_delete=models.PROTECT,
        verbose_name='Ticketkategorie für Clan-Sammelzahlungen', help_text='Bei genau einer aktiven Kategorie wird diese automatisch verwendet. Sonst hier eine Kategorie der aktiven Veranstaltung festlegen.')
    payment_days = models.PositiveIntegerField(default=7, verbose_name='Zahlungsfrist in Kalendertagen')
    payment_review_days = models.PositiveIntegerField(default=2, verbose_name='Prüfzeit in Kalendertagen',
        help_text='Zusätzliche Zeit für die Orga. Beide Fristen enden spätestens mit der ursprünglichen Vormerkfrist.')

    class Meta:
        verbose_name = 'Clan Sitzplatz Vormerkung'
        verbose_name_plural = 'Clan Sitzplatz Vormerkung'
        constraints = [models.CheckConstraint(condition=models.Q(pk=1), name='clan_seat_config_singleton'),
            models.CheckConstraint(condition=models.Q(payment_days__gte=1), name='clan_payment_days_positive')]

    def __str__(self):
        return self._meta.verbose_name

    def clean(self):
        super().clean()
        if not self.payment_days:
            raise ValidationError({'payment_days': 'Bitte mindestens einen Tag Zahlungsfrist angeben.'})
        if self.duration == self.Duration.DAYS and not self.days:
            raise ValidationError({'days': 'Bitte mindestens einen Tag angeben.'})
        if self.duration == self.Duration.FIXED and not self.deadline:
            raise ValidationError({'deadline': 'Bitte einen Ablaufzeitpunkt angeben.'})

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            self.pk = 1
            # Coordinate direct model saves with booking and quota forms as well.
            type(self).objects.select_for_update().filter(pk=1).first()
            super().save(*args, **kwargs)
            if not self.enabled or self.default_limit == 0:
                from seating.models import ClanSeatHold
                from seating.clan_services import release_holds
                holds = ClanSeatHold.objects.filter(protection_active=True)
                if self.enabled:
                    holds = holds.filter(allocation__clan__seat_limit_override__isnull=True)
                release_holds(holds)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]


class GeneralConfiguration(models.Model):
    """
    Zentrale allgemeine Konfiguration für Systemeinstellungen (z. B. Ticket-Anzeige).
    Singleton-Muster: Es existiert nur 1 Datensatz in der Datenbank (pk=1).
    """

    class ExpiredTicketMode(models.TextChoices):
        WORN = 'WORN', 'Ticket abgenutzt (Mit "Veranstaltung beendet" Hinweis anzeigen)'
        HIDE = 'HIDE', 'Event beendet (Automatisch ausblenden bei Event-Ende)'

    contact_enabled = models.BooleanField(
        default=False, verbose_name='Kontaktformular aktivieren',
        help_text='Erlaubt Kontaktanfragen auch ohne Anmeldung. Benötigt aktive Betreffkategorien und einen eingerichteten E-Mail-Versand.',
    )
    contact_recipient_emails = models.TextField(
        blank=True, default='', max_length=6000,
        validators=[validate_contact_recipients], verbose_name='Standardempfänger für Kontaktanfragen',
        help_text='Eine oder mehrere E-Mail-Adressen, getrennt mit ; (maximal 20). Kategorien ohne eigene Empfänger verwenden diese Liste.',
    )

    ticket_enabled = models.BooleanField(
        default=True,
        verbose_name="Ticket anzeigen",
        help_text="Schaltet die Anzeige des Ticket-Bereichs auf dem Dashboard generell ein oder aus.",
    )
    ticket_days_before_event = models.PositiveIntegerField(
        default=0,
        verbose_name="Ticket nur anzeigen X Tage vor Event-Start",
        help_text="Anzahl der Tage vor dem Event. Bei > 0 wird das Ticket erst in diesem Zeitraum vor Event-Start angezeigt (0 = immer anzeigen).",
    )
    ticket_requires_login = models.BooleanField(
        default=False,
        verbose_name="Ticket nur anzeigen, wenn der Gast eingeloggt ist",
        help_text="Wenn aktiviert, sieht der Gast die Ticket-Karte auf dem Dashboard erst, nachdem er sich angemeldet hat (für nicht eingeloggte Besucher wird sie verborgen).",
    )
    ticket_requires_payment = models.BooleanField(
        default=False,
        verbose_name="Ticket nur anzeigen, wenn der Gast eingezahlt hat",
        help_text="Wenn aktiviert, sieht der Gast die Ticket-Karte auf dem Dashboard erst, nachdem seine Zahlung verbucht wurde.",
    )
    expired_ticket_mode = models.CharField(
        max_length=10,
        choices=ExpiredTicketMode.choices,
        default=ExpiredTicketMode.WORN,
        verbose_name="Verhalten bei abgelaufenen Veranstaltungen",
        help_text="Bestimmt das Verhalten der Ticket-Karte auf dem Dashboard, wenn das Event-Enddatum überschritten ist.",
    )
    debug_mode = models.BooleanField(
        default=False,
        verbose_name="Debug-Modus (Detaillierte Fehlerausgabe)",
        help_text="Aktiviert die detaillierte technische Django-Fehlerseite bei Serverfehlern. Im normalen Live-Betrieb sollte dies deaktiviert sein.",
    )

    # Zahlungsdaten für Banküberweisungen & GiroCode / EPC-QR
    kontoinhaber = models.CharField(
        max_length=70,
        blank=True,
        verbose_name="Kontoinhaber",
        help_text="Name des Empfängers / Kontoinhabers (max. 70 Zeichen für EPC-QR-Standard).",
    )
    iban = models.CharField(
        max_length=34,
        blank=True,
        verbose_name="IBAN",
        help_text="IBAN des Empfängerkontos für SEPA-Überweisungen (ohne Leerzeichen gespeichert).",
        validators=[validate_iban],
    )
    bic = models.CharField(
        max_length=11,
        blank=True,
        verbose_name="BIC / SWIFT",
        help_text="Optional: BIC der Empfängerbank (8 oder 11 Zeichen).",
        validators=[validate_bic],
    )

    class Meta:
        verbose_name = "Allgemeine Konfiguration"
        verbose_name_plural = "Allgemeine Konfiguration"

    def __str__(self):
        return "Allgemeine Konfiguration"

    @property
    def has_payment_details(self):
        """Gibt True zurück, wenn IBAN und Kontoinhaber hinterlegt sind."""
        return bool(self.iban and self.kontoinhaber)

    @property
    def formatted_iban(self):
        """Gibt die IBAN leserlich in 4er-Blöcken formatiert zurück."""
        if not self.iban:
            return ""
        clean = self.iban.replace(" ", "").upper()
        return " ".join([clean[i:i+4] for i in range(0, len(clean), 4)])

    def clean(self):
        super().clean()
        try:
            self.contact_recipient_emails = '; '.join(parse_contact_recipients(self.contact_recipient_emails))
        except ValidationError as exc:
            raise ValidationError({'contact_recipient_emails': exc.messages}) from exc
        if self.contact_enabled and not self.contact_recipient_emails:
            raise ValidationError({'contact_recipient_emails': 'Zum Aktivieren des Kontaktformulars mindestens einen Standardempfänger angeben.'})
        if self.iban:
            self.iban = re.sub(r'[\s\-]', '', self.iban).upper()
            validate_iban(self.iban)
        if self.bic:
            self.bic = re.sub(r'\s', '', self.bic).upper()
            validate_bic(self.bic)
        if self.kontoinhaber:
            self.kontoinhaber = self.kontoinhaber.strip()

    def save(self, *args, **kwargs):
        self.pk = 1
        self.contact_recipient_emails = '; '.join(parse_contact_recipients(self.contact_recipient_emails))
        if self.iban:
            self.iban = re.sub(r'[\s\-]', '', self.iban).upper()
        if self.bic:
            self.bic = re.sub(r'\s', '', self.bic).upper()
        if self.kontoinhaber:
            self.kontoinhaber = self.kontoinhaber.strip()
        super().save(*args, **kwargs)
        safe_cache_delete('general_configuration')
        invalidate_general_configuration_cache()

    def delete(self, *args, **kwargs):
        raise ValidationError("Die Systemeinstellungen können nicht gelöscht werden.")

    @classmethod
    def load(cls):
        return safe_cache_get_or_set(
            'general_configuration',
            lambda: cls.objects.get_or_create(pk=1)[0],
            300,
        )



class ContactCategory(models.Model):
    configuration = models.ForeignKey(
        GeneralConfiguration, on_delete=models.CASCADE, related_name='contact_categories',
    )
    name = models.CharField(max_length=120, verbose_name='Betreffkategorie')
    recipient_emails = models.TextField(
        blank=True, default='', max_length=6000, validators=[validate_contact_recipients],
        verbose_name='Empfängeradressen',
        help_text='Mit ; trennen (maximal 20). Leer lassen, um die Standardempfänger zu verwenden.',
    )
    order = models.PositiveIntegerField(default=0, verbose_name='Reihenfolge')
    is_active = models.BooleanField(default=True, verbose_name='Aktiv')

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Kontakt-Betreffkategorie'
        verbose_name_plural = 'Kontakt-Betreffkategorien'
        constraints = [models.UniqueConstraint(
            Lower('name'), 'configuration', name='unique_contact_category_name',
        )]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.name = (self.name or '').strip()
        if not self.name or '\r' in self.name or '\n' in self.name:
            raise ValidationError({'name': 'Bitte eine nicht leere Betreffkategorie ohne Zeilenumbrüche angeben.'})
        try:
            self.recipient_emails = '; '.join(parse_contact_recipients(self.recipient_emails))
        except ValidationError as exc:
            raise ValidationError({'recipient_emails': exc.messages}) from exc

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class SiteCustomization(models.Model):
    """
    Zentrale Individualisierung und Branding für das System.
    Singleton-Muster: Es existiert nur 1 Datensatz in der Datenbank (pk=1).
    """
    class ThemePreset(models.TextChoices):
        WARM_AMBER = 'WARM_AMBER', 'Warm Amber (Default)'
        CYBERPUNK = 'CYBERPUNK', 'Cyberpunk Neon'
        SLATE_BLUE = 'SLATE_BLUE', 'Slate Blue'
        EMERALD = 'EMERALD', 'Emerald Gaming'
        QUAKE_99 = 'QUAKE_99', 'Quake 99 (Retro LAN)'
        ARENA_PRO = 'ARENA_PRO', 'Arena Pro (Esports Tactical)'
        CYBERDECK = 'CYBERDECK', 'Cyberdeck (Neon Synthwave)'
        MAINFRAME = 'MAINFRAME', 'Mainframe (Terminal Green)'
        DAYLIGHT = 'DAYLIGHT', 'Daylight Projector (High-Contrast Light)'
        CUSTOM = 'CUSTOM', 'Benutzerdefiniert'

    class UIScale(models.TextChoices):
        VERY_SMALL = 'XS', 'Sehr klein'
        SMALL = 'SM', 'Klein'
        MEDIUM = 'MD', 'Mittel (Standard)'
        LARGE = 'LG', 'Groß'
        VERY_LARGE = 'XL', 'Sehr groß'

    # Alias for backwards compatibility
    NavScale = UIScale

    # Branding & Identität
    site_name = models.CharField(
        max_length=100,
        default='Entails',
        verbose_name='Systemname',
        help_text='Name des Events / der Plattform (z. B. Entails, FragFest)',
    )
    brand_accent_text = models.CharField(
        max_length=50,
        default='NG',
        blank=True,
        verbose_name='Akzent-Suffix',
        help_text='Hervorgehobenes Wort im Logo/Header (z. B. NG, 2026)',
    )
    site_tagline = models.CharField(
        max_length=100,
        default='Event Control',
        blank=True,
        verbose_name='Untertitel',
        help_text='Kurzer Untertitel unter dem Markennamen (z. B. Event Control, LAN-Party CMS)',
    )
    logo = models.ImageField(
        upload_to='branding/',
        null=True,
        blank=True,
        verbose_name='Custom Logo-Bild',
        help_text='Optionales Logo-Bild. Wenn leer, wird das Standard-Icon / Text-Logo verwendet.',
    )

    # Theme & Farben
    theme_preset = models.CharField(
        max_length=30,
        choices=ThemePreset.choices,
        default=ThemePreset.WARM_AMBER,
        verbose_name='Design-Theme (Preset)',
        help_text='Wähle ein vorgefertigtes Farbschema.',
    )
    ui_scale = models.CharField(
        max_length=10,
        choices=UIScale.choices,
        default=UIScale.MEDIUM,
        verbose_name='System-Darstellungsgröße (UI-Skalierung)',
        help_text='Steuert die Gesamt-Skalierung und Schriftgrößen des gesamten Frontends (Navigation, Karten, Buttons, Formulare, Überschriften).',
    )
    primary_color = models.CharField(
        max_length=20,
        blank=True,
        validators=[validate_hex_color],
        verbose_name='Benutzerdefinierte Akzentfarbe (--signal)',
        help_text='Hex-Code (z. B. #f8ab2d). Überschreibt die Akzentfarbe des Presets.',
    )

    @property
    def nav_scale(self):
        return self.ui_scale

    @nav_scale.setter
    def nav_scale(self, value):
        self.ui_scale = value

    secondary_color = models.CharField(
        max_length=20,
        blank=True,
        validators=[validate_hex_color],
        verbose_name='Benutzerdefinierte Hauptfarbe (--navy)',
        help_text='Hex-Code (z. B. #332719). Überschreibt die Hauptfarbe der Sidebar/Header.',
    )
    background_color = models.CharField(
        max_length=20,
        blank=True,
        validators=[validate_hex_color],
        verbose_name='Benutzerdefinierte Hintergrundfarbe (--paper)',
        help_text='Hex-Code (z. B. #fffaf2). Überschreibt die Hintergrundfarbe.',
    )

    # Rechtliches (Legal)
    impressum_content = models.TextField(
        blank=True,
        default='<h3>Impressum</h3><p>EntailsNG LAN-Party CMS</p>',
        verbose_name='Impressum',
        help_text='Inhalt für die Impressum-Seite / Modal. Unterstützt HTML.',
    )
    datenschutz_content = models.TextField(
        blank=True,
        default=DEFAULT_DATENSCHUTZ_CONTENT,
        verbose_name='Datenschutzerklärung',
        help_text='Inhalt für die Datenschutz-Seite / Modal. Unterstützt HTML.',
    )

    # Custom CSS
    custom_css = models.TextField(
        blank=True,
        verbose_name='Benutzerdefiniertes CSS',
        help_text='Wird direkt im <head> aller Seiten eingebunden.',
    )

    class Meta:
        verbose_name = 'Individualisierung & Branding'
        verbose_name_plural = 'Individualisierung & Branding'

    def clean(self):
        if self.primary_color:
            validate_hex_color(self.primary_color)
        if self.secondary_color:
            validate_hex_color(self.secondary_color)
        if self.background_color:
            validate_hex_color(self.background_color)
        if self.impressum_content:
            self.impressum_content = sanitize_html(self.impressum_content)
        if self.datenschutz_content:
            self.datenschutz_content = sanitize_html(self.datenschutz_content)
        if self.custom_css:
            validate_custom_css(self.custom_css)

    def save(self, *args, **kwargs):
        self.clean()
        self.pk = 1
        super().save(*args, **kwargs)
        invalidate_site_customization_cache()
        invalidate_system_translations_cache()
        invalidate_navigation_cache()

    def delete(self, *args, **kwargs):
        raise ValidationError("Die Individualisierungs-Einstellungen können nicht gelöscht werden.")

    @classmethod
    def load(cls):
        def _get_customization():
            obj = cls.objects.filter(pk=1).first()
            if not obj:
                obj = cls(pk=1)
            return obj

        return safe_cache_get_or_set(
            'site_customization',
            _get_customization,
            300,
        )

    def get_css_variables(self):
        """Liefert ein Dictionary mit CSS-Variablen basierend auf Preset, Farben & UI-Skalierung."""
        return build_css_variables(
            theme_preset=self.theme_preset,
            ui_scale=self.ui_scale,
            primary_color=self.primary_color,
            secondary_color=self.secondary_color,
            background_color=self.background_color,
        )


class SystemErrorLog(models.Model):
    """
    Protokolliert serverseitige Ausnahmen und 500er-Fehler zur einfachen
    Einsichtnahme und Diagnose direkt im Django Admin Backend.
    """
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Zeitpunkt")
    path = models.CharField(max_length=500, verbose_name="URL / Pfad")
    method = models.CharField(max_length=10, default="GET", verbose_name="HTTP-Methode")
    exception_type = models.CharField(max_length=255, db_index=True, verbose_name="Ausnahme-Typ")
    error_message = models.TextField(verbose_name="Fehlermeldung")
    traceback = models.TextField(verbose_name="Python-Traceback")
    user = models.CharField(max_length=150, blank=True, default="Anonym", verbose_name="Benutzer")
    ip_address = models.CharField(max_length=45, blank=True, null=True, verbose_name="IP-Adresse")
    resolved = models.BooleanField(default=False, db_index=True, verbose_name="Behoben?")
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="Behoben am")

    class Meta:
        verbose_name = "System-Fehlerprotokoll"
        verbose_name_plural = "System-Fehlerprotokolle"
        ordering = ['-timestamp']

    def __str__(self):
        time_str = self.timestamp.strftime('%d.%m.%Y %H:%M') if self.timestamp else 'Neu'
        return f"#{self.pk} [{time_str}] {self.exception_type} an {self.path}"


@receiver(post_save, sender=SystemTranslation)
@receiver(post_delete, sender=SystemTranslation)
def _on_translation_change(sender, **kwargs):
    safe_cache_delete('system_translations')
    invalidate_system_translations_cache()


@receiver(post_save, sender=NavigationItem)
@receiver(post_delete, sender=NavigationItem)
def _on_navigation_change(sender, **kwargs):
    safe_cache_delete('navigation_items')
    invalidate_navigation_cache()


@receiver(post_save, sender=GeneralConfiguration)
@receiver(post_delete, sender=GeneralConfiguration)
def _on_general_config_change(sender, **kwargs):
    safe_cache_delete('general_configuration')
    invalidate_general_configuration_cache()


@receiver(post_save, sender=SiteCustomization)
@receiver(post_delete, sender=SiteCustomization)
def _on_site_customization_change(sender, **kwargs):
    safe_cache_delete('site_customization')
    invalidate_site_customization_cache()


