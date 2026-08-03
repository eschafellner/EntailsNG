from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'birthday', 'is_staff')

    # Fügt die neuen Felder zum Bearbeitungs-Formular hinzu
    fieldsets = UserAdmin.fieldsets + (
        ('EntailsNG Profil', {'fields': ('role', 'birthday')}),
    )

