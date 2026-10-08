"""Event-bound clan holds. All seating writes acquire the configuration guard first.

The short configuration-row lock coordinates quota edits, expiry, booking and
layout changes. User/Clan locks follow it; existing account-deletion locks
(User -> Clan -> Registration -> Cell) never acquire the configuration lock.
"""
import hashlib
import json
from datetime import timedelta
from functools import wraps

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from clans.models import Clan, ClanMembership
from configuration.models import ClanSeatConfiguration
from configuration.cache import invalidate_event_capacity_cache
from configuration.translations import get_translation
from emails.services import queue_system_email
from events.models import Event
from .models import ClanSeatAllocation, ClanSeatHold, SeatingCell, SeatingPlan
from .clan_texts import TEXTS
from .clan_payment_texts import TEXTS as PAYMENT_TEXTS


class ClanSeatError(Exception):
    def __init__(self, key):
        super().__init__(get_translation(key, {**TEXTS, **PAYMENT_TEXTS}[key]))


def lock_configuration():
    ClanSeatConfiguration.load()
    return ClanSeatConfiguration.objects.select_for_update().get(pk=1)


def seating_write(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with transaction.atomic():
            lock_configuration()
            return function(*args, **kwargs)
    return guarded


def effective_limit(clan, config=None):
    config = config or ClanSeatConfiguration.load()
    return config.default_limit if clan.seat_limit_override is None else clan.seat_limit_override


def live_holds(event_id=None, now=None):
    """CLAIMED holds become open again if their personal booking is released."""
    now = now or timezone.now()
    config = ClanSeatConfiguration.load()
    qs = ClanSeatHold.objects.filter(
        payment__isnull=True,
        protection_active=True, cell__isnull=False,
        allocation__expired_at__isnull=True,
        allocation__event__is_active=True,
        allocation__event__status__in=[Event.Status.REGISTRATION_OPEN, Event.Status.RUNNING],
        allocation__event__end_date__gt=now,
        cell__cell_type=SeatingCell.CellType.SEAT,
    ).filter(Q(allocation__duration=ClanSeatConfiguration.Duration.EVENT) | Q(allocation__expires_at__gt=now)).exclude(cell__reservation_status=SeatingCell.ReservationStatus.BLOCKED).exclude(allocation__clan__seat_limit_override=0)
    if not config.enabled or config.default_limit == 0:
        if not config.enabled:
            qs = qs.none()
        else:
            qs = qs.filter(allocation__clan__seat_limit_override__gt=0)
    if event_id is not None:
        qs = qs.filter(allocation__event_id=event_id)
    from .clan_payments import committed_holds
    funded = committed_holds(event_id, now)
    return ClanSeatHold.objects.filter(Q(pk__in=qs.values('pk')) | Q(pk__in=funded.values('pk')))


def open_holds(event_id=None, now=None):
    return live_holds(event_id, now).filter(cell__registration__isnull=True)


def check_clan_access(cell, user):
    from .clan_payments import committed_holds
    if committed_holds(cell.plan.event_id).filter(cell=cell).exists():
        return False, get_translation('clan_payment_managed_hint')
    # Retain protection on unpaid personal bookings, too: outsiders cannot overwrite them.
    hold = live_holds(cell.plan.event_id).filter(cell=cell).select_related('allocation__clan').first()
    if hold and not ClanMembership.objects.filter(
        clan_id=hold.allocation.clan_id, user=user, status=ClanMembership.Status.ACCEPTED,
        user__is_active=True, user__deleted_at__isnull=True,
    ).exists():
        return False, get_translation('clan_seat_members_only', TEXTS['clan_seat_members_only'], clan=hold.allocation.clan.name)
    return True, ''


def claim_hold(cell):
    if cell.registration_id:
        live_holds(cell.plan.event_id).filter(cell=cell).update(
            state=ClanSeatHold.State.CLAIMED, claimed_by_id=cell.registration.user_id,
        )


def release_holds(qs):
    """Detach protection; preserve the consumed quota of previously claimed seats."""
    qs = qs.filter(Q(payment__isnull=True) | Q(payment__status='CANCELLED') |
        Q(payment__status='PENDING', payment__release_at__lte=timezone.now()))
    qs.filter(state=ClanSeatHold.State.OPEN).update(state=ClanSeatHold.State.RELEASED, protection_active=False)
    qs.exclude(state=ClanSeatHold.State.OPEN).update(protection_active=False)


def expire_allocation(allocation, now, *, notify=True):
    holds = allocation.holds.filter(protection_active=True, payment__isnull=True)
    labels = list(holds.filter(cell__registration__isnull=True, cell__isnull=False).values_list('seat_label', flat=True))
    if labels and notify:
        notify_admins(allocation, 'clan_seat_expired', labels)
    release_holds(holds)
    allocation.expired_at = now
    allocation.save(update_fields=['expired_at'])
    invalidate_event_capacity_cache(allocation.event_id)


def notify_admins(allocation, template, labels):
    # Separate outbox message per current admin. Never reveal recipient lists.
    admins = ClanMembership.objects.filter(
        clan_id=allocation.clan_id, status=ClanMembership.Status.ACCEPTED,
        role=ClanMembership.Role.ADMIN, user__is_active=True, user__deleted_at__isnull=True,
    ).select_related('user')
    from django.conf import settings
    from django.urls import reverse
    base = settings.PUBLIC_BASE_URL.rstrip('/')
    for membership in admins:
        queue_system_email(template, membership.user.email, {
            'username': membership.user.username,
            'clan_name': allocation.clan.name, 'event_title': allocation.event.title,
            'expires_at': timezone.localtime(allocation.expires_at).strftime('%d.%m.%Y %H:%M'),
            'open_count': len(labels), 'seat_labels': ', '.join(labels),
            'seating_url': base + reverse('clan_seat_selection', args=[allocation.clan.slug]),
        }, expires_at=allocation.expires_at if template == 'clan_seat_reminder' else None)


def _remind(allocation, now):
    if allocation.reminder_at is None and allocation.expires_at - timedelta(days=7) <= now < allocation.expires_at:
        labels = list(open_holds(allocation.event_id, now).filter(allocation=allocation, payment__isnull=True).values_list('seat_label', flat=True))
        if labels:
            notify_admins(allocation, 'clan_seat_reminder', labels)
            allocation.reminder_at = now
            allocation.save(update_fields=['reminder_at'])


@seating_write
def update_selection(clan_id, actor_id, event_id, cell_ids, *, expected_revision=None):
    if (not isinstance(cell_ids, list) or any(type(v) is not int or v < 1 for v in cell_ids)
            or len(cell_ids) != len(set(cell_ids))):
        raise ClanSeatError('clan_seat_invalid')
    actor = get_user_model().objects.select_for_update().get(pk=actor_id)
    event = Event.objects.select_for_update().get(pk=event_id)
    clan = Clan.objects.select_for_update().get(pk=clan_id)
    if not clan.is_admin(actor):
        raise ClanSeatError('clan_seat_permission')
    config = ClanSeatConfiguration.objects.get(pk=1)
    limit = effective_limit(clan, config)
    if not config.enabled or limit == 0:
        raise ClanSeatError('clan_seat_disabled')
    now = timezone.now()
    if not event.is_active or event.effective_status not in (Event.Status.REGISTRATION_OPEN, Event.Status.RUNNING):
        raise ClanSeatError('clan_seat_event')
    plan = SeatingPlan.objects.select_for_update().filter(event=event).first()
    if plan is None:
        raise ClanSeatError('clan_seat_event')
    allocation = ClanSeatAllocation.objects.filter(clan=clan, event=event).first()
    if allocation and hasattr(allocation, 'payment'):
        raise ClanSeatError('clan_payment_locked')
    if expected_revision is not None and expected_revision != selection_revision(clan, event, config, allocation):
        raise ClanSeatError('clan_seat_stale')
    if allocation and (allocation.expired_at or (event.end_date if allocation.duration == config.Duration.EVENT else allocation.expires_at) <= now):
        raise ClanSeatError('clan_seat_expired')
    # Nothing selected must not start a new clock.
    if allocation is None and not cell_ids:
        return selection_status(clan, event)
    if allocation is None:
        deadline = (now + timedelta(days=config.days) if config.duration == config.Duration.DAYS
                    else config.deadline if config.duration == config.Duration.FIXED else event.end_date)
        if deadline is None or deadline <= now:
            raise ClanSeatError('clan_seat_expired')
        allocation = ClanSeatAllocation.objects.create(
            clan=clan, event=event, created_by=actor, created_at=now,
            duration=config.duration, expires_at=min(deadline, event.end_date),
        )
    current_open = list(open_holds(event.id, now).filter(allocation=allocation))
    open_ids = {h.cell_id for h in current_open}
    consumed = allocation.holds.filter(state=ClanSeatHold.State.CLAIMED).exclude(pk__in=[h.pk for h in current_open if h.cell_id in cell_ids]).count()
    # A lowered quota can be below consumed bookings; still permit releasing open seats.
    if len(cell_ids) + consumed > limit and (set(cell_ids) - open_ids or len(cell_ids) > max(0, limit - consumed)):
        raise ClanSeatError('clan_seat_limit')
    cells = list(SeatingCell.objects.select_for_update().filter(pk__in=cell_ids, plan=plan).order_by('pk'))
    if len(cells) != len(cell_ids):
        raise ClanSeatError('clan_seat_invalid')
    for cell in cells:
        if cell.pk in open_ids:
            continue
        if cell.cell_type != SeatingCell.CellType.SEAT or cell.registration_id or cell.reservation_status != SeatingCell.ReservationStatus.FREE:
            raise ClanSeatError('clan_seat_conflict')
        protected = live_holds(event.id, now).filter(cell=cell).first()
        if protected:
            raise ClanSeatError('clan_seat_conflict')
    release_holds(allocation.holds.filter(pk__in=[h.pk for h in current_open if h.cell_id not in cell_ids]))
    for cell in cells:
        if cell.pk not in open_ids:
            # Old, elapsed protection must not block the conditional unique constraint.
            release_holds(ClanSeatHold.objects.filter(cell=cell, protection_active=True))
            ClanSeatHold.objects.create(allocation=allocation, cell=cell, seat_label=cell.seat_label or f'{cell.x},{cell.y}')
    _remind(allocation, now)
    invalidate_event_capacity_cache(event.id)
    return selection_status(clan, event)


def selection_revision(clan, event, config, allocation):
    rows = [] if allocation is None else list(allocation.holds.order_by('pk').values_list(
        'pk', 'state', 'protection_active', 'cell_id', 'cell__registration_id'))
    payload = [rows, effective_limit(clan, config), config.enabled, config.duration,
               config.days, str(config.deadline), event.is_active, event.status, str(event.end_date),
               str(allocation.expires_at) if allocation else None,
               str(allocation.expired_at) if allocation else None]
    payload.extend([config.payment_ticket_type_id, config.payment_days, config.payment_review_days,
        list(event.ticket_types.order_by('pk').values_list('pk', 'is_active', 'price')),
        list(event.seating_plan.cells.order_by('pk').values_list('pk', 'seat_label')) if hasattr(event, 'seating_plan') else []])
    return hashlib.sha256(json.dumps(payload, default=str).encode()).hexdigest()


def selection_status(clan, event):
    config = ClanSeatConfiguration.load()
    allocation = ClanSeatAllocation.objects.filter(clan=clan, event=event).first()
    holds = list(open_holds(event.pk).filter(allocation__clan=clan))
    claimed = 0 if allocation is None else allocation.holds.filter(state=ClanSeatHold.State.CLAIMED).exclude(pk__in=[h.pk for h in holds]).count()
    now = timezone.now()
    valid_event = event.is_active and event.effective_status in (Event.Status.REGISTRATION_OPEN, Event.Status.RUNNING)
    return {
        'revision': selection_revision(clan, event, config, allocation),
        'limit': effective_limit(clan, config), 'claimed': claimed,
        'selected': [h.cell_id for h in holds],
        'consumed_open': [h.cell_id for h in holds if h.state == ClanSeatHold.State.CLAIMED],
        'expires_at': (event.end_date if allocation.duration == config.Duration.EVENT else allocation.expires_at).isoformat() if allocation else None,
        'enabled': not (allocation and hasattr(allocation, 'payment')) and config.enabled and effective_limit(clan, config) > 0 and valid_event and (
            allocation is None or (allocation.expired_at is None and (event.end_date if allocation.duration == config.Duration.EVENT else allocation.expires_at) > now)),
    }


@seating_write
def process_clan_holds():
    now = timezone.now()
    from .clan_payments import process_payments
    process_payments(now)
    config = ClanSeatConfiguration.objects.get(pk=1)
    for allocation_id in ClanSeatAllocation.objects.filter(expired_at__isnull=True).order_by('pk').values_list('pk', flat=True):
        event_id = ClanSeatAllocation.objects.values_list('event_id', flat=True).get(pk=allocation_id)
        Event.objects.select_for_update().get(pk=event_id)
        allocation = ClanSeatAllocation.objects.select_for_update(of=('self',)).select_related('clan', 'event').get(pk=allocation_id)
        if allocation.expired_at:
            continue
        if allocation.duration == config.Duration.EVENT and allocation.event.end_date != allocation.expires_at:
            allocation.expires_at = allocation.event.end_date
            allocation.save(update_fields=['expires_at'])
        if (allocation.expires_at <= now or not allocation.event.is_active
                or allocation.event.effective_status not in (Event.Status.REGISTRATION_OPEN, Event.Status.RUNNING)):
            expire_allocation(allocation, now)
        elif not config.enabled or effective_limit(allocation.clan, config) == 0:
            release_holds(allocation.holds.filter(protection_active=True))
        else:
            _remind(allocation, now)
