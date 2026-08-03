from django.urls import path
from . import views

urlpatterns = [
    # Hauptseite / Frontend-Ansicht für den Sitzplan (GEFEHLT)
    path('', views.seating_plan_view, name='seating_plan'),

    # Admin / Editor URLs
    path('editor/<int:plan_id>/', views.seating_editor, name='seating_editor'),
    path('editor/<int:plan_id>/save/', views.save_seating_plan, name='save_seating_plan'),
    path('admin/assign-seat/', views.admin_assign_seat, name='admin_assign_seat'),
    path('admin/toggle-block-seat/', views.admin_toggle_block_seat, name='admin_toggle_block_seat'),
    path('admin/release-seat/', views.admin_release_seat, name='admin_release_seat'),

    # Frontend / User APIs
    path('api/plan/<int:event_id>/', views.get_event_seating_api, name='api_event_seating'),
    path('api/reserve/<int:event_id>/', views.reserve_seat_api, name='api_reserve_seat'),
    path('api/release/<int:event_id>/', views.release_seat_api, name='api_release_seat'),
]
