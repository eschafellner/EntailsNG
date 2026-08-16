# configuration/admin.py
from django.contrib import admin
from .models import FeatureFlag, NavigationItem, SystemTranslation


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'is_enabled', 'description')
    list_editable = ('is_enabled',)
    search_fields = ('name', 'key', 'description')
    ordering = ('name',)


@admin.register(SystemTranslation)
class SystemTranslationAdmin(admin.ModelAdmin):
    list_display = ('key', 'text')
    search_fields = ('key', 'text')


@admin.register(NavigationItem)
class NavigationItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'title', 'url_name', 'icon_name', 'badge_text', 'is_active')
    list_display_links = ('title',)  # Verhindert den Django admin.E124 Fehler
    list_editable = ('order', 'is_active')
    ordering = ('order',)
    fields = ('title', 'url_name', 'icon_name', 'icon_svg', 'badge_text', 'order', 'is_active')

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            # Roher SVG-Code ist nur für Superuser editierbar (Staff nutzt die sichere icon_name Auswahlliste)
            if 'icon_svg' not in readonly:
                readonly.append('icon_svg')
        return readonly


from django.urls import path
from django.shortcuts import redirect, render
from django.contrib import messages
from django.core.management import call_command
from django.utils.safestring import mark_safe
from .models import GeneralConfiguration, SiteCustomization


@admin.register(GeneralConfiguration)
class GeneralConfigurationAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            'Ticket-Anzeige Steuerung',
            {
                'fields': (
                    'ticket_enabled',
                    'ticket_days_before_event',
                    'ticket_requires_payment',
                    'expired_ticket_mode',
                ),
                'description': (
                    'Steuerung der Ticket-Karte auf dem Dashboard (Anzeige, '
                    'Zeitraum vor Event, Zahlungs-Bedingungen und Verhalten bei Event-Ende).'
                ),
            },
        ),
        (
            'System-Diagnose & Fehleranalyse',
            {
                'fields': (
                    'debug_mode',
                ),
                'description': (
                    'Ermöglicht das temporäre Einschalten der detaillierten technischen Django-Debugseite '
                    'im Fehlerfall direkt im Browser. Im Live-Betrieb sollte dies standardmäßig deaktiviert sein.'
                ),
            },
        ),
    )


    def has_add_permission(self, request):
        return not GeneralConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SiteCustomization)
class SiteCustomizationAdmin(admin.ModelAdmin):
    readonly_fields = ('theme_preset_preview', 'reset_demo_data_button')

    fieldsets = (
        (
            'Branding & Markenidentität',
            {
                'fields': (
                    'site_name',
                    'brand_accent_text',
                    'site_tagline',
                    'logo',
                ),
                'description': 'Name, Akzentwort, Untertitel und optionales Logo-Bild für den Header/Sidebar.',
            },
        ),
        (
            'Design-Theme & Darstellungsgröße',
            {
                'fields': (
                    'theme_preset',
                    'theme_preset_preview',
                    'ui_scale',
                    'primary_color',
                    'secondary_color',
                    'background_color',
                ),
                'description': 'Wähle ein vorgefertigtes Farbschema und die System-Darstellungsgröße (Sehr klein, Klein, Mittel, Groß, Sehr groß) für das gesamte Frontend.',
            },
        ),
        (
            'Rechtliche Hinweise (Footer & Modals)',
            {
                'fields': (
                    'impressum_content',
                    'datenschutz_content',
                ),
                'description': 'Inhalte für Impressum und Datenschutz.',
            },
        ),
        (
            'Erweiterte Anpassung & Wartung',
            {
                'fields': (
                    'custom_css',
                    'reset_demo_data_button',
                ),
                'description': 'Eigenes CSS injizieren oder das System auf Werkseinstellungen / Demo-Daten zurücksetzen.',
            },
        ),
    )

    def reset_demo_data_button(self, obj):
        return mark_safe(
            '<a href="/admin/configuration/sitecustomization/reset-demo-data/" '
            'style="background:#dc2626; color:#ffffff; font-weight:bold; padding:8px 14px; border-radius:6px; text-decoration:none; display:inline-block;">'
            '🔄 System auf Demo-Daten zurücksetzen'
            '</a>'
        )
    reset_demo_data_button.short_description = "Demo-Daten Reset"


    def theme_preset_preview(self, obj):
        swatches = [
            ("WARM_AMBER", "Warm Amber (Default)", "#f59e0b", "#10b981", "#0b0f17"),
            ("CYBERPUNK", "Cyberpunk Neon", "#06b6d4", "#ec4899", "#090d16"),
            ("SLATE_BLUE", "Slate Blue", "#3b82f6", "#8b5cf6", "#0f172a"),
            ("EMERALD", "Emerald Gaming", "#10b981", "#f59e0b", "#06130e"),
        ]
        html = ['<div style="display: flex; gap: 14px; flex-wrap: wrap; margin-top: 6px;">']
        for key, name, p, s, bg in swatches:
            is_active = (obj.theme_preset == key) if obj else (key == 'WARM_AMBER')
            border = '2px solid #22c55e' if is_active else '1px solid #374151'
            badge = ' <span style="background:#22c55e;color:#000;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:bold;">AKTIV</span>' if is_active else ''
            html.append(f'''
                <div style="background: {bg}; border: {border}; padding: 12px; border-radius: 8px; width: 175px; color: #fff; font-family: sans-serif; box-shadow: 0 4px 10px rgba(0,0,0,0.3);">
                    <div style="font-weight: bold; font-size: 12px; margin-bottom: 8px;">{name}{badge}</div>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <span style="background:{p}; width: 22px; height: 22px; border-radius: 50%; display: inline-block; border: 1px solid rgba(255,255,255,0.3);" title="Primärfarbe: {p}"></span>
                        <span style="background:{s}; width: 22px; height: 22px; border-radius: 50%; display: inline-block; border: 1px solid rgba(255,255,255,0.3);" title="Sekundärfarbe: {s}"></span>
                        <span style="background:{bg}; width: 22px; height: 22px; border-radius: 50%; display: inline-block; border: 1px solid rgba(255,255,255,0.3);" title="Hintergrund: {bg}"></span>
                    </div>
                </div>
            ''')
        html.append('</div>')
        return mark_safe(''.join(html))
    theme_preset_preview.short_description = "Vorschau der Farb-Themes (Color Swatches)"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('reset-demo-data/', self.admin_site.admin_view(self.reset_demo_data_view), name='reset_demo_data_admin'),
        ]
        return custom_urls + urls

    def reset_demo_data_view(self, request):
        if request.method == 'POST':
            call_command('reset_demo_data')
            messages.success(request, '🎉 Demo-Daten und System-Einstellungen wurden erfolgreich zurückgesetzt!')
            return redirect('/admin/configuration/sitecustomization/1/change/')
        return render(request, 'admin/reset_demo_data_confirm.html')

    def has_add_permission(self, request):
        return not SiteCustomization.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            # Sensible HTML/CSS-Felder dürfen nur von echten Superusern geändert werden
            for field in ('custom_css', 'impressum_content', 'datenschutz_content'):
                if field not in readonly:
                    readonly.append(field)
        return readonly


