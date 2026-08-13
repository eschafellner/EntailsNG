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
    )
    actions = ['action_unlock_accounts']

    # Fügt die neuen Felder zum Bearbeitungs-Formular hinzu
    fieldsets = UserAdmin.fieldsets + (
        (
            'EntailsNG Profil & Sicherheit',
            {'fields': ('role', 'birthday', 'failed_login_attempts', 'locked_until')},
        ),
    )

    @admin.action(description="🔓 Gewählte Benutzerkonten sofort entsperren")
    def action_unlock_accounts(self, request, queryset):
        unlocked_count = 0
        for user in queryset:
            user.reset_lockout()
            unlocked_count += 1
        self.message_user(
            request, f"{unlocked_count} Benutzerkonto/en erfolgreich entsperrt."
        )


