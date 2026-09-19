import logging
import secrets
from datetime import timedelta
from django.contrib import messages

logger = logging.getLogger(__name__)
from django.contrib.auth import get_user_model, login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from emails.models import GeneralEmailSettings
from emails.services import send_system_email
from events.models import EventRegistration
from configuration.translations import get_translation
from .auth_backends import get_client_ip
from .exceptions import VerificationCodeCooldownError, VerificationCodeLimitError
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

        status, code_obj, remaining = EmailVerificationCode.verify_and_consume(
            user=user,
            code_input=code_input,
            is_email_change=False,
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
                f"Ungültiger Verifizierungscode. Noch {remaining} Versuch(e) verbleibend.",
            )
        elif status == 'locked':
            messages.error(
                request,
                "Zu viele Fehlversuche. Dieser Bestätigungscode wurde gesperrt. Bitte fordere einen neuen Code an.",
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
    except VerificationCodeCooldownError as e:
        messages.warning(request, str(e))
        return redirect("verify_email")
    except VerificationCodeLimitError as e:
        messages.error(request, str(e))
        return redirect("verify_email")

    messages.info(
        request,
        get_translation(
            'msg_verification_code_sent',
            'Ein neuer Bestätigungscode wurde an {email} gesendet.',
            email=user.email,
        ),
    )
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

    from clans.models import ClanMembership
    clan_membership = ClanMembership.get_user_active_membership(user)

    profile_form = UserProfileForm(instance=user)
    password_form = PasswordChangeForm(user=user)

    pending_email_code = EmailVerificationCode.objects.filter(
        user=user, is_used=False, new_email__isnull=False, expires_at__gt=timezone.now()
    ).order_by('-created_at').first()

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
                            with transaction.atomic():
                                code_obj = EmailVerificationCode.generate_for_user(
                                    user, valid_minutes=15, new_email=target_email
                                )
                                context_data = {
                                    'username': user.username,
                                    'full_name': user.get_full_name() or user.username,
                                    'code': code_obj.code,
                                    'valid_minutes': 15,
                                    'new_email': target_email,
                                }
                                transaction.on_commit(
                                    lambda: send_system_email(
                                        'email_change_verification', target_email, context_data
                                    )
                                )
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

            status, code_obj, remaining = EmailVerificationCode.verify_and_consume(
                user=user,
                code_input=code_input,
                is_email_change=True,
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
            if not pending_email_code:
                return redirect("profile")

            target_email = pending_email_code.new_email
            try:
                with transaction.atomic():
                    new_code = EmailVerificationCode.generate_for_user(
                        user, valid_minutes=15, new_email=target_email
                    )
                    context_data = {
                        'username': user.username,
                        'full_name': user.get_full_name() or user.username,
                        'code': new_code.code,
                        'valid_minutes': 15,
                        'new_email': target_email,
                    }
                    transaction.on_commit(
                        lambda: send_system_email(
                            'email_change_verification', target_email, context_data
                        )
                    )
                messages.info(
                    request,
                    get_translation(
                        'msg_email_change_resend',
                        'Ein neuer Bestätigungscode wurde an "{new_email}" gesendet.',
                        new_email=target_email,
                    ),
                )
            except VerificationCodeCooldownError as e:
                messages.warning(request, str(e))
            except VerificationCodeLimitError as e:
                messages.error(request, str(e))
            return redirect("profile")

        elif "cancel_email_change" in request.POST:
            if pending_email_code:
                pending_email_code.is_used = True
                pending_email_code.save(update_fields=['is_used'])
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
                update_session_auth_hash(request, user)  # Verhindert Ausloggen
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
        'clan_membership': clan_membership,
    }
    return render(request, "users/profile.html", context)
