import re
import xml.etree.ElementTree as ET
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import NoReverseMatch, reverse

ALLOWED_SVG_TAGS = {
    'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon',
    'text', 'tspan', 'defs', 'clippath', 'mask', 'use', 'title', 'desc'
}
DISALLOWED_ATTRIBUTES_REGEX = re.compile(r'^(on|data-|formaction)', re.IGNORECASE)
DANGEROUS_PROTOCOLS_REGEX = re.compile(r'^\s*(javascript|data|vbscript):', re.IGNORECASE)


def sanitize_and_validate_svg(svg_code: str) -> str:
    """
    Validiert und bereinigt SVG-Code vor dem Speichern.
    Verhindert Stored-XSS, Script-Injections und gefährliche Attribute im Template (|safe).
    """
    if not svg_code or not svg_code.strip():
        return ""

    raw = svg_code.strip()

    # Schutz vor XXE / DTD Injections
    if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():
        raise ValidationError({'icon_svg': "SVG darf keine DOCTYPE- oder ENTITY-Deklarationen enthalten."})

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValidationError({'icon_svg': f"Ungültiger SVG/XML-Code: {e}"})

    def clean_tag(tag):
        if '}' in tag:
            return tag.split('}', 1)[1].lower()
        return tag.lower()

    if clean_tag(root.tag) != 'svg':
        raise ValidationError({'icon_svg': "Wurzelelement muss ein <svg>-Tag sein."})

    for elem in root.iter():
        tag_name = clean_tag(elem.tag)
        if tag_name not in ALLOWED_SVG_TAGS:
            raise ValidationError({'icon_svg': f"Nicht erlaubtes SVG-Tag '<{tag_name}>' im Icon-Code gefunden."})

        for attr, val in list(elem.attrib.items()):
            attr_clean = clean_tag(attr)
            if DISALLOWED_ATTRIBUTES_REGEX.match(attr_clean):
                raise ValidationError({'icon_svg': f"Nicht erlaubtes Attribut '{attr}' im SVG gefunden."})
            if attr_clean in ('href', 'xlink:href', 'src') and DANGEROUS_PROTOCOLS_REGEX.match(str(val)):
                raise ValidationError({'icon_svg': f"Gefährliche URI im Attribut '{attr}' gefunden."})

    return raw


class NavigationItem(models.Model):
    title = models.CharField(
        max_length=100,
        help_text='Anzeigename im Menü (z. B. Übersicht, Sitzplan)',
    )
    url_name = models.CharField(
        max_length=100,
        help_text='Django URL-Name, z. B. dashboard, news_list, seating_plan',
    )
    icon_svg = models.TextField(
        blank=True, help_text='SVG-Code für das Icon (20x20px empfohlen)'
    )
    badge_text = models.CharField(
        max_length=10, blank=True, default='',
        help_text='Optionales Badge, z. B. "2" oder "NEU"',
    )
    order = models.PositiveIntegerField(
        default=0, help_text='Kleinere Zahlen stehen weiter oben bzw. links'
    )
    is_active = models.BooleanField(default=True, help_text='Im Menü anzeigen?')

    ALIAS_MAP = {
        'info': 'event_info_detail',
        'seating': 'seating_plan',
        'news': 'news_list',
    }

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Menüpunkt'
        verbose_name_plural = 'Menüpunkte'

    def __str__(self):
        return f'{self.order}. {self.title} ({self.url_name})'


    def clean(self):
        """Verhindert Tippfehler und schützt vor XSS in SVG-Icons."""
        target = self.ALIAS_MAP.get(self.url_name, self.url_name)
        try:
            reverse(target)
        except NoReverseMatch:
            raise ValidationError({
                'url_name': (
                    f'"{self.url_name}" ist kein bekannter URL-Name. '
                    'Gültig sind z. B.: dashboard, event_info_detail, '
                    'news_list, seating_plan.'
                )
            })

        if self.icon_svg:
            self.icon_svg = sanitize_and_validate_svg(self.icon_svg)


    def get_url(self):
        target = self.ALIAS_MAP.get(self.url_name, self.url_name)
        try:
            return reverse(target)
        except NoReverseMatch:
            return ''

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete('navigation_items')

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        cache.delete('navigation_items')


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
        cache.delete('system_translations')

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        cache.delete('system_translations')


