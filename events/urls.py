from django.urls import path
from . import views

urlpatterns = [
    # Die Startseite/Hauptansicht (Dashboard)
    path('', views.dashboard_view, name='dashboard'),

    # Gästeliste
    path('guests/', views.guest_list_view, name='guest_list'),
    path('guests/<slug:slug>/', views.guest_list_view, name='guest_list_slug'),

    # Helfer Scanner & Einlass-Tool (Nur Staff)
    path('checkin/scanner/', views.checkin_scanner_view, name='checkin_scanner'),

    # API / Interaktionen
    path('api/event/<int:event_id>/update-payment-check/', views.update_payment_check_api, name='api_update_payment_check'),
    path('events/api/event/<int:event_id>/update-payment-check/', views.update_payment_check_api),
    path('api/check-in/toggle/', views.toggle_check_in_api, name='api_toggle_check_in'),
    path('api/check-in/scan/', views.scan_qr_api, name='api_scan_qr'),
    path('register/<int:event_id>/', views.register_for_event, name='register_for_event'),
    path('registrations/<int:registration_id>/payment-qr/', views.registration_payment_qr_view, name='registration_payment_qr'),
    path('registrations/<int:registration_id>/checkin-qr/', views.registration_checkin_qr_view, name='registration_checkin_qr'),
    path('checkin/<int:registration_id>/<uuid:token>/', views.process_checkin, name='process_checkin'),
]

