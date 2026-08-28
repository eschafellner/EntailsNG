# events/views.py
import json
import logging
import re

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Event, EventRegistration, TicketType
from .services import RegistrationService
from .exceptions import RegistrationError

logger = logging.getLogger(__name__)

from news.services import get_latest_news, get_pinned_news
from info.services import get_event_info
from seating.services import get_event_capacity_stats
from sponsors.services import get_random_active_sponsor

# Wie viele News auf dem Dashboard erscheinen. Eine Stelle, ein Wert.
DASHBOARD_NEWS_LIMIT = 3



def get_active_event():
    """Liefert das aktuell aktive Event.

    Bewusst identisch zur Logik im Context Processor, damit Dashboard und
    Navigation nie unterschiedliche Events anzeigen.
    """
    return Event.objects.get_active()


# ==============================================================================
# DASHBOARD
# ==============================================================================


def dashboard_view(request):
    """Startseite. Funktioniert für Gäste und angemeldete Benutzer."""
    from django.utils import timezone
    from configuration.services import should_show_onboarding_ticket

    event = get_active_event()
    event_info = get_event_info()
    latest_news = get_latest_news(limit=DASHBOARD_NEWS_LIMIT)
    pinned_news = get_pinned_news()


    registration = None
    ticket_types = []
    user_status_step = 1
    user_seat_label = None

    if event:
        ticket_types = list(event.ticket_types.filter(is_active=True))

        if request.user.is_authenticated:
            registration = (
                EventRegistration.objects.filter(event=event, user=request.user)
                .select_related('user', 'ticket_type')
                .prefetch_related('seats')
                .first()
            )
            if registration:
                if registration.is_checked_in:
                    user_status_step = 4
                elif registration.payment_status == EventRegistration.PaymentStatus.PAID:
                    user_status_step = 3
                else:
                    user_status_step = 2

                seat = registration.seats.first()
                if seat:
                    user_seat_label = seat.seat_label or f'Pos ({seat.x},{seat.y})'

    cap_stats = get_event_capacity_stats(event) if event else {'total_seats': 0, 'reserved_seats': 0, 'capacity_percent': 0}

    now = timezone.now()
    is_event_expired = bool(event and event.end_date and now > event.end_date)

    show_ticket = should_show_onboarding_ticket(
        user=request.user,
        upcoming_event=event,
        user_registration=registration,
    )



    past_registrations = []
    if request.user.is_authenticated:
        past_regs_qs = EventRegistration.objects.filter(user=request.user)
        if event:
            past_regs_qs = past_regs_qs.exclude(event=event)
        past_registrations = list(
            past_regs_qs.select_related('event', 'ticket_type')
            .prefetch_related('seats')
            .order_by('-event__start_date')
        )

    context = {
        'event': event,
        'upcoming_event': event,
        'event_info': event_info,
        'latest_news': latest_news,
        'pinned_news': pinned_news,
        'registration': registration,
        'user_registration': registration,
        'is_user_registered': registration is not None,
        'user_status_step': user_status_step,
        'user_seat_label': user_seat_label,
        'ticket_types': ticket_types,
        'event_total_seats': cap_stats['total_seats'],
        'event_reserved_seats': cap_stats['reserved_seats'],
        'event_capacity_percent': cap_stats['capacity_percent'],
        'is_event_expired': is_event_expired,
        'show_onboarding_ticket': show_ticket,
        'past_registrations': past_registrations,
        'active_sponsor': get_random_active_sponsor(),
    }
    return render(request, 'dashboard.html', context)



# ==============================================================================
# ANMELDUNG ZUM EVENT
# ==============================================================================


@login_required
@require_POST
def register_for_event(request, event_id):
    """Meldet den eingeloggten Benutzer für das angegebene Event an."""
    ticket_type_id = request.POST.get('ticket_type_id')

    try:
        registration, created = RegistrationService.register_user(
            user=request.user,
            event_id=event_id,
            ticket_type_id=ticket_type_id,
        )
        if created:
            messages.success(
                request, f'Du bist jetzt für "{registration.event.title}" angemeldet.'
            )
        else:
            messages.info(
                request, f'Du warst bereits für "{registration.event.title}" angemeldet.'
            )
    except RegistrationError as e:
        messages.error(request, str(e))
    except Exception as e:
        logger.exception("Unerwarteter Fehler bei der Event-Registrierung für Event %s von User %s: %s", event_id, request.user, e)
        messages.error(request, 'Bei der Anmeldung ist ein unerwarteter Fehler aufgetreten.')

    return redirect('dashboard')



# ==============================================================================
# CHECK-IN
# ==============================================================================


def _wants_json(request):
    """Erkennt AJAX-/API-Aufrufe."""
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or request.headers.get('accept', '').startswith('application/json')
    )


