"""Synthetic examples; never import an installation snapshot or reset live data."""
from datetime import timedelta
from io import StringIO

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.db import connection, transaction
from django.utils import timezone

from .models import DemoDataset

DATASET_NAME = 'synthetic-lan'
DATASET_VERSION = 1
DOMAIN_APPS = {'events', 'seating', 'clans', 'tournaments', 'news', 'info',
               'knowledge', 'sponsors', 'media_designer'}


class DemoDataError(Exception):
    pass


def _verify_dataset(dataset):
    if dataset.version != DATASET_VERSION:
        raise DemoDataError('Die Demo-Version weicht ab. Keine automatische Umstellung.')
    try:
        if not dataset.objects_manifest:
            raise ValueError
        for record in dataset.objects_manifest:
            model = apps.get_model(record['model'])
            if model._meta.app_label not in DOMAIN_APPS | {'users'}:
                raise ValueError
            obj = model.objects.get(pk=record['pk'])
            if any(getattr(obj, field) != value for field, value in record['relations'].items()):
                raise ValueError
    except (LookupError, KeyError, TypeError, ValueError, AttributeError, ObjectDoesNotExist):
        raise DemoDataError('Demo unvollständig oder Beziehungen verändert. Keine Daten geändert.') from None


def _ensure_empty():
    if get_user_model().objects.exclude(is_superuser=True, is_staff=True, is_active=True,
                                        is_banned=False, deleted_at__isnull=True).exists():
        raise DemoDataError('Benutzer-Fachdaten vorhanden. Demo nur auf frischer Datenbank einrichten.')
    for model in apps.get_models():
        if model._meta.app_label in DOMAIN_APPS and model.objects.exists():
            raise DemoDataError('Fachdaten vorhanden. Demo nur auf frischer Datenbank einrichten.')
    from emails.models import OutgoingEmail
    from users.models import UserBan, EmailVerificationCode
    if any(model.objects.exists() for model in (OutgoingEmail, UserBan, EmailVerificationCode)):
        raise DemoDataError('Nachrichten oder Benutzeraktionen vorhanden. Keine Demo eingerichtet.')


def _create_objects():
    from clans.models import Clan, ClanMembership
    from events.models import Event, TicketType, EventRegistration
    from seating.models import SeatingPlan, SeatingCell
    from tournaments.models import Game, Team, TeamMember, Tournament, TournamentRegistration

    manifest = []

    def remember(obj):
        manifest.append({'model': obj._meta.label_lower, 'pk': obj.pk,
                         'relations': {f.attname: getattr(obj, f.attname)
                                       for f in obj._meta.fields if f.many_to_one}})
        return obj

    now = timezone.now()
    event = remember(Event.objects.create(
        title='Demo LAN', slug='demo-lan', status=Event.Status.DRAFT, is_active=False,
        location='Synthetische Demo-Halle', max_guests=8,
        start_date=now + timedelta(days=30), end_date=now + timedelta(days=32),
        description='Synthetische Beispieldaten. Nach Einrichtung der E-Mail-Konfiguration öffnen.'))
    ticket = remember(TicketType.objects.create(event=event, name='Demo-Ticket', price=0))
    plan = remember(SeatingPlan.objects.create(event=event, name='Demo-Halle', columns=4, rows=2))
    guests = [remember(get_user_model().objects.create_user(
        username=f'demo_guest_{n}', email=f'demo_guest_{n}@example.invalid', password=None,
        first_name='Demo', last_name=f'Gast {n}',
        is_active=True, email_verified=True)) for n in range(1, 5)]
    clan = remember(Clan.objects.create(name='Demo Clan', tag='DEMO', password=''))
    for index, guest in enumerate(guests):
        remember(ClanMembership.objects.create(clan=clan, user=guest,
                 role=ClanMembership.Role.ADMIN if index == 0 else ClanMembership.Role.MEMBER))
    # Bootstrap examples in an inactive draft; no registration/payment email actions.
    registrations = [remember(EventRegistration.objects.create(
        event=event, user=guest, ticket_type=ticket, booking_price=0,
        payment_status=EventRegistration.PaymentStatus.PAID, paid_amount=0, paid_at=now)) for guest in guests]
    for index in range(8):
        remember(SeatingCell.objects.create(
            plan=plan, x=index % 4 + 1, y=index // 4 + 1, cell_type=SeatingCell.CellType.SEAT,
            seat_label=f'D{index + 1}', registration=registrations[index] if index < 4 else None,
            reservation_status=SeatingCell.ReservationStatus.RESERVED if index < 4 else SeatingCell.ReservationStatus.FREE))
    game = remember(Game.objects.create(name='Demo Arena', slug='demo-arena', team_size=2, mode='2v2'))
    tournament = remember(Tournament.objects.create(
        event=event, game=game, title='Demo Cup', slug='demo-cup',
        mode=Tournament.Mode.SINGLE_ELIMINATION, status=Tournament.Status.DRAFT,
        registration_start=now, registration_end=now + timedelta(days=29)))
    for index in range(2):
        captain, member = guests[index * 2:index * 2 + 2]
        team = remember(Team.objects.create(name=f'Demo Team {index + 1}', game=game, event=event, captain=captain))
        remember(TeamMember.objects.create(team=team, user=captain, role=TeamMember.Role.CAPTAIN))
        remember(TeamMember.objects.create(team=team, user=member, role=TeamMember.Role.MEMBER))
        remember(TournamentRegistration.objects.create(tournament=tournament, team=team))
    return manifest


def seed_demo_data():
    """True on creation, False on an intact repeated initialization."""
    if not settings.DEMO_MODE:
        raise DemoDataError('Demo deaktiviert. DEMO_MODE=True ausdrücklich für diese Demo-Umgebung setzen.')
    if connection.vendor != 'postgresql':
        raise DemoDataError('Die Demo benötigt PostgreSQL.')
    from backups.locking import access_guard
    with access_guard(), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s, %s)', [1728031, 1])
        dataset = DemoDataset.objects.filter(name=DATASET_NAME).first()
        if dataset:
            _verify_dataset(dataset)
            return False
        _ensure_empty()
        for command in ('seed_translations', 'seed_features', 'seed_email_templates'):
            call_command(command, stdout=StringIO())
        manifest = _create_objects()
        DemoDataset.objects.create(name=DATASET_NAME, version=DATASET_VERSION, objects_manifest=manifest)
        return True
