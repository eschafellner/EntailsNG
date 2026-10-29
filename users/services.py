import logging
import uuid
from datetime import timedelta
from io import BytesIO
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max, OuterRef, Q, Subquery
from PIL import Image, ImageOps, UnidentifiedImageError
from configuration.translations import get_translation
from django.utils import timezone
from emails.models import GeneralEmailSettings
from emails.services import send_system_email
from .exceptions import AccountDeletionError, VerificationCodeCooldownError, VerificationCodeLimitError
from .models import GUEST_PHOTO_DIR, EmailVerificationCode, GuestPhoto

logger = logging.getLogger(__name__)
User = get_user_model()


def _dispatch_email(template_key, recipient_email, context_data, user_id=None):
    """Sendet System-E-Mails nach erfolgreichem DB-Commit oder direkt bei aktivem Versand."""
    def dispatch():
        # Ein vor der Löschung vorbereiteter Callback darf keine Mail nachreichen.
        if user_id and not User.objects.filter(pk=user_id, deleted_at__isnull=True, is_banned=False).exists():
            return
        send_system_email(template_key, recipient_email, context_data)

    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(dispatch)
    else:
        dispatch()


class UserService:
    """Zentraler Service für Account-Lifecycle, Verifizierung und Sicherheitsaktionen."""

    @staticmethod
    def register_user(user_creation_form):
        """Erstellt einen neuen Benutzer mit is_active=False und erzeugt einen Verifizierungscode.
        Reiht die Aktivierungs-E-Mail über die Transactional Outbox bzw. nach DB-Commit ein.
        """
        with transaction.atomic():
            user = user_creation_form.save(commit=False)
            from .moderation import lock_email, assert_registration_allowed
            lock_email(user.email)
            assert_registration_allowed(user.email)
            user.is_active = False
            user.email_verified = False
            user.save()

            code_obj = EmailVerificationCode.generate_for_user(user, valid_minutes=15)
            context_data = {
                'username': user.username,
                'full_name': user.get_full_name() or user.username,
                'code': code_obj.code,
                'valid_minutes': 15,
            }
            _dispatch_email('email_verification', user.email, context_data, user.pk)

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
            _dispatch_email('email_verification', user.email, context_data, user.pk)
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
            _dispatch_email('email_change_verification', normalized_new_email, context_data, user.pk)

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

    @staticmethod
    def _user_teams(user):
        from tournaments.models import Team, TeamMember
        return Team.objects.filter(
            Q(captain=user) |
            Q(memberships__user=user, memberships__status=TeamMember.Status.ACCEPTED)
        ).distinct()

    @staticmethod
    def deletion_blockers(user):
        from events.models import EventRegistration
        from tournaments.models import Tournament

        blockers = []
        from seating.models import ClanSeatPayment
        from clans.models import ClanMembership
        for membership in user.clan_memberships.filter(status=ClanMembership.Status.ACCEPTED):
            if ClanSeatPayment.objects.filter(allocation__clan_id=membership.clan_id).exists() and not membership.clan.memberships.filter(
                    status=ClanMembership.Status.ACCEPTED, user__is_active=True, user__deleted_at__isnull=True).exclude(user=user).exists():
                blockers.append(('clan_payment', get_translation('clan_payment_account_blocked')))
        if user.deleted_at:
            blockers.append(('deleted', get_translation('account_delete_already_deleted', 'Dieser Account wurde bereits gelöscht.')))
        if user.is_staff or user.is_superuser or user.role != User.Roles.USER:
            blockers.append(('privileged', get_translation(
                'account_delete_staff_blocked',
                'Mitarbeiterkonten können nicht selbst gelöscht werden. Bitte wende dich an die Administration.',
            )))
        paid = list(user.registrations.filter(
            payment_status=EventRegistration.PaymentStatus.PAID,
        ).order_by('event_id').values_list('event__title', flat=True))
        if paid:
            blockers.append(('paid_registration', get_translation(
                'account_delete_paid_blocked',
                'Du hast bezahlte Anmeldungen für folgende Veranstaltungen: {events}. Bitte kläre die Stornierung zuerst mit der Orga. Danach kannst du deinen Account löschen.',
                events=', '.join(paid),
            )))
        tournaments = list(Tournament.objects.filter(
            registrations__team__in=UserService._user_teams(user),
        ).filter(
            Q(is_generated=True) | Q(status=Tournament.Status.IN_PROGRESS),
        ).exclude(status__in=[Tournament.Status.FINISHED, Tournament.Status.CANCELLED])
            .order_by('pk').values_list('title', flat=True).distinct())
        if tournaments:
            blockers.append(('active_tournament', get_translation(
                'account_delete_tournament_blocked',
                'Du bist an laufenden oder bereits generierten Turnieren beteiligt: {tournaments}. Bitte kläre deinen Austritt zuerst mit der Turnierleitung.',
                tournaments=', '.join(tournaments),
            )))
        return blockers

    @staticmethod
    def delete_account(user, password, verify_password=True):
        """Entfernt persönliche Daten endgültig; Historie bleibt an der alten ID.

        Sperrreihenfolge: User -> Events -> Turniere -> Teams -> Anmeldungen.
        Passwortfehler werden außerhalb der zurückrollbaren Löschung persistiert.
        verify_password=False nur für die Admin-Aktion „Konto anonymisieren“.
        """
        from events.models import Event, EventRegistration
        from events.services import PaymentService
        from tournaments.models import Team, Tournament

        failure = None
        with transaction.atomic():
            locked_user = User.objects.select_for_update(no_key=True).get(pk=user.pk)
            if locked_user.deleted_at:
                raise AccountDeletionError(get_translation('account_delete_already_deleted'), 'deleted')
            if verify_password and locked_user.is_locked():
                failure = AccountDeletionError(get_translation(
                    'account_delete_locked', 'Zu viele Passwortfehlversuche. Bitte versuche es nach Ablauf der Kontosperre erneut.',
                ), 'locked')
            elif verify_password and (not password or not locked_user.check_password(password)):
                if password:
                    locked_user.register_failed_login()
                failure = AccountDeletionError(get_translation(
                    'account_delete_wrong_password', 'Das aktuelle Passwort ist nicht korrekt.',
                ), 'wrong_password')
            else:
                team_ids = list(UserService._user_teams(locked_user).values_list('pk', flat=True))
                event_ids = set(locked_user.registrations.values_list('event_id', flat=True))
                event_ids.update(Tournament.objects.filter(registrations__team_id__in=team_ids).values_list('event_id', flat=True))
                event_ids.update(Team.objects.filter(pk__in=team_ids, event__isnull=False).values_list('event_id', flat=True))
                list(Event.objects.select_for_update().filter(pk__in=event_ids).order_by('pk'))
                list(Tournament.objects.select_for_update().filter(event_id__in=event_ids).order_by('pk'))
                list(Team.objects.select_for_update().filter(pk__in=team_ids).order_by('pk'))
                registrations = list(EventRegistration.objects.select_for_update().filter(user=locked_user).order_by('pk'))
                blockers = UserService.deletion_blockers(locked_user)
                if blockers:
                    code, message = blockers[0]
                    raise AccountDeletionError(message, code)

                # Restdatensatz zuerst markieren. Die gesamte Transaktion wird bei
                # einem Fehler zurückgerollt, einschließlich Stornierungen/Nachfolge.
                original_username, original_email = locked_user.username, locked_user.email
                marker = uuid.uuid4().hex
                locked_user.username = f'deleted_{marker}'
                locked_user.email = f'{marker}@deleted.invalid'
                locked_user.first_name = locked_user.last_name = ''
                locked_user.birthday = None
                locked_user.last_login = None
                locked_user.failed_login_attempts = 0
                locked_user.locked_until = None
                locked_user.is_active = locked_user.is_staff = locked_user.is_superuser = False
                locked_user.role = User.Roles.USER
                locked_user.deleted_at = timezone.now()
                locked_user.set_unusable_password()
                locked_user.save()
                locked_user.groups.clear()
                locked_user.user_permissions.clear()

                for registration in registrations:
                    if registration.payment_status != EventRegistration.PaymentStatus.CANCELLED:
                        PaymentService.mark_cancelled(registration)
                    registration.checkin_token = uuid.uuid4()
                    registration.save(update_fields=['checkin_token'])

                UserService._leave_clans(locked_user)
                UserService._leave_teams(locked_user, team_ids, marker)
                UserService._erase_account_messages(locked_user, original_username, original_email)
                locked_user.verification_codes.all().delete()
                GuestPhotoService.delete_photo(locked_user)
                UserService._erase_account_sessions(locked_user)

        if failure:
            raise failure
        return locked_user

    @staticmethod
    def _leave_clans(user):
        from clans.models import Clan, ClanMembership
        clan_ids = list(user.clan_memberships.values_list('clan_id', flat=True))
        for clan in Clan.objects.select_for_update().filter(pk__in=clan_ids).order_by('pk'):
            from seating.models import ClanSeatPayment
            if ClanSeatPayment.objects.filter(allocation__clan=clan).exists() and not clan.memberships.filter(
                    status=ClanMembership.Status.ACCEPTED, user__is_active=True, user__deleted_at__isnull=True).exclude(user=user).exists():
                raise AccountDeletionError(get_translation('clan_payment_account_blocked'), 'clan_payment')
            clan.memberships.filter(user=user).delete()
            remaining = clan.memberships.filter(
                status=ClanMembership.Status.ACCEPTED, user__deleted_at__isnull=True,
            ).order_by('created_at', 'pk')
            if not remaining.exists():
                logo_name, storage = clan.logo.name, clan.logo.storage
                clan.delete()
                if logo_name:
                    transaction.on_commit(lambda name=logo_name, storage=storage: storage.delete(name))
            else:
                # Ein deaktivierter Admin ersetzt keinen noch aktiven Admin.
                # Bei ausschließlich inaktiven Restkonten bleibt die bisherige
                # Nachfolge erhalten, damit eine spätere Aktivierung möglich ist.
                eligible = remaining.filter(user__is_active=True)
                candidates = eligible if eligible.exists() else remaining
                if not candidates.filter(role=ClanMembership.Role.ADMIN).exists():
                    successor = candidates.first()
                    successor.role = ClanMembership.Role.ADMIN
                    successor.save(update_fields=['role'])

    @staticmethod
    def _leave_teams(user, team_ids, marker):
        from tournaments.models import Team, TeamMember, Tournament

        # Ausstehende Anfragen sind keine Turnierteilnahme.
        user.tournament_memberships.filter(status=TeamMember.Status.PENDING).delete()
        for team in Team.objects.filter(pk__in=team_ids).order_by('pk'):
            terminal = [Tournament.Status.FINISHED, Tournament.Status.CANCELLED]
            has_history = team.tournament_registrations.filter(tournament__status__in=terminal).exists()
            remaining = team.memberships.filter(
                status=TeamMember.Status.ACCEPTED, user__deleted_at__isnull=True,
            ).exclude(user=user).order_by('joined_at', 'pk')
            successor = remaining.first()
            if successor:
                team.memberships.filter(user=user).delete()
                if team.captain_id == user.pk:
                    team.captain = successor.user
                    team.save(update_fields=['captain'])
                    successor.role = TeamMember.Role.CAPTAIN
                    successor.save(update_fields=['role'])
                # Ungenerierte Turniere können keine unvollständigen Kader behalten.
                required = team.game.team_size if team.game else 1
                if remaining.count() < required:
                    team.tournament_registrations.exclude(tournament__status__in=terminal).delete()
            elif has_history:
                team.is_archived = True
                team.save(update_fields=['is_archived'])
                team.memberships.filter(status=TeamMember.Status.PENDING).delete()
                team.tournament_registrations.exclude(tournament__status__in=terminal).delete()
            else:
                team.delete()
                continue

            if team.is_solo:
                team.name = get_translation('user_deleted_name', 'Gelöschter Benutzer')
                team.slug = f'deleted-solo-{marker}-{team.pk}'
                team.tag = ''
                team.save(update_fields=['name', 'slug', 'tag'])

    @staticmethod
    def _erase_account_messages(user, original_username, original_email):
        from configuration.models import SystemErrorLog
        from emails.models import OutgoingEmail
        # Gerenderte Mailkopien; Kontaktanfragen sind zusätzlich über submitted_by zugeordnet.
        query = Q(recipient_email__iexact=original_email) | Q(submitted_by=user)
        for code in user.verification_codes.exclude(new_email__isnull=True):
            query |= Q(
                recipient_email__iexact=code.new_email,
                template_key='email_change_verification', body_text__contains=code.code,
            )
        OutgoingEmail.objects.filter(query).update(
            recipient_email=user.email, subject='', body_text='', body_html='', last_error='',
            reply_to_email='', submitted_by=None, contact_ip_hash='', contact_submission_id=None,
            status=OutgoingEmail.Status.EXPIRED, worker_id='', lease_expires_at=None,
        )
        SystemErrorLog.objects.filter(user=original_username).delete()

    @staticmethod
    def _erase_account_sessions(user):
        from django.conf import settings
        from django.contrib.sessions.models import Session
        if settings.SESSION_ENGINE not in (
            'django.contrib.sessions.backends.db', 'django.contrib.sessions.backends.cached_db',
        ):
            # Andere Stores und signierte Cookies werden durch das geänderte
            # Passwort und user_can_authenticate ebenfalls unbrauchbar.
            return
        for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator(chunk_size=500):
            data = session.get_decoded()
            if str(data.get('_auth_user_id', '')) == str(user.pk) or data.get('pending_verification_user_id') == user.pk:
                session.delete()