@staff_member_required
@require_POST
def toggle_check_in_api(request):
    """Schaltet den Check-in-Status eines Gastes um (Einlass-Tool)."""
    from django.core.exceptions import ValidationError
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {'status': 'error', 'message': 'Ungültige Anfrage.'}, status=400
        )

    registration = EventRegistration.objects.filter(
        pk=data.get('registration_id')
    ).select_related('user', 'event').first()
    if registration is None:
        return JsonResponse(
            {'status': 'error', 'message': 'Anmeldung nicht gefunden.'},
            status=404,
        )

    if registration.is_checked_in:
        registration.check_out()
        status_msg = 'ausgecheckt'
    else:
        try:
            registration.check_in(actor=request.user)
            status_msg = 'eingecheckt'
        except ValidationError as e:
            error_message = e.messages[0] if hasattr(e, 'messages') else str(e)
            return JsonResponse({'status': 'error', 'message': error_message}, status=400)

    return JsonResponse({
        'status': 'success',
        'is_checked_in': registration.is_checked_in,
        'checked_in_at': (
            registration.checked_in_at.strftime('%H:%M:%S')
            if registration.checked_in_at
            else None
        ),
        'message': f'{registration.user.username} {status_msg}.',
    })



@staff_member_required
def process_checkin(request, registration_id, token):
    """Zeigt bei GET eine Vorschau mit Bestätigungs-Button und verarbeitet erst bei POST den Check-in."""
    registration = get_object_or_404(
        EventRegistration.objects.select_related('user', 'event', 'ticket_type'),
        pk=registration_id,
        checkin_token=token
    )

    active_event = get_active_event()
    if active_event and registration.event_id != active_event.id:
        error_msg = f"Check-in abgelehnt: Dieses Ticket gehört zur Veranstaltung '{registration.event.title}' und ist für '{active_event.title}' nicht gültig!"
        if _wants_json(request):
            return JsonResponse({'status': 'error', 'message': error_msg}, status=400)
        return render(
            request,
            'events/checkin_failed.html',
            {
                'registration': registration,
                'reason': error_msg,
            },
            status=400,
        )

    if registration.payment_status != EventRegistration.PaymentStatus.PAID:
        if _wants_json(request):
            return JsonResponse(
                {
                    'status': 'error',
                    'message': (
                        f'Check-in abgelehnt: Die Anmeldung von '
                        f'{registration.user.username} ist nicht bezahlt.'
                    ),
                },
                status=400,
            )
        return render(
            request,
            'events/checkin_failed.html',
            {
                'registration': registration,
                'reason': 'Zahlung steht noch aus.',
            },
            status=400,
        )

    seat = registration.seats.first()
    seat_label = seat.seat_label if seat else "Kein Sitzplatz"

    # GET-Request: Keine Zustandsänderung! Vorschau / Bestätigungsseite anzeigen
    if request.method == 'GET':
        if registration.is_checked_in:
            return render(
                request,
                'events/checkin_success.html',
                {
                    'registration': registration,
                    'already_checked_in': True,
                },
            )
        return render(
            request,
            'events/checkin_confirm.html',
            {
                'registration': registration,
                'seat_label': seat_label,
            },
        )

    # POST-Request: Zustandsänderung durchführen!
    already_checked_in = registration.is_checked_in
    if not already_checked_in:
        registration.check_in(target_event=active_event)

    if _wants_json(request):
        return JsonResponse({
            'status': 'success',
            'user': registration.user.username,
            'already_checked_in': already_checked_in,
            'message': f'Check-in für {registration.user.username} erfolgt.',
        })

    return render(
        request,
        'events/checkin_success.html',
        {
            'registration': registration,
            'already_checked_in': already_checked_in,
        },
    )


@staff_member_required
def checkin_scanner_view(request):
    """
    Rendert das Vor-Ort Scanner & Einlass-Tool für Helfer.
    Strikte Beschränkung: NUR Mitarbeiter (is_staff=True).
    """
    event = get_active_event()
    registrations = []
    total_count = 0
    paid_count = 0
    checked_in_count = 0

    if event:
        regs_qs = EventRegistration.objects.filter(event=event).select_related(
            'user', 'ticket_type'
        ).prefetch_related('seats')
        total_count = regs_qs.count()
        paid_count = regs_qs.filter(
            payment_status=EventRegistration.PaymentStatus.PAID
        ).count()
        checked_in_count = regs_qs.filter(is_checked_in=True).count()
        registrations = regs_qs.order_by('-is_checked_in', 'user__username')

    context = {
        'event': event,
        'registrations': registrations,
        'total_count': total_count,
        'paid_count': paid_count,
        'checked_in_count': checked_in_count,
    }
    return render(request, 'events/checkin_scanner.html', context)


