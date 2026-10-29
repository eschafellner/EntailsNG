from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from configuration.translations import get_translation as tr
from configuration.models import GeneralConfiguration
from .models import GuestPhoto, User, UserBan
from .forms import UserBanActionForm
from .admin_filters import RealNameFilter
from .exceptions import UserBanError
from . import moderation


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = (
        'username',
        'real_name',
        'email',
        'role',
        'failed_login_attempts',
        'locked_until',
        'is_staff',
        'is_banned',
        'deleted_at',
    )
    readonly_fields = ('deleted_at', 'is_banned', 'email_verified')
    list_filter = UserAdmin.list_filter + ('is_banned', RealNameFilter)
    change_form_template = 'admin/users/user/change_form.html'

    @admin.display(description='Name', ordering='last_name')
    def real_name(self, obj):
        return obj.get_full_name() or '—'
    actions = ['action_unlock_accounts', 'action_anonymize_accounts']

    # Fügt die neuen Felder zum Bearbeitungs-Formular hinzu
    fieldsets = UserAdmin.fieldsets + (
        (
            'EntailsNG Profil & Sicherheit',
            {'fields': ('role', 'birthday', 'failed_login_attempts', 'locked_until', 'deleted_at', 'is_banned', 'email_verified')},
        ),
    )

    @admin.action(permissions=['change'], description="Login-Fehlversuchssperre zurücksetzen (keine Orga-Sperren)")
    def action_unlock_accounts(self, request, queryset):
        unlocked_count = 0
        for user in queryset:
            if user.deleted_at or user.is_banned:
                continue
            user.reset_lockout()
            unlocked_count += 1
        self.message_user(
            request, f"{unlocked_count} Benutzerkonto/en erfolgreich entsperrt."
        )

    def has_change_permission(self, request, obj=None):
        if obj and obj.deleted_at:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        # F-024: Konten mit Anmeldungen werden anonymisiert statt gelöscht.
        if obj is not None and (obj.is_banned or obj.registrations.exists()):
            return False
        return super().has_delete_permission(request, obj)

    @admin.action(permissions=['delete'], description="Konto anonymisieren (Anmeldungen bleiben erhalten)")
    def action_anonymize_accounts(self, request, queryset):
        from .exceptions import AccountDeletionError
        from .services import UserService
        users = list(queryset.order_by('pk'))
        if request.POST.get('confirm') != 'yes':
            return TemplateResponse(request, 'admin/users/user/anonymize_confirmation.html', {
                **self.admin_site.each_context(request), 'opts': self.model._meta,
                'title': tr('admin_user_anonymize_title'), 'users': users,
                'action_checkbox_name': admin.helpers.ACTION_CHECKBOX_NAME,
            })
        done = 0
        for user in users:
            if user.pk == request.user.pk:
                reason = tr('admin_user_anonymize_self')
            elif user.is_banned:
                reason = tr('admin_user_anonymize_banned')
            else:
                try:
                    UserService.delete_account(user, None, verify_password=False)
                except AccountDeletionError as exc:
                    reason = str(exc)
                else:
                    done += 1
                    continue
            self.message_user(request, tr('admin_user_anonymize_skipped', username=user.username, reason=reason),
                              level='warning')
        self.message_user(request, tr('admin_user_anonymize_done', count=done))

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (('is_active', 'email', 'username', 'password') if obj and obj.is_banned else ())

    def get_urls(self):
        return [path('<int:object_id>/moderation/', self.admin_site.admin_view(self.moderation_view),
                     name='users_user_moderation')] + super().get_urls()

    def change_view(self, request, object_id, form_url='', extra_context=None):
        obj = self.get_object(request, object_id)
        context = dict(extra_context or {})
        context['can_manage_bans'] = bool(obj and not obj.deleted_at and moderation.can_manage_bans(request.user)
            and self.has_change_permission(request, obj))
        return super().change_view(request, object_id, form_url, context)

    def moderation_view(self, request, object_id):
        from django.shortcuts import get_object_or_404
        obj = get_object_or_404(User, pk=object_id)
        if not moderation.can_manage_bans(request.user) or not self.has_change_permission(request, obj):
            raise PermissionDenied
        if request.method not in ('GET', 'POST'):
            return HttpResponseNotAllowed(['GET', 'POST'])
        active = obj.orga_bans.filter(revoked_at__isnull=True).first()
        form = UserBanActionForm(request.POST if request.method == 'POST' else None,
            initial={'expected_state': moderation.ban_state(obj)})
        if request.method == 'POST' and form.is_valid():
            try:
                if request.POST.get('action') == 'revoke' and active:
                    moderation.revoke_ban(active.pk, actor=request.user, reason=form.cleaned_data['reason'],
                        expected_state=form.cleaned_data['expected_state'])
                    text = tr('ban_revoke_success')
                elif request.POST.get('action') == 'ban' and not active:
                    ban = moderation.ban_user(obj.pk, actor=request.user, reason=form.cleaned_data['reason'],
                        expected_state=form.cleaned_data['expected_state'])
                    text = tr('ban_success')
                    if not ban.email_identities.exists():
                        self.message_user(request, tr('ban_email_unverified'), level='warning')
                else:
                    raise UserBanError(tr('ban_stale'))
            except UserBanError as exc:
                form.add_error(None, str(exc))
            else:
                self.message_user(request, text)
                return redirect('admin:users_user_change', obj.pk)
        return TemplateResponse(request, 'admin/users/user/moderation.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'original': obj,
            'title': tr('ban_manage'), 'target_user': obj, 'form': form, 'active_ban': active,
            'ban_logs': obj.orga_bans.prefetch_related('logs__actor'),
        })


