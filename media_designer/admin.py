from django.contrib import admin

from media_designer.models import MediaTemplate


@admin.register(MediaTemplate)
class MediaTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'paper_size', 'event', 'updated_at')
    list_filter = ('kind', 'paper_size', 'event')
    search_fields = ('name', 'event__title')
    readonly_fields = ('created_by', 'created_at', 'updated_at')

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