@staff_member_required
@require_POST
def scan_qr_api(request):
    """
    Verarbeitet gescannte QR-Code-Daten oder manuell eingegebene Ticket-Codes für das Helfer-Tool.
    Strikte Beschränkung: NUR Mitarbeiter (is_staff=True).
    Sicherheit: Akzeptiert ausschließlich unerratbare UUIDv4 (QR) oder kryptografischen short_code (8-stellig).
    Ein Fallback auf fortlaufende Primärschlüssel (pk) ist strikt verboten!
    """
    # Rate-Limiting gegen automatisiertes Durchprobieren / Flooding
    rate_key = f"rate_limit_scan_qr_{request.user.id}"
    attempts = cache.get(rate_key, 0)
    if attempts >= 60:
        return JsonResponse(
            {'status': 'error', 'message': 'Zu viele Scan-Anfragen in kurzer Zeit. Bitte kurz warten.'},
            status=429,
        )
    cache.set(rate_key, attempts + 1, 60)

    try:
        data = json.loads(request.body)
        code_str = str(data.get('code', '')).strip()
    except json.JSONDecodeError:
        return JsonResponse(
            {'status': 'error', 'message': 'Ungültiges JSON-Format.'}, status=400
        )

    if not code_str:
        return JsonResponse(
            {'status': 'error', 'message': 'Kein QR-Code oder Ticket-Code übergeben.'}, status=400
        )

    registration = None

    # 1. Extrahiere UUID aus String, falls eine URL oder voller Text gescannt wurde
    uuid_match = re.search(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        code_str,
        re.I,
    )
    if uuid_match:
        token_uuid = uuid_match.group(0)
        registration = (
            EventRegistration.objects.filter(checkin_token=token_uuid)
            .select_related('user', 'event', 'ticket_type')
            .first()
        )

    # 2. Suche per kryptografischem short_code (z. B. "K7QM2XZ4" oder "K7QM-2XZ4")
    if not registration:
        clean_code = re.sub(r'[^A-Za-z0-9]', '', code_str).upper()
        if len(clean_code) >= 6:
            registration = (
                EventRegistration.objects.filter(short_code=clean_code)
                .select_related('user', 'event', 'ticket_type')
                .first()
            )

    if not registration:
        return JsonResponse(
            {
                'status': 'error',
                'message': f'Keine gültige Anmeldung für "{code_str}" gefunden.',
            },
            status=404,
        )

    # Sitzplatz-Bezeichnung laden
    seat = registration.seats.first()
    seat_label = seat.seat_label if seat else "Kein Platz"

    active_event = get_active_event()
    if not active_event:
        return JsonResponse(
            {'status': 'error', 'message': 'Keine aktive Veranstaltung konfiguriert.'},
            status=400,
        )

    # 3. Prüfe, ob die Anmeldung zum aktuell aktiven Event gehört
    if registration.event_id != active_event.id:
        return JsonResponse(
            {
                'status': 'event_mismatch',
                'user': registration.user.username,
                'full_name': registration.user.get_full_name()
                or registration.user.username,
                'ticket': (
                    registration.ticket_type.name
                    if registration.ticket_type
                    else "Standard"
                ),
                'seat': seat_label,
                'message': (
                    f'ABGELEHNT: Dieses Ticket gehört zur Veranstaltung "{registration.event.title}" '
                    f'und ist für die aktuelle Veranstaltung "{active_event.title}" nicht gültig!'
                ),
            },
            status=400,
        )

    # 4. Prüfe Zahlungsstatus
    if registration.payment_status != EventRegistration.PaymentStatus.PAID:
        return JsonResponse(
            {
                'status': 'unpaid',
                'user': registration.user.username,
                'full_name': registration.user.get_full_name()
                or registration.user.username,
                'ticket': (
                    registration.ticket_type.name
                    if registration.ticket_type
                    else "Standard"
                ),
                'seat': seat_label,
                'message': (
                    f'ABGELEHNT: Die Anmeldung von {registration.user.username} ist noch NICHT BEZAHLT.'
                ),
            },
            status=400,
        )

    already_checked_in = registration.is_checked_in
    if not already_checked_in:
        registration.check_in(target_event=active_event)

    return JsonResponse({
        'status': 'already_checked_in' if already_checked_in else 'success',
        'registration_id': registration.id,
        'user': registration.user.username,
        'full_name': registration.user.get_full_name()
        or registration.user.username,
        'ticket': (
            registration.ticket_type.name
            if registration.ticket_type
            else "Standard"
        ),
        'seat': seat_label,
        'already_checked_in': already_checked_in,
        'checked_in_at': (
            registration.checked_in_at.strftime('%H:%M:%S')
            if registration.checked_in_at
            else ''
        ),
        'message': (
            f'Einlass gestattet: {registration.user.username} '
            f'{"(Bereits vorher eingecheckt)" if already_checked_in else "erfolgreich eingecheckt!"}'
        ),
    })

