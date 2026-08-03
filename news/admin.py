from django.contrib import admin
from .models import NewsArticle


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "created_at", "is_published", "is_pinned")
    list_editable = ("is_published", "is_pinned")
    list_filter = ("is_published", "is_pinned", "created_at")
    search_fields = ("title", "content")
    readonly_fields = ("author", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        # Wenn noch kein Autor zugewiesen ist, automatisch den angemeldeten User setzen
        if not obj.author:
            obj.author = request.user
        super().save_model(request, obj, form, change)
