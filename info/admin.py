from django.contrib import admin
from .models import EventInfo


@admin.register(EventInfo)
class EventInfoAdmin(admin.ModelAdmin):
    list_display = ("title", "subtitle", "updated_at")

    # Verhindert das Erstellen mehrerer Datensätze, wenn bereits einer existiert
    def has_add_permission(self, request):
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)
