from django.urls import path
from .views import event_info_detail_view, event_info_page_view

urlpatterns = [
    path('', event_info_detail_view, name='event_info_detail'),
    path('<slug:slug>/', event_info_page_view, name='event_info_page'),
]
