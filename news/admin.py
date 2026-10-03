from django.contrib import admin
from django.db import models
from tinymce.widgets import AdminTinyMCE
from .models import NewsArticle


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "created_at", "is_published", "is_pinned")
    list_editable = ("is_published", "is_pinned")
    list_filter = ("is_published", "is_pinned", "created_at")
    search_fields = ("title", "content")
    readonly_fields = ("author", "created_at", "updated_at")
    formfield_overrides = {
        models.TextField: {
            "widget": AdminTinyMCE(mce_attrs={
                "license_key": "gpl",
                "branding": False,
                "promotion": False,
                "toolbar": (
                    "undo redo | blocks | bold italic underline forecolor backcolor | "
                    "alignleft aligncenter alignright alignjustify | "
                    "bullist numlist outdent indent | link image table | "
                    "removeformat code preview fullscreen"
                ),
                "relative_urls": False,
                "remove_script_host": True,
                "paste_data_images": False,
            }),
        },
    }

    def save_model(self, request, obj, form, change):
        # Wenn noch kein Autor zugewiesen ist, automatisch den angemeldeten User setzen
        if not obj.author:
            obj.author = request.user
        super().save_model(request, obj, form, change)
