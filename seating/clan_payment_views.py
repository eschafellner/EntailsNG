from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseBadRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils import timezone

from clans.models import Clan, ClanMembership
from configuration.translations import get_translation
from events.models import Event, EventRegistration
from events.exceptions import RegistrationError
from events.payment_qr import generate_transfer_qr_png
from .models import ClanSeatPayment, ClanSeatHold
from .clan_services import ClanSeatError
from .clan_payment_forms import CreatePaymentForm, AssignmentForm
from .clan_payments import payment_preview, create_payment, assign_member, can_manage_payments


def payment_url(clan, event_id):
    return reverse('clan_payment_detail', args=[clan.slug]) + f'?event={event_id}'


def permitted(request, clan):
    if not (clan.is_admin(request.user) or can_manage_payments(request.user)) or request.user.is_banned:
        raise PermissionDenied(get_translation('clan_seat_permission'))


@login_required
def clan_payment_detail(request, slug):
    clan = get_object_or_404(Clan, slug=slug)
    permitted(request, clan)
    if request.GET.get('event'):
        try:
            event = get_object_or_404(Event, pk=int(request.GET['event']))
        except ValueError:
            return HttpResponseBadRequest(get_translation('clan_seat_event'))
    else:
        event = Event.objects.get_active()
        if event is None:
            latest = ClanSeatPayment.objects.filter(allocation__clan=clan).select_related('allocation__event').order_by('-created_at').first()
            event = latest.allocation.event if latest else None
    payment = ClanSeatPayment.objects.filter(allocation__clan=clan, allocation__event=event).select_related(
        'allocation__event', 'allocation__clan', 'ticket_type').first()
    preview, error, form = None, None, None
    if not payment:
        try:
            preview = payment_preview(clan, event)
            form = CreatePaymentForm(initial={'token': preview['token'], 'event_id': event.pk})
        except ClanSeatError as exc:
            error = str(exc)
    holds = list(payment.holds.select_related('funded_registration__user', 'cell').order_by('pk')) if payment else []
    paid_users = EventRegistration.objects.filter(event=event, payment_status='PAID').values_list('user_id', flat=True)
    members = ClanMembership.objects.filter(clan=clan, status='ACCEPTED', user__is_active=True,
        user__is_banned=False, user__deleted_at__isnull=True).exclude(user_id__in=paid_users).select_related('user').order_by('user__username')
    response = render(request, 'clans/clan_payment.html', {'clan': clan, 'event': event, 'payment': payment,
        'preview': preview, 'payment_error': error, 'create_form': form, 'holds': holds,
        'eligible_members': members, 'orga': can_manage_payments(request.user),
        'now': timezone.now(),
        'payment_expired': bool(payment and payment.status == 'PENDING' and payment.release_at <= timezone.now()),
        'assignment_open': bool(event and event.is_active and event.effective_status in (Event.Status.REGISTRATION_OPEN, Event.Status.RUNNING))})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_POST
def clan_payment_create(request, slug):
    clan = get_object_or_404(Clan, slug=slug)
    permitted(request, clan)
    form = CreatePaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, get_translation('clan_payment_confirmation_required'))
        return redirect('clan_payment_detail', slug=slug)
    try:
        create_payment(clan.pk, form.cleaned_data['event_id'], request.user.pk, form.cleaned_data['token'], confirmed=True)
        messages.success(request, get_translation('clan_payment_created'))
    except (ClanSeatError, Event.DoesNotExist) as exc:
        messages.error(request, str(exc) if isinstance(exc, ClanSeatError) else get_translation('clan_seat_event'))
    return redirect(payment_url(clan, form.cleaned_data['event_id']))


@login_required
@require_POST
def clan_payment_assign(request, slug, hold_id):
    clan = get_object_or_404(Clan, slug=slug)
    permitted(request, clan)
    hold = get_object_or_404(ClanSeatHold.objects.select_related('payment', 'allocation'), pk=hold_id,
        allocation__clan=clan, payment__isnull=False)
    form = AssignmentForm(request.POST)
    if not form.is_valid():
        messages.error(request, get_translation('clan_payment_confirmation_required'))
    else:
        data = form.cleaned_data
        target_id = None if request.POST.get('action') == 'unassign' else data['user_id']
        if target_id is None and request.POST.get('action') != 'unassign':
            messages.error(request, get_translation('clan_payment_member_invalid'))
        else:
            try:
                assign_member(hold.payment_id, hold.pk, request.user.pk, target_id,
                    expected_registration_id=data['expected_registration_id'], confirmed=True, reason=data['reason'])
                messages.success(request, get_translation('clan_payment_assigned' if target_id else 'clan_payment_unassigned'))
            except (ClanSeatError, RegistrationError, ValidationError) as exc:
                messages.error(request, str(exc))
    return redirect(payment_url(clan, hold.allocation.event_id))


@login_required
def clan_payment_qr(request, payment_id):
    payment = get_object_or_404(ClanSeatPayment.objects.select_related('allocation__clan'), pk=payment_id)
    permitted(request, payment.allocation.clan)
    from django.utils import timezone
    if payment.status != 'PENDING' or timezone.now() >= payment.payment_due_at:
        return HttpResponseBadRequest(get_translation('clan_payment_expired'))
    response = HttpResponse(generate_transfer_qr_png(payment.beneficiary_name, payment.iban, payment.bic,
        payment.total_amount, payment.reference), content_type='image/png')
    response['Cache-Control'] = 'private, no-store'
    return response
