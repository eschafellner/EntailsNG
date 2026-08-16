import secrets
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth import get_user_model, login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from emails.services import send_system_email
from events.models import EventRegistration
from .forms import CustomUserCreationForm, UserProfileForm
from .models import EmailVerificationCode

from django.contrib.auth.views import PasswordResetConfirmView

User = get_user_model()


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'auth/password_reset_confirm.html'

    def form_valid(self, form):
        user = form.save()
        user.reset_lockout()
        return super().form_valid(form)


def register_view(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=False)
                user.is_active = False  # Account ist inaktiv bis zur Double Opt-In Verifizierung!
                user.save()

                # Kryptografisch sicheren 6-stelligen Zufallscode generieren
                code_obj = EmailVerificationCode.generate_for_user(user, valid_minutes=15)

                context_data = {
                    'username': user.username,
                    'full_name': user.get_full_name() or user.username,
                    'code': code_obj.code,
                    'valid_minutes': 15,
                }
                # E-Mail-Versand erst NACH erfolgreichem DB-Commit (kein SMTP-Blocker in Transaktion, keine Phantom-Mails bei Rollback)
                transaction.on_commit(
                    lambda: send_system_email('email_verification', user.email, context_data)
                )

            # Session merken & zur Verifizierungsmaske umleiten
            request.session['pending_verification_user_id'] = user.id
            return redirect("verify_email")
    else:
        form = CustomUserCreationForm()

    return render(request, "auth/register.html", {"form": form})


def verify_email_view(request):
    user_id = request.session.get('pending_verification_user_id')
    if not user_id:
        return redirect("login")

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return redirect("login")

    if user.is_active:
        if 'pending_verification_user_id' in request.session:
            del request.session['pending_verification_user_id']
        return redirect("dashboard")

    if request.method == "POST":
        # IP-basiertes Rate-Limiting gegen Brute-Force auf Verifizierungscodes
        client_ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
        rate_key = f"rate_limit_verify_email_{client_ip}"
        attempts = cache.get(rate_key, 0)
        if attempts >= 10:
            messages.error(
                request,
                "Zu viele Verifizierungsversuche von deiner IP-Adresse. Bitte warte eine Minute.",
            )
            return render(request, "auth/verify_email.html", {'user_email': user.email, 'user_id': user.id})
        cache.set(rate_key, attempts + 1, 60)

        # Einzelnen Code-String aus Formular oder den 6 Ziffernfeldern zusammenbauen
        code_input = request.POST.get('code', '').strip()
        if not code_input:
            digits = [request.POST.get(f'digit{i}', '').strip() for i in range(1, 7)]
            code_input = "".join(digits)

        # Aktuellsten aktiven Code des Benutzers abrufen
        code_obj = EmailVerificationCode.objects.filter(
            user=user, is_used=False
        ).order_by('-created_at').first()

        if not code_obj or not code_obj.is_valid():
            messages.error(
                request,
                "Der Verifizierungscode ist ungültig oder abgelaufen. Bitte fordere einen neuen Code an.",
            )
        elif secrets.compare_digest(code_obj.code, code_input):
            # Account freischalten & Code entwerten
            with transaction.atomic():
                user.is_active = True
                user.save(update_fields=['is_active'])
                code_obj.is_used = True
                code_obj.save(update_fields=['is_used'])

            if 'pending_verification_user_id' in request.session:
                del request.session['pending_verification_user_id']

            # Automatisch einloggen & zum Dashboard weiterleiten
            login(request, user, backend='users.auth_backends.EmailOrUsernameBackend')
            messages.success(
                request,
                "E-Mail erfolgreich verifiziert! Willkommen bei EntailsNG.",
            )
            return redirect("dashboard")
        else:
            code_obj.register_failed_attempt()
            remaining = max(0, 5 - code_obj.failed_attempts)
            if remaining > 0:
                messages.error(
                    request,
                    f"Ungültiger Verifizierungscode. Noch {remaining} Versuch(e) verbleibend.",
                )
            else:
                messages.error(
                    request,
                    "Zu viele Fehlversuche. Dieser Bestätigungscode wurde gesperrt. Bitte fordere einen neuen Code an.",
                )

    context = {
        'user_email': user.email,
        'user_id': user.id,
    }
    return render(request, "auth/verify_email.html", context)


def resend_verification_code_view(request):
    if request.method == "POST":
        user_id = request.session.get('pending_verification_user_id')
        if not user_id:
            return redirect("login")

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return redirect("login")

        # Cooldown Schutz (maximal 1 Code alle 60 Sekunden)
        last_code = EmailVerificationCode.objects.filter(user=user).order_by('-created_at').first()
        if last_code and (timezone.now() - last_code.created_at) < timedelta(seconds=60):
            messages.warning(
                request,
                "Bitte warte kurz (ca. 1 Minute), bevor du einen neuen Code anforderst.",
            )
            return redirect("verify_email")

        with transaction.atomic():
            # Neuen Code generieren & E-Mail erst nach Commit senden
            code_obj = EmailVerificationCode.generate_for_user(user, valid_minutes=15)

            context_data = {
                'username': user.username,
                'full_name': user.get_full_name() or user.username,
                'code': code_obj.code,
                'valid_minutes': 15,
            }
            transaction.on_commit(
                lambda: send_system_email('email_verification', user.email, context_data)
            )

        messages.info(request, f"Ein neuer Bestätigungscode wurde an {user.email} gesendet.")

    return redirect("verify_email")



@login_required
def profile_view(request):
    user = request.user
    registrations = (
        EventRegistration.objects.filter(user=user)
        .select_related('event', 'ticket_type')
        .prefetch_related('seats')
        .order_by('-created_at')
    )

    profile_form = UserProfileForm(instance=user)
    password_form = PasswordChangeForm(user=user)

    if request.method == "POST":
        if "update_profile" in request.POST:
            profile_form = UserProfileForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(
                    request, "Deine Profil-Stammdaten wurden aktualisiert."
                )
                return redirect("profile")
            else:
                messages.error(
                    request, "Bitte korrigiere die Fehler im Formular."
                )

        elif "change_password" in request.POST:
            password_form = PasswordChangeForm(user=user, data=request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)  # Verhindert Ausloggen
                messages.success(
                    request, "Dein Passwort wurde erfolgreich geändert."
                )
                return redirect("profile")
            else:
                messages.error(
                    request,
                    "Fehler beim Ändern des Passworts. Bitte überprüfe deine"
                    " Eingaben.",
                )

    context = {
        'profile_form': profile_form,
        'password_form': password_form,
        'registrations': registrations,
    }
    return render(request, "users/profile.html", context)
