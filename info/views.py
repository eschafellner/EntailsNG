from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from .models import EventInfo


def event_info_detail_view(request):
    """
    Hauptansicht unter /info/:
    Zeigt die erste aktive Inhaltsseite an und übergibt alle Seiten für die Tab-Leiste.
    """
    if request.user.is_staff:
        pages_qs = EventInfo.objects.all().order_by('order', 'id')
    else:
        pages_qs = EventInfo.objects.filter(is_active=True).order_by('order', 'id')

    current_page = pages_qs.first()

    if current_page and current_page.login_required and not request.user.is_authenticated:
        messages.warning(
            request,
            "Diese Informationsseite ist nur für angemeldete Teilnehmer sichtbar. Bitte melde dich an."
        )
        return redirect_to_login(request.get_full_path(), login_url='login')

    return render(
        request,
        'info/event_info_detail.html',
        {
            'event_info': current_page,
            'current_page': current_page,
            'all_pages': pages_qs,
        }
    )


def event_info_page_view(request, slug):
    """
    Detailansicht einer spezifischen Inhaltsseite unter /info/<slug>/.
    """
    if request.user.is_staff:
        current_page = get_object_or_404(EventInfo, slug=slug)
        pages_qs = EventInfo.objects.all().order_by('order', 'id')
    else:
        current_page = get_object_or_404(EventInfo, slug=slug, is_active=True)
        pages_qs = EventInfo.objects.filter(is_active=True).order_by('order', 'id')

    if current_page.login_required and not request.user.is_authenticated:
        messages.warning(
            request,
            "Diese Informationsseite ist nur für angemeldete Teilnehmer sichtbar. Bitte melde dich an."
        )
        return redirect_to_login(request.get_full_path(), login_url='login')

    return render(
        request,
        'info/event_info_detail.html',
        {
            'event_info': current_page,
            'current_page': current_page,
            'all_pages': pages_qs,
        }
    )
