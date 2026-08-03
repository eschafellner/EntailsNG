from django.shortcuts import render
from .models import EventInfo


def event_info_detail_view(request):
    event_info = EventInfo.objects.first()
    return render(
        request, 'info/event_info_detail.html', {'event_info': event_info}
    )
