from django.contrib import admin
from .models import Clan, ClanMembership


class ClanMembershipInline(admin.TabularInline):
    model = ClanMembership
    extra = 1
    raw_id_fields = ('user',)


@admin.register(Clan)
class ClanAdmin(admin.ModelAdmin):
    list_display = ('name', 'website', 'member_count', 'created_at')
    search_fields = ('name', 'website')
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
