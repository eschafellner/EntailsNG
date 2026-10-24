from django.contrib import admin
from django.db.models import Q


class RealNameFilter(admin.SimpleListFilter):
    """Admin-Filter "Name fehlt / vorhanden" für Benutzer (prefix '') oder Anmeldungen (prefix 'user__')."""
    title = 'Echter Name'
    parameter_name = 'real_name'
    prefix = ''

    def lookups(self, request, model_admin):
        return (('missing', 'Name fehlt'), ('present', 'Name vorhanden'))

    def queryset(self, request, queryset):
        missing = Q(**{f'{self.prefix}first_name': ''}) | Q(**{f'{self.prefix}last_name': ''})
        if self.value() == 'missing':
            return queryset.filter(missing)
        if self.value() == 'present':
            return queryset.exclude(missing)
        return queryset


class RegistrationRealNameFilter(RealNameFilter):
    prefix = 'user__'