MAX_GUEST_PHOTO_BYTES = 10 * 1024 * 1024
MAX_GUEST_PHOTO_PIXELS = 40_000_000
# Dateien ohne Datensatz erst nach dieser Zeit löschen: Ein laufender Upload
# schreibt die Datei vor dem Commit seines Datensatzes.
ORPHAN_GUEST_PHOTO_GRACE = timedelta(hours=1)
GUEST_PHOTO_EDGE = 600
GUEST_PHOTO_FORMATS = {'JPEG', 'PNG', 'WEBP'}


def normalize_guest_photo(upload):
    """Kodiert ein Foto neu als JPEG (max. 600 px Kante) ohne EXIF-/GPS-Metadaten."""
    size = getattr(upload, 'size', None)
    if size is None or size > MAX_GUEST_PHOTO_BYTES:
        raise ValidationError(get_translation('guest_photo_too_large'))
    try:
        upload.seek(0)
        with Image.open(upload) as image:
            if image.format not in GUEST_PHOTO_FORMATS:
                raise ValidationError(get_translation('guest_photo_invalid'))
            width, height = image.size
            if width * height > MAX_GUEST_PHOTO_PIXELS:
                raise ValidationError(get_translation('guest_photo_too_many_pixels'))
            if image.format == 'JPEG':
                image.draft('RGB', (GUEST_PHOTO_EDGE * 2, GUEST_PHOTO_EDGE * 2))
            # Ausrichtung übernehmen, bevor die Metadaten verworfen werden.
            photo = ImageOps.exif_transpose(image).convert('RGB')
        photo.thumbnail((GUEST_PHOTO_EDGE, GUEST_PHOTO_EDGE))
        output = BytesIO()
        photo.save(output, format='JPEG', quality=85, optimize=True)
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise ValidationError(get_translation('guest_photo_invalid'))
    finally:
        upload.seek(0)
    return ContentFile(output.getvalue())


