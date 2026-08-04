from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('verify-email/', views.verify_email_view, name='verify_email'),
    path('resend-code/', views.resend_verification_code_view, name='resend_verification_code'),
    path('profile/', views.profile_view, name='profile'),
]
