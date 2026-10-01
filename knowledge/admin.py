from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import KnowledgeSpace, KnowledgePage, KnowledgeRevision, KnowledgeAttachment


class ReadOnlyKnowledgeAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(KnowledgeSpace)
class SpaceAdmin(ReadOnlyKnowledgeAdmin):
    list_display = ['name', 'event', 'updated_at']
    search_fields = ['name', 'description']


@admin.register(KnowledgePage)
class PageAdmin(ReadOnlyKnowledgeAdmin):
    list_display = ['title', 'space', 'version', 'open_editor']
    search_fields = ['title', 'search_text']
    list_filter = ['space']

    @admin.display(description='Bearbeiten')
    def open_editor(self, obj):
        return format_html('<a href="{}">In der Wissensbasis öffnen</a>', reverse('knowledge:edit', args=[obj.pk]))


@admin.register(KnowledgeRevision)
class RevisionAdmin(ReadOnlyKnowledgeAdmin):
    list_display = ['title', 'number', 'author', 'created_at']
    search_fields = ['title', 'note']


@admin.register(KnowledgeAttachment)
class AttachmentAdmin(ReadOnlyKnowledgeAdmin):
    list_display = ['original_name', 'page', 'size', 'uploaded_by']
    exclude = ['file']
