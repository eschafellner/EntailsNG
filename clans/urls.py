from django.urls import path
from . import views

urlpatterns = [
    path('', views.clan_list_view, name='clan_list'),
    path('create/', views.clan_create_view, name='clan_create'),
    path('<slug:slug>/', views.clan_detail_view, name='clan_detail'),
    path('<slug:slug>/edit/', views.clan_edit_view, name='clan_edit'),
    path('<slug:slug>/join-password/', views.clan_join_password_view, name='clan_join_password'),
    path('<slug:slug>/request-join/', views.clan_request_join_view, name='clan_request_join'),
    path('<slug:slug>/manage-request/<int:membership_id>/', views.clan_manage_request_view, name='clan_manage_request'),
    path('<slug:slug>/manage-member/<int:membership_id>/', views.clan_manage_member_view, name='clan_manage_member'),
    path('<slug:slug>/leave/', views.clan_leave_view, name='clan_leave'),
]
