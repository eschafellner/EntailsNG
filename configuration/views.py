import logging
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.utils import timezone

logger = logging.getLogger(__name__)


def health_check_api(request):
    """Echtzeit Status-Endpoint für Datenbank und Cache (Uptime-Monitoring)."""
    db_status = "ok"
    cache_status = "ok"
    is_healthy = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as e:
        logger.error(f"Healthcheck Database Failure: {e}", exc_info=True)
        db_status = "unavailable"
        is_healthy = False

    try:
        cache.set("health_check_ping", "pong", 5)
        if cache.get("health_check_ping") != "pong":
            cache_status = "unavailable"
            is_healthy = False
    except Exception as e:
        logger.error(f"Healthcheck Cache Failure: {e}", exc_info=True)
        cache_status = "unavailable"
        is_healthy = False

    data = {
        "status": "healthy" if is_healthy else "unhealthy",
        "database": db_status,
        "cache": cache_status,
        "timestamp": timezone.now().isoformat(),
    }
    return JsonResponse(data, status=200 if is_healthy else 503)



from django.shortcuts import render
from .models import SiteCustomization


def impressum_view(request):
    custom = SiteCustomization.load()
    return render(
        request,
        'legal.html',
        {
            'title': 'Impressum',
            'content': custom.impressum_content,
        },
    )


def datenschutz_view(request):
    custom = SiteCustomization.load()
    return render(
        request,
        'legal.html',
        {
            'title': 'Datenschutzerklärung',
            'content': custom.datenschutz_content,
        },
    )

