from django.urls import path
from .views import event_info_detail_view

urlpatterns = [
    path('', event_info_detail_view, name='event_info_detail'),
]
