from django.contrib import admin
from django.utils.html import format_html
from .models import Sponsor


@admin.register(Sponsor)
class SponsorAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'logo_typ',
        'aktiv_modus',
        'ist_aktiv_display',
        'rang',
        'erstellt_am',
    )
    list_filter = ('aktiv_modus', 'logo_typ')
    search_fields = ('name', 'beschreibung')
    ordering = ('rang', 'erstellt_am')
    readonly_fields = ('erstellt_am', 'aktualisiert_am')

    fieldsets = (
        (None, {
            'fields': (
                'name',
                'logo_typ',
                'bild',
                'url',
                'beschreibung',
                'rang',
            )
        }),
        ('Aktivierungs-Steuerung', {
            'fields': (
                'aktiv_modus',
                'veranstaltung',
                'aktiv_bis',
            ),
            'description': (
                'Wähle den Aktiv-Modus. Je nach Auswahl wird entweder eine Veranstaltung '
                'oder ein Enddatum zur automatischen Steuerung herangezogen.'
            )
        }),
        ('System-Informationen', {
            'fields': ('erstellt_am', 'aktualisiert_am'),
            'classes': ('collapse',),
        }),
    )

    class Media:
        js = ('js/admin_sponsor.js',)

    @admin.display(description="Aktiv?", boolean=True)
    def ist_aktiv_display(self, obj):
        """Zeigt im Admin an, ob der Sponsor aktuell fachlich aktiv ist."""
        return obj.ist_aktiv
