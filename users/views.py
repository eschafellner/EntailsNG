import logging
import secrets
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth import get_user_model, login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import PasswordResetConfirmView
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from emails.models import GeneralEmailSettings
from events.models import EventRegistration
from configuration.translations import get_translation
from .auth_backends import get_client_ip
from .exceptions import VerificationCodeCooldownError, VerificationCodeLimitError
from .forms import CustomUserCreationForm, UserProfileForm
from .models import EmailVerificationCode
from .services import UserService

logger = logging.getLogger(__name__)
User = get_user_model()


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'auth/password_reset_confirm.html'

    def form_valid(self, form):
        # form.save() nur einmal aufrufen (kein zweiter Aufruf via super().form_valid)
        user = form.save()
        user.reset_lockout()
        return HttpResponseRedirect(self.get_success_url())


def register_view(request):
    email_settings = GeneralEmailSettings.load()
    if not email_settings.is_operational:
        return render(
            request,
            "auth/register.html",
            {
                "registration_disabled": True,
                "disabled_reason": "Die Registrierung ist derzeit vorübergehend nicht möglich, da der E-Mail-Versand nicht eingerichtet oder deaktiviert ist. Bitte wende dich an das Orga-Team.",
            },
        )

    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user, code_obj = UserService.register_user(form)
            # Session merken & zur Verifizierungsmaske umleiten
            request.session['pending_verification_user_id'] = user.id
            return redirect("verify_email")
    else:
        form = CustomUserCreationForm()

    return render(request, "auth/register.html", {"form": form})


def verify_email_view(request):
    user_id = request.session.get('pending_verification_user_id')
    if not user_id:
        messages.info(
            request,
            "Bitte melde dich an oder fordere einen Bestätigungscode an."
        )
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
        client_ip = get_client_ip(request)
        rate_key = f"rate_limit_verify_email_{client_ip}"
        attempts = 1
        try:
            if cache.add(rate_key, 1, 60):
                attempts = 1
            else:
                attempts = cache.incr(rate_key)
        except (ValueError, TypeError):
            try:
                cache.set(rate_key, 1, 60)
            except Exception:
                pass
            attempts = 1
        except Exception as e:
            logger.warning("E-Mail-Verify Rate-Limiting Cache-Fehler für IP %s: %s. Fail-Open aktiv.", client_ip, e)
            attempts = 1

        if attempts > 10:
            messages.error(
                request,
                "Zu viele Verifizierungsversuche von deiner IP-Adresse. Bitte warte eine Minute.",
            )
            return render(request, "auth/verify_email.html", {'user_email': user.email, 'user_id': user.id})

        # Einzelnen Code-String aus Formular oder den 6 Ziffernfeldern zusammenbauen
        code_input = request.POST.get('code', '').strip()
        if not code_input:
            digits = [request.POST.get(f'digit{i}', '').strip() for i in range(1, 7)]
            code_input = "".join(digits)

        status, code_obj, remaining = UserService.verify_registration_code(
            user=user,
            code_input=code_input,
        )

        if status == 'success':
            if 'pending_verification_user_id' in request.session:
                del request.session['pending_verification_user_id']

            # Automatisch einloggen & zum Dashboard weiterleiten
            login(request, user, backend='users.auth_backends.EmailOrUsernameBackend')
            messages.success(
                request,
                get_translation(
                    'register_verify_success',
                    'E-Mail erfolgreich verifiziert! Willkommen bei EntailsNG.'
                ),
            )
            return redirect("dashboard")
        elif status == 'wrong_code':
            messages.error(
                request,
                get_translation(
                    'msg_verification_code_wrong',
                    'Ungültiger Bestätigungscode. Noch {remaining} Versuch(e) verbleibend.',
                    remaining=remaining,
                ),
            )
        elif status == 'locked':
            messages.error(
                request,
                get_translation(
                    'verify_code_locked',
                    'Dieser Code wurde wegen zu vieler Fehlversuche gesperrt. Bitte fordere einen neuen Code an.',
                ),
            )
        else:
            messages.error(
                request,
                "Der Verifizierungscode ist ungültig oder abgelaufen. Bitte fordere einen neuen Code an.",
            )

    context = {
        'user_email': user.email,
        'user_id': user.id,
    }
    return render(request, "auth/verify_email.html", context)


