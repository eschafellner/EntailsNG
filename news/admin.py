from django.contrib import admin
from django.db import models
from django.urls import reverse
from django.utils.html import format_html
from tinymce.widgets import AdminTinyMCE
from .models import NewsArticle


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "publish_at", "publication_status", "is_published", "is_pinned")
    list_editable = ("is_published", "is_pinned")
    list_filter = ("is_published", "is_pinned", "publish_at")
    search_fields = ("title", "content")
    readonly_fields = ("author", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("title", "content")}),
        ("Titelbild", {"fields": ("cover_image", "cover_image_alt", "image_fit")}),
        ("Veröffentlichung", {"fields": ("is_published", "publish_at", "is_pinned")}),
        ("Beitragsinformationen", {"fields": ("author", "created_at", "updated_at")}),
    )
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

    @admin.display(description="Status")
    def publication_status(self, obj):
        if not obj.is_published:
            return "Entwurf"
        if obj.is_scheduled:
            return format_html('Geplant · <a href="{}">Vorschau</a>', reverse("news_detail", args=[obj.pk]))
        return "Veröffentlicht"

    def save_model(self, request, obj, form, change):
        # Wenn noch kein Autor zugewiesen ist, automatisch den angemeldeten User setzen
        if not obj.author:
            obj.author = request.user
        super().save_model(request, obj, form, change)
