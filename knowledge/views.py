from difflib import unified_diff

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from configuration.translations import get_translation
from events.models import Event
from .access import staff_only
from .content import sanitize_content
from .forms import SpaceForm, PageForm, VersionForm, AttachmentForm
from .models import KnowledgeSpace, KnowledgePage, KnowledgeRevision, KnowledgeAttachment
from .services import save_space, save_page, publish_page, restore_revision, upload_attachment, EditConflict


def page_queryset():
    return KnowledgePage.objects.select_related('space', 'space__event', 'published_revision', 'published_revision__author', 'updated_by')


def space_queryset():
    return KnowledgeSpace.objects.select_related('event').annotate(page_count=Count('pages'))


def scope_filter(queryset, scope, prefix=''):
    if scope == 'global':
        return queryset.filter(**{prefix + 'event__isnull': True})
    if scope.isdecimal() and len(scope) < 19:
        return queryset.filter(**{prefix + 'event_id': int(scope)})
    return queryset


def tree_rows(pages):
    children = {}
    for page in pages:
        children.setdefault(page.parent_id, []).append(page)
    rows, visited = [], set()
    def walk(parent_id, depth):
        for page in children.get(parent_id, []):
            if page.pk in visited or depth > 20:
                continue
            visited.add(page.pk)
            rows.append({'page': page, 'depth': depth})
            walk(page.pk, depth + 1)
    walk(None, 0)
    return rows


def context_for(space=None, page=None):
    context = {'spaces': space_queryset(), 'space': space, 'page': page}
    if space:
        pages = list(page_queryset().filter(space=space))
        context['tree'] = tree_rows(pages)
        by_id = {item.pk: item for item in pages}
        ancestors, parent_id, visited = [], page.parent_id if page else None, set()
        while parent_id in by_id and parent_id not in visited:
            visited.add(parent_id)
            parent = by_id[parent_id]
            ancestors.append(parent)
            parent_id = parent.parent_id
        context['ancestors'] = list(reversed(ancestors))
    return context


def form_errors(form, error):
    if hasattr(error, 'message_dict'):
        for field, errors in error.message_dict.items():
            form.add_error(field if field in form.fields else None, errors)
    else:
        form.add_error(None, error)


@staff_only
@require_safe
def home(request):
    scope = request.GET.get('scope', 'all')
    spaces = scope_filter(space_queryset(), scope)
    query = request.GET.get('q', '').strip()[:200]
    results = None
    if query:
        pages = scope_filter(page_queryset(), scope, 'space__')
        pages = pages.filter(Q(published_revision__title__icontains=query)
            | Q(published_revision__search_text__icontains=query)
            | Q(published_revision__isnull=True, title__icontains=query)
            | Q(published_revision__isnull=True, search_text__icontains=query))
        results = Paginator(pages.order_by('space__name', 'title', 'pk'), 30).get_page(request.GET.get('p'))
    return render(request, 'knowledge/home.html', {
        'spaces': spaces, 'scope': scope, 'query': query, 'results': results,
        'events': Event.objects.filter(knowledge_spaces__isnull=False).distinct().order_by('-start_date'),
        'recent_pages': scope_filter(page_queryset(), scope, 'space__').order_by('-updated_at')[:8],
    })


@staff_only
@require_http_methods(['GET', 'POST'])
def space_edit(request, pk=None):
    space = get_object_or_404(KnowledgeSpace, pk=pk) if pk else None
    form = SpaceForm(request.POST if request.method == 'POST' else None, instance=space)
    status = 200
    if request.method == 'POST':
        status = 400
        if form.is_valid():
            try:
                space = save_space(actor=request.user, space_id=space.pk if space else None,
                    **{key: form.cleaned_data[key] for key in ('name', 'description', 'event', 'expected_version')})
            except ValidationError as error:
                form_errors(form, error)
                status = 409 if isinstance(error, EditConflict) else 400
            else:
                messages.success(request, get_translation('knowledge_space_saved', 'Bereich gespeichert.'))
                return redirect(space)
    return render(request, 'knowledge/space_form.html', {'form': form, 'space': space}, status=status)


@staff_only
@require_safe
def space_detail(request, pk):
    return render(request, 'knowledge/space.html', context_for(get_object_or_404(KnowledgeSpace.objects.select_related('event'), pk=pk)))


@staff_only
@require_safe
def page_detail(request, pk):
    page = get_object_or_404(page_queryset(), pk=pk)
    draft = request.GET.get('draft') == '1' or not page.published_revision_id
    context = context_for(page.space, page)
    context.update({'reading_draft': draft, 'reading_title': page.title if draft else page.published_revision.title,
        'reading_content': sanitize_content(page.content if draft else page.published_revision.content),
        'reading_revision': page.revisions.select_related('author').first() if draft else page.published_revision,
        'attachments': page.attachments.all()})
    return render(request, 'knowledge/page.html', context)