def resend_verification_code_view(request):
    if request.method != "POST":
        return redirect("verify_email")

    user_id = request.session.get('pending_verification_user_id')
    if not user_id:
        return redirect("login")

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return redirect("login")

    try:
        UserService.resend_registration_code(user)
        messages.success(request, "Ein neuer Bestätigungscode wurde an deine E-Mail-Adresse gesendet.")
    except VerificationCodeCooldownError as e:
        messages.warning(request, str(e))
    except VerificationCodeLimitError as e:
        messages.error(request, str(e))

    return redirect("verify_email")


def request_activation_code_view(request):
    """
    Erlaubt es unbestätigten Nutzern, die ihre Session verloren haben,
    einen neuen Bestätigungscode per E-Mail anzufordern.
    Schutz gegen Enumeration: Gibt immer dieselbe neutrale Erfolgsmeldung aus.
    """
    if request.method == "POST":
        client_ip = get_client_ip(request)
        rate_key = f"rate_limit_request_activation_{client_ip}"
        count = cache.get(rate_key, 0)
        if count >= 5:
            messages.error(
                request,
                "Zu viele Anfragen von deiner IP-Adresse. Bitte warte einige Minuten."
            )
            return render(request, "auth/request_activation.html")

        try:
            cache.set(rate_key, count + 1, 600)
        except Exception:
            pass

        email_input = request.POST.get("email", "").strip().lower()
        if email_input:
            user = User.objects.filter(email__iexact=email_input, is_active=False).first()
            if not user:
                user = User.objects.filter(username__iexact=email_input, is_active=False).first()

            if user:
                has_code = user.verification_codes.filter(new_email__isnull=True).exists()
                if has_code:
                    try:
                        UserService.resend_registration_code(user)
                        request.session['pending_verification_user_id'] = user.id
                        messages.success(
                            request,
                            "Ein neuer Bestätigungscode wurde gesendet. Bitte prüfe dein Postfach."
                        )
                        return redirect("verify_email")
                    except VerificationCodeCooldownError as e:
                        request.session['pending_verification_user_id'] = user.id
                        messages.warning(request, str(e))
                        return redirect("verify_email")
                    except VerificationCodeLimitError as e:
                        messages.error(request, str(e))
                        return redirect("login")

        messages.success(
            request,
            "Falls für diese Angabe ein unbestätigtes Benutzerkonto existiert, wurde ein neuer Code versendet."
        )
        return redirect("login")

    return render(request, "auth/request_activation.html")


