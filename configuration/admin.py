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
    list_display = ('order', 'title', 'url_name', 'badge_text', 'is_active')
    list_display_links = ('title',)  # Verhindert den Django admin.E124 Fehler
    list_editable = ('order', 'is_active')
    ordering = ('order',)


from .models import GeneralConfiguration


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
                ),
                'description': (
                    'Steuerung der Ticket-Karte auf dem Dashboard (Anzeige, '
                    'Zeitraum vor Event und Zahlungs-Bedingungen).'
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        return not GeneralConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
