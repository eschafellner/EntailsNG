# config/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    # 1. Startseite / Haupt-Dashboard
    path('', include('events.urls')),

    # 2. Django Admin
    path('admin/', admin.site.urls),

    # 3. Authentifizierung
    path('', include('users.urls')),
    path(
        'login/',
        auth_views.LoginView.as_view(template_name='auth/login.html'),
        name='login',
    ),
    path(
        'logout/',
        auth_views.LogoutView.as_view(next_page='login'),
        name='logout',
    ),

    # 3b. Passwort zurücksetzen
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='auth/password_reset.html'
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='auth/password_reset_done.html'
        ),
        name='password_reset_done',
    ),
    path(
        'password-reset-confirm/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='auth/password_reset_confirm.html'
        ),
        name='password_reset_confirm',
    ),
    path(
        'password-reset-complete/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='auth/password_reset_complete.html'
        ),
        name='password_reset_complete',
    ),

    # 4. Modul-Routen
    path('', include('configuration.urls')),
    path('tinymce/', include('tinymce.urls')),
    path('info/', include('info.urls')),
    path('news/', include('news.urls')),
    path('seating/', include('seating.urls')),
    path('clans/', include('clans.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

