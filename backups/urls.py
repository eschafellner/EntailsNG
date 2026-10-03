from django.contrib import admin
from django.urls import path
from . import views

app_name = 'backups'
urlpatterns = [
    path('', admin.site.admin_view(views.index), name='index'),
    path('download/<str:value>/', admin.site.admin_view(views.download), name='download'),
    path('restore/<str:value>/', admin.site.admin_view(views.restore), name='restore'),
    path('delete/<str:value>/', admin.site.admin_view(views.delete), name='delete'),
    path('resume-mail/', admin.site.admin_view(views.resume_mail), name='resume_mail'),
    path('jobs/<str:value>/<str:token>/', admin.site.admin_view(views.job), name='job'),
    path('progress/<str:value>/<str:token>/', views.progress, name='progress'),
]
