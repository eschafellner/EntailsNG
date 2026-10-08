"""Fixed clan payments and ticket coverage; all writes use the seating guard.

Lock order: configuration -> users by ID -> event -> clan -> payment ->
registrations/holds -> cells. No money is received by assigning a member:
paid_amount on a funded registration is an attributed share of one bank receipt.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from clans.models import Clan, ClanMembership
from configuration.models import ClanSeatConfiguration, GeneralConfiguration
from configuration.cache import invalidate_event_capacity_cache
from configuration.translations import get_translation
from emails.services import queue_system_email
from events.models import Event, EventRegistration, TicketType
from events.services import RegistrationService, PaymentService
from .models import ClanSeatPayment, ClanSeatPaymentLog, ClanSeatHold, SeatingCell
from .clan_services import ClanSeatError, seating_write, selection_revision, open_holds, effective_limit


SALT = 'clan-payment-preview-v1'


def fail(key):
    raise ClanSeatError(key)


def can_manage_payments(actor):
    return bool(actor and actor.is_authenticated and actor.is_active and not actor.is_banned
        and not actor.deleted_at and actor.is_staff and actor.has_perm('seating.manage_clan_payments'))


def committed_holds(event_id=None, now=None):
    now = now or timezone.now()
    qs = ClanSeatHold.objects.filter(payment__isnull=False, protection_active=True).filter(
        Q(payment__status=ClanSeatPayment.Status.PAID) |
        Q(payment__status=ClanSeatPayment.Status.PENDING, payment__release_at__gt=now,
          allocation__event__end_date__gt=now))
    return qs if event_id is None else qs.filter(allocation__event_id=event_id)


def reserved_ticket_count(event_id):
    if not event_id:
        return 0
    return committed_holds(event_id).filter(funded_registration__isnull=True).count()


def payment_ticket(event, config):
    tickets = list(event.ticket_types.filter(is_active=True).order_by('pk'))
    ticket = tickets[0] if len(tickets) == 1 else next(
        (t for t in tickets if t.pk == config.payment_ticket_type_id), None)
    if ticket is None:
        fail('clan_payment_ticket_missing')
    if ticket.price <= 0:
        fail('clan_payment_ticket_price')
    return ticket


def payment_preview(clan, event):
    config = ClanSeatConfiguration.load()
    if not config.enabled or effective_limit(clan, config) == 0:
        fail('clan_seat_disabled')
    if not event or not event.is_active or event.effective_status != Event.Status.REGISTRATION_OPEN:
        fail('clan_seat_event')
    allocation = clan.seat_allocations.filter(event=event).first()
    if not allocation:
        fail('clan_payment_no_seats')
    if ClanSeatPayment.objects.filter(allocation=allocation).exists():
        fail('clan_payment_locked')
    holds = list(open_holds(event.pk).filter(allocation=allocation, payment__isnull=True)
        .select_related('cell').order_by('pk'))
    if not holds:
        fail('clan_payment_no_seats')
    consumed = allocation.holds.filter(state=ClanSeatHold.State.CLAIMED).exclude(pk__in=[h.pk for h in holds]).count()
    if len(holds) + consumed > effective_limit(clan, config):
        fail('clan_seat_limit')
    ticket = payment_ticket(event, config)
    bank = GeneralConfiguration.load()
    if not bank.has_payment_details:
        fail('clan_payment_bank_missing')
    now = timezone.now()
    original_deadline = min(allocation.expires_at, event.end_date)
    if allocation.duration == ClanSeatConfiguration.Duration.EVENT:
        original_deadline = event.end_date
    release_at = min(timezone.localtime(now) + timedelta(days=config.payment_days + config.payment_review_days), original_deadline)
    payment_due_at = timezone.localtime(release_at) - timedelta(days=config.payment_review_days)
    if payment_due_at <= now:
        fail('clan_payment_short_deadline')
    if event.active_registrations_count + reserved_ticket_count(event.pk) + len(holds) > event.max_guests:
        fail('clan_payment_capacity')
    payload = {
        'clan_id': clan.pk, 'event_id': event.pk, 'allocation_id': allocation.pk,
        'holds': [h.pk for h in holds], 'revision': selection_revision(clan, event, config, allocation),
        'ticket_id': ticket.pk, 'price': str(ticket.price), 'created_at': now.isoformat(),
        'payment_due_at': payment_due_at.isoformat(), 'release_at': release_at.isoformat(),
        'beneficiary_name': bank.kontoinhaber, 'iban': bank.iban, 'bic': bank.bic,
    }
    return {'holds': holds, 'ticket': ticket, 'seat_count': len(holds), 'unit_price': ticket.price,
        'total_amount': ticket.price * len(holds), 'payment_due_at': payment_due_at,
        'release_at': release_at, 'token': signing.dumps(payload, salt=SALT), 'payload': payload}


@seating_write
def create_payment(clan_id, event_id, actor_id, token, *, confirmed=False):
    if confirmed is not True:
        fail('clan_payment_confirmation_required')
    actor = get_user_model().objects.select_for_update(no_key=True).get(pk=actor_id)
    event = Event.objects.select_for_update().get(pk=event_id)
    clan = Clan.objects.select_for_update().get(pk=clan_id)
    if actor.is_banned or not clan.is_admin(actor):
        fail('clan_seat_permission')
    try:
        payload = signing.loads(token, salt=SALT, max_age=900)
    except (signing.BadSignature, TypeError, ValueError):
        fail('clan_payment_stale')
    preview = payment_preview(clan, event)
    current = preview['payload']
    for key in ('clan_id', 'event_id', 'allocation_id', 'holds', 'revision', 'ticket_id', 'price',
                'beneficiary_name', 'iban', 'bic'):
        if payload.get(key) != current[key]:
            fail('clan_payment_stale')
    ticket = TicketType.objects.select_for_update().get(pk=current['ticket_id'])
    if not ticket.is_active or str(ticket.price) != payload['price']:
        fail('clan_payment_stale')
    now = timezone.now()
    due = timezone.datetime.fromisoformat(payload['payment_due_at'])
    release = timezone.datetime.fromisoformat(payload['release_at'])
    if due <= now or release > preview['release_at']:
        fail('clan_payment_stale')
    holds = list(ClanSeatHold.objects.select_for_update().filter(pk__in=payload['holds']).order_by('pk'))
    cells = list(SeatingCell.objects.select_for_update().filter(pk__in=[h.cell_id for h in holds]).order_by('pk'))
    if any(c.registration_id or c.cell_type != SeatingCell.CellType.SEAT or c.reservation_status != SeatingCell.ReservationStatus.FREE for c in cells):
        fail('clan_payment_stale')
    payment = ClanSeatPayment.objects.create(allocation_id=payload['allocation_id'], ticket_type=ticket,
        ticket_name=ticket.name, seat_count=len(holds), unit_price=ticket.price,
        total_amount=ticket.price * len(holds), created_by=actor, created_at=now,
        payment_due_at=due, release_at=release, beneficiary_name=payload['beneficiary_name'],
        iban=payload['iban'], bic=payload['bic'])
    ClanSeatHold.objects.filter(pk__in=payload['holds']).update(payment=payment)
    log(payment, actor, 'CREATED', details={'seat_labels': [h.seat_label for h in holds]})
    notify_payment_admins(payment, 'clan_payment_created')
    invalidate_event_capacity_cache(event.pk)
    return payment


def log(payment, actor, action, *, reason='', details=None):
    return ClanSeatPaymentLog.objects.create(payment=payment, actor=actor, action=action,
        reason=reason, details=details or {})


def notify_payment_admins(payment, template):
    from django.conf import settings
    url = (settings.PUBLIC_BASE_URL.rstrip('/')
        + reverse('clan_payment_detail', args=[payment.allocation.clan.slug])
        + f'?event={payment.allocation.event_id}')
    for membership in payment.allocation.clan.memberships.filter(status='ACCEPTED', role='ADMIN',
            user__is_active=True, user__is_banned=False, user__deleted_at__isnull=True).select_related('user'):
        queue_system_email(template, membership.user.email, {
            'username': membership.user.username, 'clan_name': payment.allocation.clan.name,
            'event_title': payment.allocation.event.title, 'reference': payment.reference,
            'amount': f'{payment.total_amount:.2f}', 'seat_count': payment.seat_count,
            'payment_due_at': timezone.localtime(payment.payment_due_at).strftime('%d.%m.%Y %H:%M'),
            'release_at': timezone.localtime(payment.release_at).strftime('%d.%m.%Y %H:%M'),
            'payment_url': url,
        }, expires_at=payment.payment_due_at if template in ('clan_payment_created', 'clan_payment_reminder') else None)


def _cancel_payment(payment, reason, actor=None):
    if payment.status != ClanSeatPayment.Status.PENDING:
        return
    payment.status = ClanSeatPayment.Status.CANCELLED
    payment.cancelled_at = timezone.now()
    payment.cancel_reason = reason
    payment.save(update_fields=['status', 'cancelled_at', 'cancel_reason'])
    payment.holds.update(protection_active=False, state=ClanSeatHold.State.RELEASED)
    log(payment, actor, 'CANCELLED', reason=reason)
    notify_payment_admins(payment, 'clan_payment_cancelled')
    invalidate_event_capacity_cache(payment.allocation.event_id)


@seating_write
def confirm_payment(payment_id, actor_id, *, received_at, amount, confirmed=False):
    if confirmed is not True:
        fail('clan_payment_confirmation_required')
    actor = get_user_model().objects.select_for_update(no_key=True).get(pk=actor_id)
    if not can_manage_payments(actor):
        fail('clan_seat_permission')
    event_id = ClanSeatPayment.objects.values_list('allocation__event_id', flat=True).get(pk=payment_id)
    event = Event.objects.select_for_update().get(pk=event_id)
    payment = ClanSeatPayment.objects.select_for_update().get(pk=payment_id)
    now = timezone.now()
    if payment.status != ClanSeatPayment.Status.PENDING or payment.release_at <= now:
        fail('clan_payment_expired')
    if not event.is_active or event.effective_status not in (Event.Status.REGISTRATION_OPEN, Event.Status.RUNNING):
        fail('clan_seat_event')
    if amount != payment.total_amount or not received_at or not payment.created_at <= received_at <= min(now, payment.payment_due_at):
        fail('clan_payment_received_invalid')
    payment.status = ClanSeatPayment.Status.PAID
    payment.received_at, payment.confirmed_at, payment.confirmed_by = received_at, now, actor
    payment.save(update_fields=['status', 'received_at', 'confirmed_at', 'confirmed_by'])
    log(payment, actor, 'CONFIRMED', details={'received_at': received_at.isoformat(), 'amount': str(amount)})
    notify_payment_admins(payment, 'clan_payment_confirmed')
    invalidate_event_capacity_cache(event.pk)
    return payment


@seating_write
def cancel_payment(payment_id, actor_id, *, reason, confirmed=False):
    actor = get_user_model().objects.select_for_update(no_key=True).get(pk=actor_id)
    if not can_manage_payments(actor):
        fail('clan_seat_permission')
    if confirmed is not True:
        fail('clan_payment_confirmation_required')
    if not reason.strip():
        fail('clan_payment_reason_required')
    event_id = ClanSeatPayment.objects.values_list('allocation__event_id', flat=True).get(pk=payment_id)
    Event.objects.select_for_update().get(pk=event_id)
    payment = ClanSeatPayment.objects.select_for_update().get(pk=payment_id)
    if payment.status != ClanSeatPayment.Status.PENDING:
        fail('clan_payment_expired')
    _cancel_payment(payment, reason.strip(), actor)


def _restore_registration(hold):
    reg = EventRegistration.objects.select_for_update().get(pk=hold.funded_registration_id)
    snapshot = hold.registration_snapshot
    reg.payment_status = snapshot.get('payment_status', EventRegistration.PaymentStatus.CANCELLED)
    reg.ticket_type_id = snapshot.get('ticket_type_id')
    reg.booking_price = Decimal(snapshot['booking_price']) if snapshot.get('booking_price') is not None else None
    reg.paid_amount = Decimal('0')
    reg.paid_at = None
    reg.is_checked_in = False
    reg.checked_in_at = None
    reg.cancelled_at = timezone.now() if reg.payment_status == EventRegistration.PaymentStatus.CANCELLED else None
    reg.save()
    hold.funded_registration = None
    hold.registration_snapshot = {}
    hold.state = ClanSeatHold.State.OPEN
    hold.claimed_by = None
    hold.save(update_fields=['funded_registration', 'registration_snapshot', 'state', 'claimed_by'])
    SeatingCell.objects.filter(pk=hold.cell_id).update(registration=None, reservation_status='FREE')
    return reg


@seating_write
def assign_member(payment_id, hold_id, actor_id, user_id, *, expected_registration_id,
                  confirmed=False, reason=''):
    if confirmed is not True:
        fail('clan_payment_confirmation_required')
    initial = ClanSeatHold.objects.get(pk=hold_id, payment_id=payment_id)
    old_user_id = EventRegistration.objects.filter(pk=initial.funded_registration_id).values_list('user_id', flat=True).first()
    user_ids = {actor_id} | ({user_id} if user_id else set()) | ({old_user_id} if old_user_id else set())
    users = {u.pk: u for u in get_user_model().objects.select_for_update(no_key=True).filter(pk__in=user_ids).order_by('pk')}
    actor = users[actor_id]
    event_id, clan_id = ClanSeatPayment.objects.values_list('allocation__event_id', 'allocation__clan_id').get(pk=payment_id)
    event = Event.objects.select_for_update().get(pk=event_id)
    clan = Clan.objects.select_for_update().get(pk=clan_id)
    orga = can_manage_payments(actor)
    if actor.is_banned or not (orga or clan.is_admin(actor)):
        fail('clan_seat_permission')
    payment = ClanSeatPayment.objects.select_for_update().get(pk=payment_id)
    hold = ClanSeatHold.objects.select_for_update().get(pk=hold_id, payment=payment)
    if hold.funded_registration_id != expected_registration_id:
        fail('clan_payment_stale')
    if payment.status != ClanSeatPayment.Status.PAID:
        fail('clan_payment_not_paid')
    if not event.is_active or event.effective_status not in (Event.Status.REGISTRATION_OPEN, Event.Status.RUNNING):
        fail('clan_seat_event')
    old_reg = EventRegistration.objects.select_for_update().filter(pk=hold.funded_registration_id).first()
    if old_reg and old_reg.is_checked_in:
        if not orga:
            fail('clan_payment_checked_in')
        if not reason.strip():
            fail('clan_payment_reason_required')
    if old_reg and old_reg.user_id == user_id:
        return hold
    target = users.get(user_id)
    if user_id and (not target or not target.is_active or target.is_banned or target.deleted_at or
            not ClanMembership.objects.filter(clan=clan, user=target, status='ACCEPTED').exists()):
        fail('clan_payment_member_invalid')
    reg = EventRegistration.objects.select_for_update().filter(user_id=user_id, event=event).first() if user_id else None
    if reg and (reg.payment_status == EventRegistration.PaymentStatus.PAID or reg.is_checked_in
            or ClanSeatHold.objects.filter(funded_registration=reg).exists()):
        fail('clan_payment_already_paid')
    if reg and reg.payment_status != EventRegistration.PaymentStatus.CANCELLED:
        if (reg.ticket_type_id and reg.ticket_type_id != payment.ticket_type_id) or (
            reg.booking_price is not None and reg.booking_price != payment.unit_price):
            fail('clan_payment_ticket_mismatch')
    restored = _restore_registration(hold) if old_reg else None
    if user_id:
        snapshot = {'payment_status': reg.payment_status if reg else 'CANCELLED',
            'ticket_type_id': reg.ticket_type_id if reg else None,
            'booking_price': str(reg.booking_price) if reg and reg.booking_price is not None else None}
        reg, _, _ = RegistrationService.register_user(target, event.pk, payment.ticket_type_id, clan_seat_hold_id=hold.pk)
        reg.ticket_type_id, reg.booking_price = payment.ticket_type_id, payment.unit_price
        reg.save(update_fields=['ticket_type', 'booking_price'])
        hold.funded_registration, hold.registration_snapshot = reg, snapshot
        hold.state, hold.claimed_by = ClanSeatHold.State.CLAIMED, target
        hold.save(update_fields=['funded_registration', 'registration_snapshot', 'state', 'claimed_by'])
        previous = list(SeatingCell.objects.select_for_update().filter(registration=reg).order_by('pk'))
        for cell in previous:
            cell.registration = None
            cell.reservation_status = SeatingCell.ReservationStatus.FREE
            cell.save(update_fields=['registration', 'reservation_status'])
        PaymentService.mark_paid(reg, amount=payment.unit_price, send_email=False, clan_seat_hold_id=hold.pk)
        cell = SeatingCell.objects.select_for_update().get(pk=hold.cell_id)
        if cell.registration_id and cell.registration_id != reg.pk:
            fail('clan_payment_stale')
        cell.registration, cell.reservation_status = reg, SeatingCell.ReservationStatus.RESERVED
        cell.save(update_fields=['registration', 'reservation_status'])
        queue_system_email('clan_payment_assigned', target.email, {'username': target.username,
            'clan_name': clan.name, 'event_title': event.title, 'seat_label': hold.seat_label,
            'reference': payment.reference, 'amount': f'{payment.unit_price:.2f}'})
    if event.active_registrations_count + reserved_ticket_count(event.pk) > event.max_guests:
        fail('clan_payment_capacity')
    log(payment, actor, 'ASSIGNED' if user_id else 'UNASSIGNED', reason=reason,
        details={'hold_id': hold.pk, 'seat_label': hold.seat_label,
                 'previous_registration_id': expected_registration_id,
                 'registration_id': hold.funded_registration_id})
    if restored:
        queue_system_email('clan_payment_removed', restored.user.email,
            {'username': restored.user.username, 'event_title': event.title, 'seat_label': hold.seat_label,
             'registration_status': restored.get_payment_status_display()})
    invalidate_event_capacity_cache(event.pk)
    return hold


def process_payments(now=None, event_id=None):
    """Caller holds the configuration guard; event signal may already hold event.

    Effective seat protection and capacity expire at release_at independently of
    the worker. The worker persists cancellation and transactional notifications.
    """
    now = now or timezone.now()
    qs = ClanSeatPayment.objects.filter(status=ClanSeatPayment.Status.PENDING)
    if event_id is not None:
        qs = qs.filter(allocation__event_id=event_id)
    for pk, event_pk in qs.order_by('pk').values_list('pk', 'allocation__event_id'):
        event = Event.objects.select_for_update().get(pk=event_pk)
        payment = ClanSeatPayment.objects.select_for_update().get(pk=pk)
        if payment.status != ClanSeatPayment.Status.PENDING:
            continue
        if not event.is_active or event.effective_status not in (Event.Status.REGISTRATION_OPEN, Event.Status.RUNNING):
            _cancel_payment(payment, get_translation('clan_payment_event_reason'))
        elif payment.release_at <= now:
            _cancel_payment(payment, get_translation('clan_payment_expiry_reason'))
        elif payment.reminder_at is None and payment.payment_due_at - timedelta(days=1) <= now < payment.payment_due_at:
            notify_payment_admins(payment, 'clan_payment_reminder')
            payment.reminder_at = now
            payment.save(update_fields=['reminder_at'])
