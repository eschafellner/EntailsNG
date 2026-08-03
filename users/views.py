from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render
from events.models import EventRegistration
from .forms import CustomUserCreationForm, UserProfileForm


def register_view(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # Nach Registrierung sofort einloggen
            return redirect("dashboard")
    else:
        form = CustomUserCreationForm()

    return render(request, "auth/register.html", {"form": form})


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
