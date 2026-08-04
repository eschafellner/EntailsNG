import random
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render
from django.utils import timezone
from emails.services import send_system_email
from events.models import EventRegistration
from .forms import CustomUserCreationForm, UserProfileForm
from .models import EmailVerificationCode

User = get_user_model()


def register_view(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False  # Account ist inaktiv bis zur Double Opt-In Verifizierung!
            user.save()

            # 6-stelligen Zufallscode generieren
            code = f"{random.randint(100000, 999999):06d}"
            expires_at = timezone.now() + timedelta(minutes=15)
            EmailVerificationCode.objects.create(
                user=user, code=code, expires_at=expires_at
            )

            # System-E-Mail "email_verification" versenden
            context_data = {
                'username': user.username,
                'full_name': user.get_full_name() or user.username,
                'code': code,
                'valid_minutes': 15,
            }
            send_system_email('email_verification', user.email, context_data)

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
        # Einzelnen Code-String aus Formular oder den 6 Ziffernfeldern zusammenbauen
        code_input = request.POST.get('code', '').strip()
        if not code_input:
            digits = [request.POST.get(f'digit{i}', '').strip() for i in range(1, 7)]
            code_input = "".join(digits)

        code_obj = EmailVerificationCode.objects.filter(
            user=user, code=code_input, is_used=False
        ).first()

        if code_obj and code_obj.is_valid():
            # Account freischalten & Code entwerten
            user.is_active = True
            user.save()
            code_obj.is_used = True
            code_obj.save()

            if 'pending_verification_user_id' in request.session:
                del request.session['pending_verification_user_id']

            # Automatisch einloggen & zum Dashboard weiterleiten
            login(request, user)
            messages.success(
                request,
                request.GET.get('msg') or "E-Mail erfolgreich verifiziert! Willkommen bei EntailsNG.",
            )
            return redirect("dashboard")
        else:
            messages.error(
                request,
                "Ungültiger oder abgelaufener Verifizierungscode. Bitte überprüfe deine Eingabe.",
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
        last_code = EmailVerificationCode.objects.filter(user=user).first()
        if last_code and (timezone.now() - last_code.created_at) < timedelta(seconds=60):
            messages.warning(
                request,
                "Bitte warte kurz (ca. 1 Minute), bevor du einen neuen Code anforderst.",
            )
            return redirect("verify_email")

        # Neuen Code generieren & E-Mail senden
        code = f"{random.randint(100000, 999999):06d}"
        expires_at = timezone.now() + timedelta(minutes=15)
        EmailVerificationCode.objects.create(
            user=user, code=code, expires_at=expires_at
        )

        context_data = {
            'username': user.username,
            'full_name': user.get_full_name() or user.username,
            'code': code,
            'valid_minutes': 15,
        }
        send_system_email('email_verification', user.email, context_data)
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
