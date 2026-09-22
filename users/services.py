import logging
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from emails.models import GeneralEmailSettings
from emails.services import send_system_email
from .exceptions import VerificationCodeCooldownError, VerificationCodeLimitError
from .models import EmailVerificationCode

logger = logging.getLogger(__name__)
User = get_user_model()


def _dispatch_email(template_key, recipient_email, context_data):
    """Sendet System-E-Mails nach erfolgreichem DB-Commit oder direkt bei aktivem Versand."""
    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(
            lambda: send_system_email(template_key, recipient_email, context_data)
        )
    else:
        send_system_email(template_key, recipient_email, context_data)


class UserService:
    """Zentraler Service für Account-Lifecycle, Verifizierung und Sicherheitsaktionen."""

    @staticmethod
    def register_user(user_creation_form):
        """Erstellt einen neuen Benutzer mit is_active=False und erzeugt einen Verifizierungscode.
        Reiht die Aktivierungs-E-Mail über die Transactional Outbox bzw. nach DB-Commit ein.
        """
        with transaction.atomic():
            user = user_creation_form.save(commit=False)
            user.is_active = False
            user.save()

            code_obj = EmailVerificationCode.generate_for_user(user, valid_minutes=15)
            context_data = {
                'username': user.username,
                'full_name': user.get_full_name() or user.username,
                'code': code_obj.code,
                'valid_minutes': 15,
            }
            _dispatch_email('email_verification', user.email, context_data)

        return user, code_obj

    @staticmethod
    def verify_registration_code(user, code_input):
        """Verifiziert den Registrierungscode und aktiviert das Benutzerkonto atomar."""
        return EmailVerificationCode.verify_and_consume(
            user=user,
            code_input=code_input,
            is_email_change=False,
        )

    @staticmethod
    def resend_registration_code(user):
        """Generiert einen neuen Registrierungscode und reiht die E-Mail ein."""
        with transaction.atomic():
            code_obj = EmailVerificationCode.generate_for_user(user, valid_minutes=15)
            context_data = {
                'username': user.username,
                'full_name': user.get_full_name() or user.username,
                'code': code_obj.code,
                'valid_minutes': 15,
            }
            _dispatch_email('email_verification', user.email, context_data)
        return code_obj

    @staticmethod
    def request_email_change(user, new_email):
        """Startet eine E-Mail-Änderung für das Profil.
        Prüft Eindeutigkeit, erzeugt Bestätigungscode und queued E-Mail an die neue Adresse.
        """
        normalized_new_email = new_email.strip().lower()
        if User.objects.filter(email__iexact=normalized_new_email).exclude(pk=user.pk).exists():
            return None, 'email_taken'

        with transaction.atomic():
            code_obj = EmailVerificationCode.generate_for_user(
                user, valid_minutes=15, new_email=normalized_new_email
            )
            context_data = {
                'username': user.username,
                'full_name': user.get_full_name() or user.username,
                'code': code_obj.code,
                'valid_minutes': 15,
                'new_email': normalized_new_email,
            }
            _dispatch_email('email_change_verification', normalized_new_email, context_data)

        return code_obj, 'success'

    @staticmethod
    def get_pending_email_change(user):
        """Ermittelt den aktuellsten offenen E-Mail-Änderungsauftrag für den Benutzer.
        Gibt Informationen auch dann zurück, wenn der Code abgelaufen ist, damit der Nutzer
        einen neuen Code anfordern kann, anstatt die E-Mail erneut eingeben zu müssen.
        """
        code_obj = (
            EmailVerificationCode.objects.filter(
                user=user, is_used=False, new_email__isnull=False
            )
            .order_by('-created_at')
            .first()
        )
        if not code_obj:
            return None

        # Wenn der Auftrag älter als 7 Tage ist, verwerfen wir ihn automatisch
        if timezone.now() - code_obj.created_at > timedelta(days=7):
            return None

        is_expired = timezone.now() >= code_obj.expires_at or code_obj.failed_attempts >= 5
        return {
            'code_obj': code_obj,
            'new_email': code_obj.new_email,
            'is_expired': is_expired,
            'expires_at': code_obj.expires_at,
            'failed_attempts': code_obj.failed_attempts,
        }

    @staticmethod
    def resend_email_change_code(user):
        """Sendet einen neuen Code für die offene E-Mail-Änderung."""
        pending = UserService.get_pending_email_change(user)
        if not pending:
            return None, 'no_pending_change'

        target_email = pending['new_email']
        return UserService.request_email_change(user, target_email)

    @staticmethod
    def cancel_email_change(user):
        """Bricht den aktuellen E-Mail-Änderungsauftrag ab."""
        EmailVerificationCode.objects.filter(
            user=user, is_used=False, new_email__isnull=False
        ).update(is_used=True)

    @staticmethod
    def confirm_email_change(user, code_input):
        """Bestätigt den E-Mail-Änderungscode und übernimmt die neue Adresse atomar."""
        return EmailVerificationCode.verify_and_consume(
            user=user,
            code_input=code_input,
            is_email_change=True,
        )