@staff_only
@require_http_methods(['GET', 'POST'])
def page_edit(request, pk=None, space_id=None):
    page = get_object_or_404(page_queryset(), pk=pk) if pk else None
    space = page.space if page else get_object_or_404(KnowledgeSpace, pk=space_id)
    parent = None
    parent_id = request.GET.get('parent', '')
    if parent_id:
        if not parent_id.isdecimal() or len(parent_id) >= 19:
            raise Http404
        parent = get_object_or_404(KnowledgePage, pk=int(parent_id), space=space)
    form = PageForm(request.POST if request.method == 'POST' else None, space=space, page=page, parent=parent)
    status = 200
    if request.method == 'POST':
        status = 400
        valid = form.is_valid()
        if request.POST.get('action') not in ('draft', 'publish'):
            form.add_error(None, get_translation('knowledge_action_invalid', 'Bitte als Entwurf speichern oder veröffentlichen.'))
            valid = False
        if valid:
            try:
                saved = save_page(actor=request.user, space_id=space.pk, page_id=page.pk if page else None,
                    publish=request.POST['action'] == 'publish', **form.cleaned_data)
            except ValidationError as error:
                form_errors(form, error)
                status = 409 if isinstance(error, EditConflict) else 400
            else:
                messages.success(request, get_translation('knowledge_page_saved', 'Seite gespeichert.'))
                return redirect(saved.get_absolute_url() + ('?draft=1' if saved.has_draft else ''))
    context = context_for(space, page)
    context.update({'form': form, 'attachments': page.attachments.all() if page else [],
        'link_pages': page_queryset().order_by('space__name', 'title'), 'attachment_form': AttachmentForm(),
        'knowledge_js_texts': {key: get_translation('knowledge_' + key, text) for key, text in {
            'editor_wait': 'Der Editor wird noch geladen. Bitte einen Moment warten.',
            'insert_image': 'Bild einfügen', 'insert_link': 'Link einfügen',
            'save_first': 'Speichere die Seite zuerst als Entwurf.', 'file_size': 'Bitte eine Datei mit höchstens 10 MB auswählen.',
            'uploading': 'Datei wird hochgeladen …', 'upload_failed': 'Der Upload wurde nicht bestätigt. Bitte Verbindung und Anmeldung prüfen.',
            'uploaded': 'Anhang gespeichert. Er kann jetzt in den Text eingefügt werden.',
        }.items()}})
    return render(request, 'knowledge/page_form.html', context, status=status)


@staff_only
@require_POST
def page_publish(request, pk):
    page = get_object_or_404(KnowledgePage, pk=pk)
    form = VersionForm(request.POST)
    if not form.is_valid():
        return render(request, 'knowledge/action_error.html', {'page': page, 'errors': form.errors}, status=400)
    try:
        publish_page(actor=request.user, page_id=pk, **form.cleaned_data)
    except ValidationError as error:
        return render(request, 'knowledge/action_error.html', {'page': page, 'errors': error.messages}, status=409)
    messages.success(request, get_translation('knowledge_published_note', 'Veröffentlicht'))
    return redirect(page)


@staff_only
@require_safe
def page_history(request, pk):
    page = get_object_or_404(page_queryset(), pk=pk)
    context = context_for(page.space, page)
    context['revisions'] = Paginator(page.revisions.select_related('author'), 25).get_page(request.GET.get('p'))
    return render(request, 'knowledge/history.html', context)


@staff_only
@require_safe
def revision_detail(request, pk, revision_id):
    page = get_object_or_404(page_queryset(), pk=pk)
    revision = get_object_or_404(KnowledgeRevision.objects.select_related('author'), page=page, pk=revision_id)
    previous = page.revisions.filter(number__lt=revision.number).first()
    other_id = request.GET.get('compare', '')
    if other_id:
        if not other_id.isdecimal() or len(other_id) >= 19:
            raise Http404
        previous = get_object_or_404(KnowledgeRevision, page=page, pk=int(other_id))
    before = (previous.title + '\n' + previous.search_text).splitlines() if previous else []
    after = (revision.title + '\n' + revision.search_text).splitlines()
    diff = '\n'.join(unified_diff(before, after, fromfile=f'Version {previous.number if previous else 0}',
        tofile=f'Version {revision.number}', lineterm=''))
    context = context_for(page.space, page)
    context.update({'revision': revision, 'revision_content': sanitize_content(revision.content), 'diff': diff,
        'comparison_revisions': page.revisions.only('pk', 'number'), 'previous': previous})
    return render(request, 'knowledge/revision.html', context)


@staff_only
@require_POST
def revision_restore(request, pk, revision_id):
    page = get_object_or_404(KnowledgePage, pk=pk)
    get_object_or_404(KnowledgeRevision, pk=revision_id, page=page)
    form = VersionForm(request.POST)
    if not form.is_valid():
        return render(request, 'knowledge/action_error.html', {'page': page, 'errors': form.errors}, status=400)
    try:
        restore_revision(actor=request.user, page_id=pk, revision_id=revision_id, **form.cleaned_data)
    except ValidationError as error:
        return render(request, 'knowledge/action_error.html', {'page': page, 'errors': error.messages}, status=409)
    messages.success(request, get_translation('knowledge_restored', 'Die frühere Version wurde als neuer Entwurf übernommen.'))
    return redirect(page.get_absolute_url() + '?draft=1')


@staff_only
@require_POST
def attachment_upload(request, pk):
    page = get_object_or_404(KnowledgePage, pk=pk)
    form = AttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        attachment = upload_attachment(actor=request.user, page_id=pk,
            upload=form.cleaned_data['file'], metadata=form.metadata)
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'location': attachment.image_url if attachment.is_image else attachment.get_absolute_url(),
                'name': attachment.original_name, 'is_image': attachment.is_image})
        messages.success(request, get_translation('knowledge_uploaded', 'Anhang gespeichert.'))
        return redirect('knowledge:edit', pk=pk)
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'error': ' '.join(form.errors.get('file', []))}, status=400)
    return render(request, 'knowledge/action_error.html', {'page': page, 'errors': form.errors}, status=400)


@staff_only
@require_safe
def attachment_download(request, attachment_id):
    attachment = get_object_or_404(KnowledgeAttachment, pk=attachment_id)
    try:
        stream = attachment.file.open('rb')
    except FileNotFoundError:
        raise Http404
    inline = request.GET.get('inline') == '1' and attachment.is_image
    response = FileResponse(stream, as_attachment=not inline, filename=attachment.original_name,
        content_type=attachment.mime_type if inline else 'application/octet-stream')
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response
