from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = (
        'username',
        'email',
        'role',
        'failed_login_attempts',
        'locked_until',
        'is_staff',
        'deleted_at',
    )
    readonly_fields = ('deleted_at',)
    actions = ['action_unlock_accounts']

    # Fügt die neuen Felder zum Bearbeitungs-Formular hinzu
    fieldsets = UserAdmin.fieldsets + (
        (
            'EntailsNG Profil & Sicherheit',
            {'fields': ('role', 'birthday', 'failed_login_attempts', 'locked_until', 'deleted_at')},
        ),
    )

    @admin.action(description="🔓 Gewählte Benutzerkonten sofort entsperren")
    def action_unlock_accounts(self, request, queryset):
        unlocked_count = 0
        for user in queryset:
            if user.deleted_at:
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


