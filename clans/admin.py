from django.contrib import admin
from .models import Clan, ClanMembership
from seating.clan_admin_forms import ClanQuotaForm


class ClanMembershipInline(admin.TabularInline):
    model = ClanMembership
    extra = 1
    raw_id_fields = ('user',)


@admin.register(Clan)
class ClanAdmin(admin.ModelAdmin):
    form = ClanQuotaForm

    def changeform_view(self, request, *args, **kwargs):
        from django.db import transaction
        from seating.clan_services import lock_configuration
        if request.method == 'POST':
            with transaction.atomic():
                lock_configuration()
                return super().changeform_view(request, *args, **kwargs)
        return super().changeform_view(request, *args, **kwargs)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        form.apply_releases()

    list_display = ('name', 'tag', 'website', 'member_count', 'seat_limit_override', 'created_at')
    search_fields = ('name', 'tag', 'website')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ClanMembershipInline]

    @admin.display(description="Mitglieder")
    def member_count(self, obj):
        return obj.memberships.filter(status=ClanMembership.Status.ACCEPTED).count()


@admin.register(ClanMembership)
class ClanMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'clan', 'role', 'status', 'created_at')
    list_filter = ('role', 'status', 'clan')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'clan__name')
    raw_id_fields = ('user', 'clan')
