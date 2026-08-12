from django.urls import path
from . import views

urlpatterns = [
    path('api/health/', views.health_check_api, name='api_health_check'),
    path('impressum/', views.impressum_view, name='impressum'),
    path('datenschutz/', views.datenschutz_view, name='datenschutz'),
]

