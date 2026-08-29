from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .dns_checker import check_domain_dns_health
from .models import EmailTemplate, GeneralEmailSettings
from .services import send_test_email


class GeneralEmailSettingsForm(forms.ModelForm):
    smtp_password = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        required=False,
        label="SMTP-Passwort",
    )
    clear_smtp_password = forms.BooleanField(
        required=False,
        label="Gespeichertes Passwort löschen",
    )

    class Meta:
        model = GeneralEmailSettings
        exclude = (
            'last_test_at', 'last_test_ok', 'last_test_message',
            'last_send_error_at', 'last_send_error', 'credentials_broken',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        has_password = bool(self.instance and self.instance.smtp_password)
        if has_password:
            if self.instance.credentials_broken:
                self.fields['smtp_password'].help_text = (
                    "⚠️ Das gespeicherte Passwort kann nicht gelesen werden. "
                    "Bitte neu eingeben."
                )
            else:
                self.fields['smtp_password'].help_text = (
                    "🔒 Ein Passwort ist verschlüsselt hinterlegt. "
                    "Leer lassen, um es beizubehalten."
                )
            self.fields['clear_smtp_password'].widget = forms.CheckboxInput()
        else:
            self.fields['smtp_password'].help_text = (
                "Kein Passwort hinterlegt. Wird beim Speichern verschlüsselt."
            )
            self.fields['clear_smtp_password'].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        self._raw_password = cleaned.get('smtp_password') or ''
        self._clear_password = cleaned.get('clear_smtp_password', False)
        # Feld aus cleaned_data entfernen, damit ModelForm es nicht direkt im Klartext setzt
        cleaned.pop('smtp_password', None)
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self._clear_password:
            obj.set_smtp_password('')
        elif self._raw_password:
            obj.set_smtp_password(self._raw_password)
        if commit:
            obj.save()
        return obj


@admin.register(GeneralEmailSettings)
class GeneralEmailSettingsAdmin(admin.ModelAdmin):
    form = GeneralEmailSettingsForm
    list_display = ('__str__', 'transport_mode', 'sender_email', 'is_enabled', 'is_sandbox', 'test_state')

    fieldsets = (
        ('Status & Diagnose', {
            'fields': ('status_panel',),
        }),
        ('1. Versandweg', {
            'fields': ('transport_mode',),
            'description': (
                "Wähle, woher die Zugangsdaten kommen. 'Vom Server vorgegeben' "
                "nutzt die Konfiguration aus der .env-Datei."
            ),
        }),
        ('2. Absender', {
            'fields': ('sender_email', 'sender_name', 'reply_to_email'),
            'description': (
                "Die Absenderdomain muss bei deinem Mailanbieter verifiziert sein, "
                "sonst lehnt er den Versand ab."
            ),
        }),
        ('3. Eigener SMTP-Server', {
            'fields': (
                'smtp_host', 'smtp_port', 'smtp_username', 'smtp_password',
                'clear_smtp_password', 'smtp_use_tls', 'smtp_use_ssl',
                'smtp_timeout',
            ),
            'description': (
                "Nur nötig, wenn oben 'Eigener SMTP-Server' gewählt ist. "
                "Port 587 mit TLS, Port 465 mit SSL."
            ),
        }),
        ('4. Versand freigeben', {
            'fields': ('is_enabled',),
            'description': (
                "Erst einschalten, wenn der Verbindungstest erfolgreich war."
            ),
        }),
        ('Testmodus (Sandbox)', {
            'fields': ('is_sandbox', 'sandbox_redirect_email'),
            'description': (
                "Im Testmodus gehen ALLE E-Mails an die Weiterleitungsadresse — "
                "auch Registrierungsbestätigungen echter Gäste."
            ),
        }),
        ('Zustellbarkeit (DNS)', {
            'fields': ('domain_name',),
            'classes': ('collapse',),
            'description': 'Eure Haupt-Domain für die DNS-Zustellbarkeitsprüfung (SPF, DMARC, MX, DKIM).',
        }),
    )
    readonly_fields = ('status_panel',)

    @admin.display(boolean=True, description="Letzter Test")
    def test_state(self, obj):
        return obj.last_test_ok

    @admin.display(description="Aktueller Zustand")
    def status_panel(self, obj):
        rows = []

        reason = obj.blocking_reason
        if reason is None:
            rows.append(('ok', "E-Mail-Versand ist eingerichtet und aktiv."))
        elif obj.is_sandbox and obj.is_operational:
            rows.append(('info', reason))
        else:
            rows.append(('problem', reason))

        if obj.last_test_at:
            state = 'ok' if obj.last_test_ok else 'problem'
            when = obj.last_test_at.strftime('%d.%m.%Y %H:%M')
            rows.append((state, f"Letzter Verbindungstest ({when}): {obj.last_test_message}"))
        else:
            rows.append(('info', "Es wurde noch kein Verbindungstest durchgeführt."))

        if obj.last_send_error_at:
            when = obj.last_send_error_at.strftime('%d.%m.%Y %H:%M')
            rows.append(('problem', f"Letzter Versandfehler ({when}): {obj.last_send_error}"))

        colors = {'ok': '#166534', 'info': '#0369a1', 'problem': '#991b1b'}
        bg_colors = {'ok': 'rgba(22, 101, 52, 0.1)', 'info': 'rgba(3, 105, 161, 0.1)', 'problem': 'rgba(153, 27, 27, 0.1)'}
        
        html = ''.join(
            format_html(
                '<p style="margin:.4em 0;padding:.6em .8em;border-left:4px solid {};'
                'background:{};border-radius:4px;font-size:13px;">{}</p>',
                colors[state], bg_colors[state], text,
            )
            for state, text in rows
        )
        html += format_html(
            '<div style="margin-top:1.2em;display:flex;gap:10px;flex-wrap:wrap;">'
            '<a class="button" href="{}" style="padding:6px 12px;font-weight:600;">🔌 Verbindung testen</a> '
            '<a class="button" href="{}" style="padding:6px 12px;font-weight:600;">🌐 Zustellbarkeit (DNS) prüfen</a>'
            '</div>',
            reverse('admin:emails_send_test_email'),
            reverse('admin:emails_check_dns_health'),
        )
        return mark_safe(html)

    def has_add_permission(self, request):
        try:
            if self.model.objects.exists():
                return False
        except Exception:
            pass
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'send-test-email/',
                self.admin_site.admin_view(self.send_test_email_view),
                name='emails_send_test_email',
            ),
            path(
                'check-dns-health/',
                self.admin_site.admin_view(self.check_dns_health_view),
                name='emails_check_dns_health',
            ),
        ]
        return custom_urls + urls

    def check_dns_health_view(self, request):
        settings = GeneralEmailSettings.load()
        domain = settings.domain_name or (settings.sender_email.split('@')[-1] if '@' in settings.sender_email else '')
        dns_result = check_domain_dns_health(domain)

        context = {
            'title': 'Domain-Health Check & DNS-Assistent',
            'domain': domain,
            'dns_result': dns_result,
            'opts': self.model._meta,
        }
        return render(request, 'emails/admin_dns_check.html', context)

    def send_test_email_view(self, request):
        settings = GeneralEmailSettings.load()
        target = settings.sandbox_redirect_email or settings.sender_email or (request.user.email if request.user.email else '')

        if request.method == 'POST':
            target_input = request.POST.get('target_email', '').strip()
            if target_input:
                target = target_input

            success, msg = send_test_email(target)
            if success:
                messages.success(request, f"✓ {msg}")
            else:
                messages.error(request, f"✗ {msg}")
            return redirect('admin:emails_generalemailsettings_changelist')

        context = {
            'title': 'Verbindung testen',
            'target_email': target,
            'transport_mode': settings.get_transport_mode_display(),
            'sender_email': settings.sender_email or "(Keine Absenderadresse hinterlegt)",
            'opts': self.model._meta,
        }
        return render(request, 'emails/admin_send_test_email.html', context)


@admin.action(description="Ausgewählte Vorlagen aktivieren")
def activate_templates(modeladmin, request, queryset):
    updated = queryset.update(is_active=True)
    messages.success(request, f"{updated} Template(s) erfolgreich aktiviert.")


@admin.action(description="Ausgewählte Vorlagen deaktivieren")
def deactivate_templates(modeladmin, request, queryset):
    updated = queryset.update(is_active=False)
    messages.warning(request, f"{updated} Template(s) deaktiviert.")


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'subject', 'is_active', 'updated_at')
    list_editable = ('is_active',)
    list_filter = ('is_active',)
    search_fields = ('name', 'key', 'subject')
    actions = [activate_templates, deactivate_templates]

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