@admin.register(UserBan)
class UserBanAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'user', 'active', 'created_at', 'created_by', 'revoke_link')
    list_filter = ('revoked_at',)
    search_fields = ('user__username', 'user__email', 'reason')
    readonly_fields = ('user', 'reason', 'created_at', 'created_by', 'revoked_at', 'revoked_by', 'revoke_reason', 'history', 'revoke_link')
    fields = readonly_fields
    change_list_template = 'admin/users/userban/change_list.html'

    def has_view_permission(self, request, obj=None):
        return moderation.can_manage_bans(request.user)

    def has_module_permission(self, request):
        return moderation.can_manage_bans(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [path('email/', self.admin_site.admin_view(self.email_view), name='users_userban_email'),
                path('<int:object_id>/revoke/', self.admin_site.admin_view(self.revoke_view), name='users_userban_revoke')] + super().get_urls()

    @admin.display(boolean=True, description='Aktive Sperre')
    def active(self, obj):
        return obj.is_active

    @admin.display(description='Sperre aufheben')
    def revoke_link(self, obj):
        if obj.is_active:
            return format_html('<a href="{}">{}</a>', reverse('admin:users_userban_revoke', args=[obj.pk]), tr('ban_revoke'))
        return '—'

    @admin.display(description='Änderungshistorie')
    def history(self, obj):
        from django.utils.html import format_html_join
        return format_html_join('', '<p>{} · {} · {}<br>{}</p>',
            ((entry.created_at, entry.actor or '—', entry.get_action_display(), entry.reason) for entry in obj.logs.select_related('actor')))

    def email_view(self, request):
        return self.action_view(request, email_action=True)

    def revoke_view(self, request, object_id):
        from django.shortcuts import get_object_or_404
        return self.action_view(request, ban=get_object_or_404(UserBan, pk=object_id))

    def action_view(self, request, *, ban=None, email_action=False):
        if not moderation.can_manage_bans(request.user):
            raise PermissionDenied
        if request.method not in ('GET', 'POST'):
            return HttpResponseNotAllowed(['GET', 'POST'])
        form = UserBanActionForm(request.POST if request.method == 'POST' else None, email_action=email_action)
        if request.method == 'POST' and form.is_valid():
            try:
                if email_action:
                    moderation.ban_email(form.cleaned_data['email'], actor=request.user, reason=form.cleaned_data['reason'])
                else:
                    moderation.revoke_ban(ban.pk, actor=request.user, reason=form.cleaned_data['reason'])
            except (UserBanError, ValidationError) as exc:
                form.add_error(None, str(exc))
            else:
                self.message_user(request, tr('ban_success' if email_action else 'ban_revoke_success'))
                return redirect('admin:users_userban_changelist')
        return TemplateResponse(request, 'admin/users/user/moderation.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta, 'title': tr('ban_manage'),
            'form': form, 'active_ban': ban, 'email_action': email_action,
        })


@admin.register(GuestPhoto)
class GuestPhotoAdmin(admin.ModelAdmin):
    """Nur ansehen und löschen; Fotos entstehen ausschließlich über den bereinigenden Service."""
    list_display = ('user', 'thumbnail', 'source', 'uploaded_by', 'captured_at', 'notice_confirmed_at', 'delete_after')
    list_filter = ('source',)
    list_select_related = ('user', 'uploaded_by')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('user', 'preview', 'source', 'uploaded_by', 'captured_at', 'notice_confirmed_at', 'delete_after')
    fields = readonly_fields
    change_list_template = 'admin/users/guestphoto/change_list.html'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), 'can_delete_all': self.has_delete_permission(request)}
        return super().changelist_view(request, extra_context=extra_context)

    def get_urls(self):
        return [path('delete-all/', self.admin_site.admin_view(self.delete_all_view),
                     name='users_guestphoto_delete_all')] + super().get_urls()

    def _image(self, obj, size):
        # Gleiche Regel wie die Fotoausgabe: Mitarbeiter sehen Fotos nur bei aktivem erweitertem Check-in.
        if not GeneralConfiguration.load().extended_checkin_enabled:
            return tr('guest_photo_admin_hidden')
        url = f"{reverse('guest_photo', args=[obj.user_id])}?v={int(obj.captured_at.timestamp())}"
        return format_html('<img src="{}" alt="" width="{}" height="{}" style="object-fit: cover; border-radius: 6px;">',
                           url, size, size)

    @admin.display(description='Foto')
    def thumbnail(self, obj):
        return self._image(obj, 48)

    @admin.display(description='Foto')
    def preview(self, obj):
        return self._image(obj, 240)

    def delete_all_view(self, request):
        if not self.has_delete_permission(request):
            raise PermissionDenied
        if request.method not in ('GET', 'POST'):
            return HttpResponseNotAllowed(['GET', 'POST'])
        count = GuestPhoto.objects.count()
        if request.method == 'POST':
            with transaction.atomic():
                # Die Dateien entfernt der post_delete-Handler nach dem Commit.
                deleted = GuestPhoto.objects.all().delete()[1].get(GuestPhoto._meta.label, 0)
            self.message_user(request, tr('guest_photo_admin_deleted', count=deleted))
            return redirect('admin:users_guestphoto_changelist')
        return TemplateResponse(request, 'admin/users/guestphoto/delete_all.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': tr('guest_photo_admin_delete_all'), 'photo_count': count,
        })
