from django.urls import path
from . import views

urlpatterns = [
    path('api/health/', views.health_check_api, name='api_health_check'),
]
