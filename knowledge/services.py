from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from configuration.translations import get_translation
from .access import require_staff
from .content import sanitize_content, content_text
from .models import KnowledgeSpace, KnowledgePage, KnowledgeRevision, KnowledgeAttachment


class EditConflict(ValidationError):
    pass


def locked_actor(actor):
    actor = get_user_model().objects.select_for_update(no_key=True).get(pk=actor.pk)
    require_staff(actor)
    return actor


def check_version(actual, expected):
    if actual != expected:
        raise EditConflict(get_translation('knowledge_conflict', 'Eine andere Person hat inzwischen Änderungen gespeichert. Deine Eingabe bleibt erhalten. Öffne den aktuellen Stand in einem zweiten Tab und übernimm deine Änderungen dort.'))


@transaction.atomic
def save_space(*, actor, name, description='', event=None, space_id=None, expected_version=0):
    locked_actor(actor)
    if space_id:
        space = KnowledgeSpace.objects.select_for_update().get(pk=space_id)
        check_version(space.version, expected_version)
        space.version += 1
    else:
        space = KnowledgeSpace()
    space.name, space.description, space.event = name, description, event
    space.full_clean()
    space.save()
    return space


def validate_parent(space, page, parent):
    if not parent:
        return
    parent = KnowledgePage.objects.get(pk=parent.pk)
    if parent.space_id != space.pk:
        raise ValidationError({'parent': get_translation('knowledge_parent_space', 'Die übergeordnete Seite muss im selben Bereich liegen.')})
    pages = dict(space.pages.values_list('pk', 'parent_id'))
    visited = {page.pk} if page.pk else set()
    ancestor = parent.pk
    depth = 0
    while ancestor:
        if ancestor in visited:
            raise ValidationError({'parent': get_translation('knowledge_parent_cycle', 'Eine Seite kann nicht unter sich selbst oder ihre Unterseiten verschoben werden.')})
        visited.add(ancestor)
        depth += 1
        if depth >= 20:
            raise ValidationError({'parent': get_translation('knowledge_parent_depth', 'Die Seitenstruktur darf höchstens 20 Ebenen tief sein.')})
        ancestor = pages.get(ancestor)
    # Moving a subtree must also keep its deepest descendant within the limit.
    level, descendants = 0, {page.pk} if page.pk else set()
    while descendants:
        descendants = {pk for pk, parent_id in pages.items() if parent_id in descendants}
        level += 1
        if descendants and depth + level >= 20:
            raise ValidationError({'parent': get_translation('knowledge_parent_depth')})


def write_revision(page, actor, *, title, content, parent, order, note, publish):
    validate_parent(page.space, page, parent)
    page.title, page.content = title, sanitize_content(content)
    page.search_text = content_text(page.content)
    page.parent, page.order, page.updated_by = parent, order, actor
    page.version += 1
    page.full_clean(exclude=['published_revision'])
    page.save()
    revision = KnowledgeRevision(page=page, number=page.version, title=page.title,
        content=page.content, search_text=page.search_text, author=actor, note=note)
    revision.full_clean()
    revision.save()
    if publish:
        page.published_revision = revision
        page.save(update_fields=['published_revision'])
    return page


@transaction.atomic
def save_page(*, actor, space_id, title, content='', parent=None, order=0, note='', publish=False,
              page_id=None, expected_version=0):
    actor = locked_actor(actor)
    space = KnowledgeSpace.objects.select_for_update().get(pk=space_id)
    page = KnowledgePage.objects.select_for_update().get(pk=page_id, space=space) if page_id else KnowledgePage(space=space, created_by=actor)
    check_version(page.version, expected_version)
    return write_revision(page, actor, title=title, content=content, parent=parent, order=order, note=note, publish=publish)


@transaction.atomic
def publish_page(*, actor, page_id, expected_version):
    actor = locked_actor(actor)
    space_id = KnowledgePage.objects.values_list('space_id', flat=True).get(pk=page_id)
    KnowledgeSpace.objects.select_for_update().get(pk=space_id)
    page = KnowledgePage.objects.select_for_update().get(pk=page_id)
    check_version(page.version, expected_version)
    return write_revision(page, actor, title=page.title, content=page.content, parent=page.parent,
        order=page.order, note=get_translation('knowledge_published_note', 'Veröffentlicht'), publish=True)


@transaction.atomic
def restore_revision(*, actor, page_id, revision_id, expected_version):
    actor = locked_actor(actor)
    space_id = KnowledgePage.objects.values_list('space_id', flat=True).get(pk=page_id)
    KnowledgeSpace.objects.select_for_update().get(pk=space_id)
    page = KnowledgePage.objects.select_for_update().get(pk=page_id)
    check_version(page.version, expected_version)
    revision = KnowledgeRevision.objects.get(pk=revision_id, page=page)
    return write_revision(page, actor, title=revision.title, content=revision.content, parent=page.parent,
        order=page.order, note=get_translation('knowledge_restored_note', 'Version {number} wiederhergestellt', number=revision.number), publish=False)


@transaction.atomic
def upload_attachment(*, actor, page_id, upload, metadata):
    actor = locked_actor(actor)
    page = KnowledgePage.objects.get(pk=page_id)
    attachment = KnowledgeAttachment(page=page, uploaded_by=actor, **metadata)
    try:
        attachment.file.save(metadata['original_name'], upload, save=False)
        attachment.full_clean()
        attachment.save()
    except Exception:
        if attachment.file.name:
            attachment.file.storage.delete(attachment.file.name)
        raise
    return attachment