class FeatureFlag(models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name='Feature Name',
        help_text='Lesbarer Name der Funktion (z. B. Onboarding Ticket)',
    )
    key = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='Schlüssel (Key)',
        help_text='Eindeutiger Bezeichner (z. B. onboarding_ticket, seating_module)',
    )
    is_enabled = models.BooleanField(
        default=True,
        verbose_name='Aktiviert',
        help_text='Schaltet dieses Feature im System ein oder aus',
    )
    description = models.TextField(
        blank=True,
        verbose_name='Beschreibung',
        help_text='Erläuterung zur Funktion dieses Feature Flags',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'Feature Flag'
        verbose_name_plural = 'Feature Flags'

    def __str__(self):
        status = 'Aktiv' if self.is_enabled else 'Inaktiv'
        return f'{self.name} ({self.key}): {status}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete('feature_flags_dict')

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        cache.delete('feature_flags_dict')


class GeneralConfiguration(models.Model):
    """
    Zentrale allgemeine Konfiguration für Systemeinstellungen (z. B. Ticket-Anzeige).
    Singleton-Muster: Es existiert nur 1 Datensatz in der Datenbank (pk=1).
    """

    class ExpiredTicketMode(models.TextChoices):
        WORN = 'WORN', 'Ticket abgenutzt (Mit "Veranstaltung beendet" Hinweis anzeigen)'
        HIDE = 'HIDE', 'Event beendet (Automatisch ausblenden bei Event-Ende)'

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



    class Meta:
        verbose_name = "Allgemeine Konfiguration"
        verbose_name_plural = "Allgemeine Konfiguration"

    def __str__(self):
        return "Allgemeine Konfiguration"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete('general_configuration')


    def delete(self, *args, **kwargs):
        pass  # Verhindert das Löschen der Einstellungen

    @classmethod
    def load(cls):
        conf = cache.get('general_configuration')
        if conf is None:
            conf, _ = cls.objects.get_or_create(pk=1)
            cache.set('general_configuration', conf, 300)
        return conf


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
        verbose_name='Benutzerdefinierte Hauptfarbe (--navy)',
        help_text='Hex-Code (z. B. #332719). Überschreibt die Hauptfarbe der Sidebar/Header.',
    )
    background_color = models.CharField(
        max_length=20,
        blank=True,
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
        default='<h3>Datenschutzerklärung</h3><p>Informationen zum Datenschutz...</p>',
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

    def __str__(self):
        return f'Individualisierung & Branding ({self.get_theme_preset_display()})'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete_many(['site_customization', 'system_translations', 'navigation_items'])


    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def load(cls):
        custom = cache.get('site_customization')
        if custom is None:
            custom, _ = cls.objects.get_or_create(pk=1)
            cache.set('site_customization', custom, 300)
        return custom

    def get_css_variables(self):
        """Liefert ein Dictionary mit CSS-Variablen basierend auf Preset, Farben & UI-Skalierung."""
        presets = {
            self.ThemePreset.WARM_AMBER: {
                '--ink': '#2b2115',
                '--muted': '#6f6252',
                '--line': '#e7dac8',
                '--paper': '#fffaf2',
                '--panel': '#ffffff',
                '--navy': '#332719',
                '--signal': '#f8ab2d',
                '--signal-deep': '#8a4d00',
                '--signal-soft': '#fff0d2',
                '--amber': '#d97817',
                '--amber-soft': '#ffead0',
            },
            self.ThemePreset.CYBERPUNK: {
                '--ink': '#e2e8f0',
                '--muted': '#94a3b8',
                '--line': '#2a2d3d',
                '--paper': '#0f111a',
                '--panel': '#181b29',
                '--navy': '#0b0d14',
                '--signal': '#00f0ff',
                '--signal-deep': '#ff0055',
                '--signal-soft': 'rgba(0, 240, 255, 0.15)',
                '--amber': '#ff0055',
                '--amber-soft': 'rgba(255, 0, 85, 0.15)',
            },
            self.ThemePreset.SLATE_BLUE: {
                '--ink': '#1e293b',
                '--muted': '#64748b',
                '--line': '#cbd5e1',
                '--paper': '#f8fafc',
                '--panel': '#ffffff',
                '--navy': '#0f172a',
                '--signal': '#3b82f6',
                '--signal-deep': '#1d4ed8',
                '--signal-soft': '#dbeafe',
                '--amber': '#2563eb',
                '--amber-soft': '#eff6ff',
            },
            self.ThemePreset.EMERALD: {
                '--ink': '#111827',
                '--muted': '#4b5563',
                '--line': '#d1d5db',
                '--paper': '#f3f4f6',
                '--panel': '#ffffff',
                '--navy': '#064e3b',
                '--signal': '#10b981',
                '--signal-deep': '#047857',
                '--signal-soft': '#d1fae5',
                '--amber': '#059669',
                '--amber-soft': '#ecfdf5',
            },
        }

        base_vars = presets.get(self.theme_preset, presets[self.ThemePreset.WARM_AMBER]).copy()

        if self.primary_color:
            base_vars['--signal'] = self.primary_color
            base_vars['--amber'] = self.primary_color
        if self.secondary_color:
            base_vars['--navy'] = self.secondary_color
        if self.background_color:
            base_vars['--paper'] = self.background_color

        scale_map = {
            self.UIScale.VERY_SMALL: {
                '--font-base': '13px',
                '--font-xs': '10px',
                '--font-sm': '11px',
                '--font-md': '13px',
                '--font-lg': '15px',
                '--font-xl': '18px',
                '--font-2xl': '22px',
                '--font-3xl': '28px',
                '--sidebar': '220px',
                '--card-padding': '16px',
                '--btn-height': '34px',
                '--input-height': '36px',
                '--radius': '14px',
                '--nav-item-height': '36px',
                '--nav-font-size': '12px',
                '--nav-icon-size': '16px',
                '--nav-badge-font-size': '9px',
                '--nav-padding': '0 10px',
                '--foot-font-size': '11px',
                '--mobile-item-height': '52px',
                '--mobile-font-size': '10px',
                '--mobile-icon-size': '18px',
            },
            self.UIScale.SMALL: {
                '--font-base': '14px',
                '--font-xs': '10.5px',
                '--font-sm': '12px',
                '--font-md': '14px',
                '--font-lg': '16.5px',
                '--font-xl': '20px',
                '--font-2xl': '25px',
                '--font-3xl': '31px',
                '--sidebar': '235px',
                '--card-padding': '20px',
                '--btn-height': '38px',
                '--input-height': '39px',
                '--radius': '16px',
                '--nav-item-height': '39px',
                '--nav-font-size': '13px',
                '--nav-icon-size': '18px',
                '--nav-badge-font-size': '10px',
                '--nav-padding': '0 12px',
                '--foot-font-size': '12px',
                '--mobile-item-height': '57px',
                '--mobile-font-size': '10.5px',
                '--mobile-icon-size': '20px',
            },
            self.UIScale.MEDIUM: {
                '--font-base': '15px',
                '--font-xs': '11px',
                '--font-sm': '13px',
                '--font-md': '15px',
                '--font-lg': '18px',
                '--font-xl': '22px',
                '--font-2xl': '28px',
                '--font-3xl': '35px',
                '--sidebar': '246px',
                '--card-padding': '24px',
                '--btn-height': '42px',
                '--input-height': '42px',
                '--radius': '18px',
                '--nav-item-height': '42px',
                '--nav-font-size': '14px',
                '--nav-icon-size': '19px',
                '--nav-badge-font-size': '10px',
                '--nav-padding': '0 13px',
                '--foot-font-size': '13px',
                '--mobile-item-height': '62px',
                '--mobile-font-size': '11px',
                '--mobile-icon-size': '21px',
            },
            self.UIScale.LARGE: {
                '--font-base': '16px',
                '--font-xs': '12px',
                '--font-sm': '14px',
                '--font-md': '16px',
                '--font-lg': '19.5px',
                '--font-xl': '24px',
                '--font-2xl': '31px',
                '--font-3xl': '39px',
                '--sidebar': '260px',
                '--card-padding': '28px',
                '--btn-height': '46px',
                '--input-height': '45px',
                '--radius': '20px',
                '--nav-item-height': '46px',
                '--nav-font-size': '15px',
                '--nav-icon-size': '21px',
                '--nav-badge-font-size': '11px',
                '--nav-padding': '0 14px',
                '--foot-font-size': '14px',
                '--mobile-item-height': '68px',
                '--mobile-font-size': '12px',
                '--mobile-icon-size': '23px',
            },
            self.UIScale.VERY_LARGE: {
                '--font-base': '17px',
                '--font-xs': '13px',
                '--font-sm': '15px',
                '--font-md': '17px',
                '--font-lg': '21px',
                '--font-xl': '26px',
                '--font-2xl': '34px',
                '--font-3xl': '43px',
                '--sidebar': '275px',
                '--card-padding': '32px',
                '--btn-height': '50px',
                '--input-height': '48px',
                '--radius': '22px',
                '--nav-item-height': '50px',
                '--nav-font-size': '16px',
                '--nav-icon-size': '23px',
                '--nav-badge-font-size': '12px',
                '--nav-padding': '0 16px',
                '--foot-font-size': '15px',
                '--mobile-item-height': '74px',
                '--mobile-font-size': '13px',
                '--mobile-icon-size': '25px',
            },
        }

        scale_vars = scale_map.get(self.ui_scale, scale_map[self.UIScale.MEDIUM])
        base_vars.update(scale_vars)

        return base_vars





