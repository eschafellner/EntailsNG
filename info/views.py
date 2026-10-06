from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, render
from .models import EventInfo
from .embedding import https_origin


def _render_page(request, current_page, pages_qs):
    embed_origin = None
    if current_page and current_page.is_embed:
        try:
            current_page.validate_embedding()
            candidate = https_origin(current_page.embed_url)
            # Scripts plus allow-same-origin must never be served on our own origin.
            own_origin = f'{request.scheme}://{request.get_host()}'
            if request.scheme == 'https':
                own_origin = https_origin(own_origin)
            if candidate != own_origin:
                embed_origin = candidate
        except (ValidationError, ValueError):
            pass
    response = render(request, 'info/event_info_detail.html', {
        'event_info': current_page,
        'current_page': current_page,
        'all_pages': pages_qs,
        'embed_available': bool(embed_origin),
    })
    if current_page and current_page.is_embed:
        frame_source = embed_origin or "'none'"
        response.headers['Content-Security-Policy'] = f"frame-src {frame_source}; object-src 'none'"
    return response



def _can_view_drafts(user):
    """Prüft, ob der Benutzer Entwürfe der Inhaltsseiten einsehen darf."""
    return user.is_authenticated and (
        user.is_superuser or
        user.has_perm('info.view_eventinfo') or
        user.has_perm('info.change_eventinfo')
    )


def event_info_detail_view(request):
    """
    Hauptansicht unter /info/:
    Zeigt die erste zugängliche aktive Inhaltsseite an und übergibt alle Seiten für die Tab-Leiste.
    Unangemeldete Besucher werden nicht ausgesperrt, solange mindestens eine öffentliche Seite existiert.
    """
    can_preview = _can_view_drafts(request.user)
    if can_preview:
        pages_qs = EventInfo.objects.select_related('embed_provider').order_by('order', 'id')
    else:
        pages_qs = EventInfo.objects.select_related('embed_provider').filter(is_active=True).order_by('order', 'id')

    if not request.user.is_authenticated:
        current_page = pages_qs.filter(login_required=False).first()
        if not current_page and pages_qs.filter(login_required=True).exists():
            messages.warning(
                request,
                "Diese Informationsseite ist nur für angemeldete Teilnehmer sichtbar. Bitte melde dich an."
            )
            return redirect_to_login(request.get_full_path(), login_url='login')
    else:
        current_page = pages_qs.first()

    return _render_page(request, current_page, pages_qs)


def event_info_page_view(request, slug):
    """
    Detailansicht einer spezifischen Inhaltsseite unter /info/<slug>/.
    """
    can_preview = _can_view_drafts(request.user)
    if can_preview:
        current_page = get_object_or_404(EventInfo.objects.select_related('embed_provider'), slug=slug)
        pages_qs = EventInfo.objects.all().order_by('order', 'id')
    else:
        current_page = get_object_or_404(EventInfo.objects.select_related('embed_provider'), slug=slug, is_active=True)
        pages_qs = EventInfo.objects.filter(is_active=True).order_by('order', 'id')

    if current_page.login_required and not request.user.is_authenticated:
        messages.warning(
            request,
            "Diese Informationsseite ist nur für angemeldete Teilnehmer sichtbar. Bitte melde dich an."
        )
        return redirect_to_login(request.get_full_path(), login_url='login')

    return _render_page(request, current_page, pages_qs)
