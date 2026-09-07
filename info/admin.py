from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import EventInfo


@admin.register(EventInfo)
class EventInfoAdmin(admin.ModelAdmin):
    list_display = (
        'order',
        'title',
        'slug',
        'show_in_nav_badge',
        'login_required_badge',
        'is_active',
        'updated_at',
        'view_on_site_link',
    )
    list_display_links = ('title', 'slug')
    list_editable = ('order', 'is_active')
    list_filter = ('is_active', 'show_in_nav', 'login_required')
    search_fields = ('title', 'subtitle', 'slug', 'content')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('created_at', 'updated_at', 'nav_item_display')

    fieldsets = (
        (None, {
            'fields': (
                'title',
                'subtitle',
                'slug',
                'content',
            )
        }),
        ('Navigation & Menü', {
            'fields': (
                'show_in_nav',
                'nav_icon',
                'order',
                'nav_item_display',
            ),
            'description': (
                'Wenn "In Hauptnavigation anzeigen" aktiviert ist, wird diese Seite automatisch '
                'als Menüpunkt in der linken Seitenleiste eingetragen und beim Löschen wieder entfernt.'
            )
        }),
        ('Zugriff & Status', {
            'fields': (
                'is_active',
                'login_required',
            ),
            'description': (
                'Aktiviere "Nur für angemeldete Benutzer", wenn diese Seite sensible Daten enthält '
                '(z. B. WLAN-Zugangsdaten oder Discord-Helfer-Links).'
            )
        }),
        ('System-Informationen', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description="Im Menü?")
    def show_in_nav_badge(self, obj):
        if obj.show_in_nav:
            return mark_safe(
                '<span style="background: #14532d; color: #86efac; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">✓ Menüpunkt</span>'
            )
        return mark_safe(
            '<span style="background: #374151; color: #9ca3af; padding: 2px 8px; border-radius: 4px; font-size: 11px;">Nur Tabs</span>'
        )

    @admin.display(description="Zugriff")
    def login_required_badge(self, obj):
        if obj.login_required:
            return mark_safe(
                '<span style="background: #78350f; color: #fde68a; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">🔒 Login nötig</span>'
            )
        return mark_safe(
            '<span style="background: #1e3a8a; color: #bfdbfe; padding: 2px 8px; border-radius: 4px; font-size: 11px;">🌐 Öffentlich</span>'
        )

    @admin.display(description="Verknüpfter Menüpunkt")
    def nav_item_display(self, obj):
        if obj.nav_item:
            return format_html(
                '<span>ID #{} – <b>{}</b> (Icon: {})</span>',
                obj.nav_item.id,
                obj.nav_item.title,
                obj.nav_item.icon_name,
            )
        return "Kein Menüpunkt verknüpft (wird automatisch angelegt, wenn oben ausgewählt)"

    @admin.display(description="Live-Vorschau")
    def view_on_site_link(self, obj):
        if not obj.pk:
            return "-"
        url = obj.get_absolute_url()
        return format_html(
            '<a href="{}" target="_blank" style="background: #2563eb; color: white; padding: 3px 8px; border-radius: 4px; text-decoration: none; font-size: 11px; font-weight: bold;">🔗 Öffnen</a>',
            url,
        )
