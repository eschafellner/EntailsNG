import secrets

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from configuration.translations import get_translation
from . import services, storage
from .errors import BackupError
from .forms import CreateForm, RestoreForm, UploadForm
from .texts import TEXTS


def authorize(request):
    if not request.user.is_active or not request.user.is_staff or not request.user.is_superuser:
        raise PermissionDenied


def context(request, **values):
    authorize(request)
    return {**admin.site.each_context(request), 'title': get_translation('backup_title'), **values}


def error_message(request, exc):
    messages.error(request, get_translation(exc.key))


def show_job(job):
    return redirect('backups:job', value=job['id'], token=job['token'])


@csrf_protect
def index(request):
    authorize(request)
    create = CreateForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'create' else None)
    upload = UploadForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'upload' else None,
                        request.FILES or None)
    ready = False
    issue = None
    try:
        storage.encryption_key()
        storage.initialize()
        ready = services.worker_available()
        if not ready:
            issue = get_translation('backup_worker_missing')
        if request.method == 'POST':
            if request.POST.get('action') == 'create' and create.is_valid():
                return show_job(services.enqueue('create', actor=request.user.username,
                                                 description=create.cleaned_data['description'], require_worker=True))
            if request.POST.get('action') == 'upload' and upload.is_valid():
                return show_job(services.upload_backup(upload.cleaned_data['file'], actor=request.user.username,
                                                       require_worker=True))
    except BackupError as exc:
        issue = get_translation(exc.key)
    records = storage.list_records()
    for record in records:
        record['status_label'] = get_translation('backup_' + record['state'])
    jobs = storage.list_records('jobs')[:10]
    for job in jobs:
        job['status_label'] = get_translation('backup_' + job['state'])
    return TemplateResponse(request, 'admin/backups/index.html', context(
        request, records=records, jobs=jobs, create_form=create, upload_form=upload,
        ready=ready, issue=issue, mail_paused=(storage.root() / 'mail-paused.json').exists()))


def download(request, value):
    authorize(request)
    try:
        record = storage.load('records', value)
        if record['state'] not in ('completed', 'prepared'):
            raise BackupError('backup_err_not_found')
        response = FileResponse(storage.artifact_path(value).open('rb'), as_attachment=True,
                                filename='entailsng_' + record['created_at'][:19].replace(':', '-') + '.entailsbackup',
                                content_type='application/octet-stream')
        response['Cache-Control'] = 'no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
    except (BackupError, FileNotFoundError):
        raise Http404 from None


@csrf_protect
def restore(request, value):
    authorize(request)
    try:
        record = storage.load('records', value)
        if record['state'] not in ('prepared', 'completed'):
            raise BackupError('backup_err_not_found')
        if record['state'] != 'prepared':
            if request.method == 'POST':
                return show_job(services.enqueue('prepare', actor=request.user.username, record_id=value, require_worker=True))
            return TemplateResponse(request, 'admin/backups/restore.html', context(request, record=record, prepare=True))
        form = RestoreForm(request.POST or None, user=request.user)
        if request.method == 'POST' and form.is_valid():
            return show_job(services.enqueue('restore', actor=request.user.username, record_id=value, require_worker=True))
        return TemplateResponse(request, 'admin/backups/restore.html', context(request, record=record, form=form))
    except BackupError as exc:
        error_message(request, exc)
        return redirect('backups:index')


@require_POST
@csrf_protect
def delete(request, value):
    authorize(request)
    try:
        services.delete_backup(value)
        messages.success(request, get_translation('backup_deleted'))
    except BackupError as exc:
        error_message(request, exc)
    return redirect('backups:index')


@require_POST
@csrf_protect
def resume_mail(request):
    authorize(request)
    services.resume_mail()
    messages.success(request, get_translation('backup_mail_resumed'))
    return redirect('backups:index')


def job(request, value, token):
    authorize(request)
    try:
        data = storage.load('jobs', value)
        if not secrets.compare_digest(data['token'], token):
            raise Http404
    except BackupError:
        raise Http404 from None
    return TemplateResponse(request, 'admin/backups/job.html', context(
        request, job=data, progress_url=reverse('backups:progress', args=[value, token])))


def progress(request, value, token):
    """Capability URL, deliberately usable during database replacement, with no identifying details."""
    try:
        data = storage.load('jobs', value)
        if not secrets.compare_digest(data['token'], token):
            raise Http404
    except BackupError:
        raise Http404 from None
    # Static translation defaults also work when the application DB is unavailable.
    texts = data.get('texts', TEXTS)
    response = JsonResponse({'state': data['state'], 'stage': texts.get('backup_stage_' + data['stage'], ''),
                             'label': texts.get('backup_' + data['state'], ''),
                             'error': texts.get(data.get('error'), ''),
                             'restore_url': (reverse('backups:restore', args=[data['result_id']])
                                             if data['kind'] == 'prepare' and data.get('result_id') else None)})
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response
