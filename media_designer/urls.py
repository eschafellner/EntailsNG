from django.urls import path

from media_designer import views


urlpatterns = [
    path('', views.template_list, name='media_template_list'),
    path('create/', views.template_create, name='media_template_create'),
    path('<int:pk>/edit/', views.template_edit, name='media_template_edit'),
    path('<int:pk>/export/', views.template_export, name='media_template_export'),
]
