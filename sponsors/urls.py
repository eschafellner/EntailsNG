from django.urls import path
from . import views

urlpatterns = [
    path('', views.sponsor_list_view, name='sponsor_list'),
]
