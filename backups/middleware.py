import threading

from django.db import connections
from django.http import HttpResponse, JsonResponse, Http404
from django.core.cache import caches
from django.template.loader import render_to_string
from django.utils.html import escape

from .errors import BackupError
from .locking import access_guard, maintenance_active
from .storage import read_json, root
from .texts import TEXTS


class BackupMaintenanceMiddleware:
    """Runs before sessions/authentication; holds readers through response cleanup."""
    def __init__(self, get_response):
        self.get_response = get_response
        self.local = threading.local()

    def __call__(self, request):
        # Progress contains only a capability-protected job status and never touches the DB.
        if request.path.startswith('/admin/backups/progress/'):
            return self.get_response(request)
        if maintenance_active():
            if request.path.startswith('/admin/backups/jobs/') and request.method == 'GET':
                return self.maintenance_job(request)
            return self.unavailable(request)
        guard = access_guard()
        try:
            guard.__enter__()
        except BackupError:
            return self.unavailable(request)
        try:
            # Read the generation under the shared lock: takeover cannot race this check.
            generation_path = root() / 'generation.json'
            try:
                generation = generation_path.stat().st_mtime_ns
            except FileNotFoundError:
                generation = None
            if getattr(self.local, 'generation', None) != generation:
                connections.close_all()
                for cache in caches.all():
                    cache.clear()
                self.local.generation = generation
            response = self.get_response(request)
        except BaseException:
            guard.__exit__(None, None, None)
            raise
        if response.streaming:
            response._resource_closers.append(lambda: guard.__exit__(None, None, None))
        else:
            guard.__exit__(None, None, None)
        return response

    @staticmethod
    def maintenance_job(request):
        import secrets
        from .storage import load
        parts = request.path.strip('/').split('/')
        if len(parts) != 5:
            raise Http404
        try:
            job = load('jobs', parts[3])
        except BackupError:
            raise Http404 from None
        if not secrets.compare_digest(job['token'], parts[4]):
            raise Http404
        from django.urls import reverse
        html = render_to_string('admin/backups/maintenance_job.html', {
            'texts': job.get('texts', TEXTS),
            'progress_url': reverse('backups:progress', args=[job['id'], job['token']]),
            'index_url': reverse('backups:index'),
        })  # No request/context processors: the database can currently be unavailable.
        response = HttpResponse(html)
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response

    @staticmethod
    def unavailable(request):
        if request.path == '/api/health/':
            return JsonResponse({'status': 'maintenance', 'database': 'maintenance', 'cache': 'maintenance'})
        marker = read_json(root() / 'maintenance.json', {})
        message = escape(marker.get('message', TEXTS['backup_maintenance']))
        response = HttpResponse(f'<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Entails-NG</title><body><p>{message}</p></body></html>', status=503)
        response['Retry-After'] = '15'
        response['Cache-Control'] = 'no-store'
        return response
