from django.shortcuts import render
from .services import get_active_sponsors


def sponsor_list_view(request):
    """
    Öffentliche Übersichtsseite aller aktuell aktiven Sponsoren.
    Inaktive Sponsoren werden herausgefiltert.
    """
    sponsors = get_active_sponsors()
    context = {
        'sponsors': sponsors,
    }
    return render(request, 'sponsors/sponsor_list.html', context)
