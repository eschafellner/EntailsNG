from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path
from .models import EmailTemplate, GeneralEmailSettings
from .services import send_test_email


@admin.register(GeneralEmailSettings)
class GeneralEmailSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'sender_email', 'is_enabled', 'is_sandbox')

    fieldsets = (
        (
            'Allgemeine E-Mail Einstellungen',
            {
                'fields': ('sender_email', 'sender_name', 'is_enabled'),
                'description': 'Grundlegende Absender-Informationen und Hauptschalter für den E-Mail-Versand.',
            },
        ),
        (
            'Sandbox-Modus (Entwicklung & Tests)',
            {
                'fields': ('is_sandbox', 'sandbox_redirect_email'),
                'description': 'Wenn die Sandbox aktiv ist, werden sämtliche E-Mails an die Weiterleitungsadresse geschickt.',
            },
        ),
        (
            'SMTP-Server Einstellungen (Optional)',
            {
                'fields': (
                    'smtp_host',
                    'smtp_port',
                    'smtp_username',
                    'smtp_password',
                    'smtp_use_tls',
                ),
                'classes': ('collapse',),
                'description': 'Eigenen SMTP-Server konfigurieren. Wenn leer, werden die Standard-Systemeinstellungen verwendet.',
            },
        ),
    )

    def has_add_permission(self, request):
        # Singleton: Hinzufügen sperren, wenn bereits 1 Datensatz existiert
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        # Singleton: Löschen verhindern
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'send-test-email/',
                self.admin_site.admin_view(self.send_test_email_view),
                name='emails_send_test_email',
            ),
        ]
        return custom_urls + urls

    def send_test_email_view(self, request):
        settings = GeneralEmailSettings.load()
        target = settings.sandbox_redirect_email or settings.sender_email

        if request.method == 'POST':
            target_input = request.POST.get('target_email', '').strip()
            if target_input:
                target = target_input

            success, msg = send_test_email(target)
            if success:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
            return redirect('admin:emails_generalemailsettings_changelist')

        context = {
            'title': 'Test-E-Mail senden',
            'target_email': target,
            'opts': self.model._meta,
        }
        return render(request, 'emails/admin_send_test_email.html', context)


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'subject', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'key', 'subject')

    fieldsets = (
        (
            'Template Eigenschaften',
            {
                'fields': ('name', 'key', 'is_active'),
            },
        ),
        (
            'Inhalt & Editor',
            {
                'fields': ('subject', 'content', 'placeholder_info'),
                'description': 'Bearbeite die Betreffzeile und den HTML-Inhalt. Beachte die unten stehenden Platzhalter.',
            },
        ),
    )
    readonly_fields = ('key', 'placeholder_info')