class GuestPhotoService:
    @staticmethod
    def compute_delete_after(user, captured_at, retention_days=None):
        """Upload bzw. Ende der letzten nicht stornierten Veranstaltung plus Löschfrist."""
        from configuration.models import GeneralConfiguration
        from events.models import EventRegistration

        if retention_days is None:
            retention_days = GeneralConfiguration.load().guest_photo_retention_days
        latest_end = (
            EventRegistration.objects.filter(user=user)
            .exclude(payment_status=EventRegistration.PaymentStatus.CANCELLED)
            .aggregate(latest=Max('event__end_date'))['latest']
        )
        base = max(captured_at, latest_end) if latest_end else captured_at
        return base + timedelta(days=retention_days)

    @staticmethod
    def save_photo(*, user, upload, actor, source, notice_confirmed=False):
        content = normalize_guest_photo(upload)
        with transaction.atomic():
            locked_user = User.objects.select_for_update(no_key=True).get(pk=user.pk)
            if locked_user.deleted_at:
                raise ValidationError(get_translation('guest_photo_account_deleted'))
            photo = GuestPhoto.objects.select_for_update().filter(user=locked_user).first() or GuestPhoto(user=locked_user)
            old_name = photo.image.name
            photo.source = source
            photo.uploaded_by = actor
            photo.captured_at = timezone.now()
            # Nur ein eigener Upload belegt die Bestätigung; eine Aufnahme am Einlass setzt sie zurück.
            photo.notice_confirmed_at = photo.captured_at if notice_confirmed else None
            photo.delete_after = GuestPhotoService.compute_delete_after(locked_user, photo.captured_at)
            try:
                photo.image.save('photo.jpg', content, save=False)
                photo.save()
            except Exception:
                if photo.image.name and photo.image.name != old_name:
                    photo.image.storage.delete(photo.image.name)
                raise
            if old_name:
                storage = photo.image.storage
                transaction.on_commit(lambda: storage.delete(old_name))
        return photo

    @staticmethod
    def refresh_delete_after(user):
        """Nach Anmeldung, Check-in oder Stornierung die Löschfrist neu berechnen."""
        photo = GuestPhoto.objects.filter(user=user).first()
        if photo:
            photo.delete_after = GuestPhotoService.compute_delete_after(user, photo.captured_at)
            photo.save(update_fields=['delete_after'])
        return photo

    @staticmethod
    def delete_photo(user):
        # Die Datei entfernt der post_delete-Handler nach dem Commit.
        return GuestPhoto.objects.filter(user=user).delete()[0] > 0

    @staticmethod
    def purge(now=None, dry_run=False):
        """Löscht abgelaufene Fotos, Datensätze ohne Datei und Dateien ohne Datensatz.

        Die Fristen werden vorher neu berechnet, damit eine geänderte Löschfrist und
        Anmeldungsänderungen außerhalb der Services (z. B. im Admin) wirksam werden.
        """
        from configuration.models import GeneralConfiguration
        from events.models import EventRegistration

        now = now or timezone.now()
        days = timedelta(days=GeneralConfiguration.load().guest_photo_retention_days)
        latest_end = (
            EventRegistration.objects.filter(user=OuterRef('user'))
            .exclude(payment_status=EventRegistration.PaymentStatus.CANCELLED)
            .values('user').annotate(latest=Max('event__end_date')).values('latest')
        )
        result = {'expired': 0, 'missing_files': 0, 'orphan_files': 0}
        storage = GuestPhoto._meta.get_field('image').storage
        for photo in GuestPhoto.objects.annotate(latest_end=Subquery(latest_end)).order_by('pk'):
            base = max(photo.captured_at, photo.latest_end) if photo.latest_end else photo.captured_at
            deadline = base + days
            if deadline <= now:
                key = 'expired'
            elif not storage.exists(photo.image.name):
                key = 'missing_files'
            else:
                if deadline != photo.delete_after and not dry_run:
                    GuestPhoto.objects.filter(pk=photo.pk, captured_at=photo.captured_at).update(delete_after=deadline)
                continue
            result[key] += 1
            if not dry_run:
                with transaction.atomic():
                    # Ein inzwischen ersetztes Foto hat ein neues Aufnahmedatum und bleibt.
                    for locked in GuestPhoto.objects.select_for_update().filter(pk=photo.pk, captured_at=photo.captured_at):
                        locked.delete()

        known = set(GuestPhoto.objects.values_list('image', flat=True))
        try:
            _, names = storage.listdir(GUEST_PHOTO_DIR)
        except FileNotFoundError:
            names = []
        for filename in names:
            name = f'{GUEST_PHOTO_DIR}/{filename}'
            if name in known or storage.get_modified_time(name) > now - ORPHAN_GUEST_PHOTO_GRACE:
                continue
            result['orphan_files'] += 1
            if not dry_run:
                storage.delete(name)
        return result