@login_required
def profile_view(request):
    user = request.user
    registrations = (
        EventRegistration.objects.filter(user=user)
        .select_related('event', 'ticket_type')
        .prefetch_related('seats')
        .order_by('-created_at')
    )

    from clans.models import ClanMembership
    clan_membership = ClanMembership.get_user_active_membership(user)

    profile_form = UserProfileForm(instance=user)
    password_form = PasswordChangeForm(user=user)

    pending_email_info = UserService.get_pending_email_change(user)
    pending_email_code = pending_email_info['code_obj'] if pending_email_info else None

    if request.method == "POST":
        if "update_profile" in request.POST:
            profile_form = UserProfileForm(request.POST, instance=user)
            if profile_form.is_valid():
                user = profile_form.save()
                if profile_form.pending_new_email:
                    email_settings = GeneralEmailSettings.load()
                    if not email_settings.is_operational:
                        messages.error(
                            request,
                            get_translation(
                                'msg_email_change_unavailable',
                                'E-Mail-Änderung ist derzeit vorübergehend nicht möglich, da der E-Mail-Versand nicht eingerichtet oder deaktiviert ist.',
                            ),
                        )
                    else:
                        target_email = profile_form.pending_new_email
                        try:
                            code_obj, status = UserService.request_email_change(user, target_email)
                            if status == 'email_taken':
                                messages.error(
                                    request,
                                    get_translation(
                                        'msg_email_taken',
                                        'Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet.',
                                    ),
                                )
                            else:
                                messages.info(
                                    request,
                                    get_translation(
                                        'msg_email_change_initiated',
                                        'Ein Bestätigungscode wurde an "{new_email}" gesendet. Bitte gib den Code ein, um die Änderung abzuschließen.',
                                        new_email=target_email,
                                    ),
                                )
                        except VerificationCodeCooldownError as e:
                            messages.warning(request, str(e))
                        except VerificationCodeLimitError as e:
                            messages.error(request, str(e))
                else:
                    messages.success(
                        request,
                        get_translation(
                            'msg_profile_saved',
                            'Deine Profil-Stammdaten wurden aktualisiert.',
                        ),
                    )
                return redirect("profile")
            else:
                messages.error(
                    request,
                    get_translation(
                        'msg_profile_form_errors',
                        'Bitte korrigiere die Fehler im Formular.',
                    ),
                )

        elif "confirm_email_change" in request.POST:
            code_input = request.POST.get('verification_code', '').strip()
            if not code_input:
                digits = [request.POST.get(f'digit{i}', '').strip() for i in range(1, 7)]
                code_input = "".join(digits)

            status, code_obj, remaining = UserService.confirm_email_change(
                user=user,
                code_input=code_input,
            )

            if status == 'success':
                messages.success(
                    request,
                    get_translation(
                        'msg_email_change_success',
                        'Deine E-Mail-Adresse wurde erfolgreich auf "{new_email}" geändert.',
                        new_email=user.email,
                    ),
                )
            elif status == 'email_taken':
                messages.error(
                    request,
                    get_translation(
                        'msg_email_taken',
                        'Diese E-Mail-Adresse wird inzwischen bereits von einem anderen Konto verwendet.',
                    ),
                )
            elif status == 'wrong_code':
                messages.error(
                    request,
                    get_translation(
                        'msg_verification_code_wrong',
                        'Ungültiger Bestätigungscode. Noch {remaining} Versuch(e) verbleibend.',
                        remaining=remaining,
                    ),
                )
            elif status == 'locked':
                messages.error(
                    request,
                    get_translation(
                        'verify_code_locked',
                        'Dieser Code wurde wegen zu vieler Fehlversuche gesperrt. Bitte fordere einen neuen Code an.',
                    ),
                )
            else:
                messages.error(
                    request,
                    get_translation(
                        'msg_email_change_invalid_code',
                        'Der Bestätigungscode ist ungültig oder abgelaufen.',
                    ),
                )
            return redirect("profile")

        elif "resend_email_change_code" in request.POST:
            try:
                code_obj, status = UserService.resend_email_change_code(user)
                if status == 'no_pending_change':
                    messages.error(request, "Keine offene E-Mail-Änderung vorhanden.")
                elif status == 'email_taken':
                    messages.error(request, "Diese E-Mail-Adresse wird bereits von einem anderen Konto verwendet.")
                else:
                    messages.info(
                        request,
                        get_translation(
                            'msg_email_change_resend',
                            'Ein neuer Bestätigungscode wurde an "{new_email}" gesendet.',
                            new_email=code_obj.new_email,
                        ),
                    )
            except VerificationCodeCooldownError as e:
                messages.warning(request, str(e))
            except VerificationCodeLimitError as e:
                messages.error(request, str(e))
            return redirect("profile")

        elif "cancel_email_change" in request.POST:
            UserService.cancel_email_change(user)
            messages.info(
                request,
                get_translation(
                    'msg_email_change_cancelled',
                    'Die E-Mail-Änderung wurde abgebrochen.',
                ),
            )
            return redirect("profile")

        elif "change_password" in request.POST:
            password_form = PasswordChangeForm(user=user, data=request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(
                    request,
                    get_translation(
                        'msg_password_changed',
                        'Dein Passwort wurde erfolgreich geändert.',
                    ),
                )
                return redirect("profile")
            else:
                messages.error(
                    request,
                    get_translation(
                        'msg_password_change_error',
                        'Fehler beim Ändern des Passworts. Bitte überprüfe deine Eingaben.',
                    ),
                )

    context = {
        'profile_form': profile_form,
        'password_form': password_form,
        'registrations': registrations,
        'pending_email_code': pending_email_code,
        'pending_email_info': pending_email_info,
        'clan_membership': clan_membership,
    }
    return render(request, "users/profile.html", context)
