from django.urls import path
from . import views

app_name = 'knowledge'
urlpatterns = [
    path('', views.home, name='home'),
    path('spaces/new/', views.space_edit, name='space_create'),
    path('spaces/<int:pk>/', views.space_detail, name='space'),
    path('spaces/<int:pk>/edit/', views.space_edit, name='space_edit'),
    path('spaces/<int:space_id>/pages/new/', views.page_edit, name='create'),
    path('pages/<int:pk>/', views.page_detail, name='page'),
    path('pages/<int:pk>/edit/', views.page_edit, name='edit'),
    path('pages/<int:pk>/publish/', views.page_publish, name='publish'),
    path('pages/<int:pk>/history/', views.page_history, name='history'),
    path('pages/<int:pk>/revisions/<int:revision_id>/', views.revision_detail, name='revision'),
    path('pages/<int:pk>/revisions/<int:revision_id>/restore/', views.revision_restore, name='restore'),
    path('pages/<int:pk>/attachments/', views.attachment_upload, name='upload'),
    path('attachments/<uuid:attachment_id>/', views.attachment_download, name='attachment'),
]
