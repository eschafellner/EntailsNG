# events/views.py
import json
import logging
import re
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from clans.models import ClanMembership
from configuration.cache import invalidate_active_event_cache
from configuration.translations import get_translation
from configuration.models import GeneralConfiguration
from configuration.services import should_show_onboarding_ticket
from news.services import get_latest_news, get_pinned_news
from seating.services import get_event_capacity_stats
from sponsors.services import get_random_active_sponsor

from .exceptions import RegistrationError
from .models import Event, EventRegistration, TicketType
from .payment_qr import generate_checkin_qr_png, generate_epc_qr_png
from .services import RegistrationService

logger = logging.getLogger(__name__)

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
    event = get_active_event()
    general_config = GeneralConfiguration.load()

    registration = None
    ticket_types = []
    if event:
        ticket_types = list(event.ticket_types.filter(is_active=True))
        if request.user.is_authenticated:
            registration = (
                EventRegistration.objects.filter(event=event, user=request.user)
                .select_related('user', 'ticket_type')
                .prefetch_related('seats')
                .first()
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

    cap_stats = get_event_capacity_stats(event) if event else {'total_seats': 0, 'reserved_seats': 0, 'capacity_percent': 0}

    show_ticket = should_show_onboarding_ticket(
        user=request.user,
        upcoming_event=event,
        user_registration=registration,
    )

    context = {
        'event': event,
        'upcoming_event': event,
        'latest_news': get_latest_news(limit=DASHBOARD_NEWS_LIMIT),
        'pinned_news': get_pinned_news(),
        'registration': registration,
        'is_user_registered': registration is not None,
        'user_status_step': registration.status_step if registration else 1,
        'user_seat_label': registration.seat_label if registration else None,
        'ticket_types': ticket_types,
        'event_total_seats': cap_stats['total_seats'],
        'event_reserved_seats': cap_stats['reserved_seats'],
        'event_capacity_percent': cap_stats['capacity_percent'],
        'is_event_expired': event.is_expired if event else False,
        'show_onboarding_ticket': show_ticket,
        'past_registrations': past_registrations,
        'active_sponsor': get_random_active_sponsor(),
        'general_config': general_config,
        'can_show_payment_qr': registration.can_show_payment_qr if registration else False,
    }
    return render(request, 'dashboard.html', context)


@login_required
def registration_payment_qr_view(request, registration_id):
    """
    Liefert das generierte GiroCode / EPC-QR-Code PNG für die angegebene EventRegistration.
    Zugriffsschutz: Nur der Eigentümer der Anmeldung oder Staff-Mitglieder.
    Bedingungen:
    - Status muss UNPAID sein
    - Ticketpreis darf nicht 0 sein
    - Zahlungsdaten (IBAN, Kontoinhaber) müssen in GeneralConfiguration gepflegt sein
    """
    registration = get_object_or_404(
        EventRegistration.objects.select_related('user', 'ticket_type', 'event'),
        pk=registration_id,
    )

    # 1. Zugriffsschutz
    if not (request.user == registration.user or request.user.is_staff):
        raise PermissionDenied("Keine Berechtigung zum Zugriff auf diesen Zahlungs-QR-Code.")

    # 2. Statusprüfung (nur UNPAID)
    if registration.payment_status != EventRegistration.PaymentStatus.UNPAID:
        return HttpResponseBadRequest("Zahlungs-QR-Code ist nur für offene Zahlungen verfügbar.")

    # 3. Kostenloses Ticket prüfen
    if registration.ticket_type and registration.ticket_type.price == 0:
        return HttpResponseBadRequest("Kostenlose Tickets erfordern keine Zahlung.")

    # 4. Zahlungsdaten prüfen
    config = GeneralConfiguration.load()
    if not config.has_payment_details:
        raise Http404("Zahlungsdaten sind im System noch nicht hinterlegt.")

    # 5. QR-Code Bild erzeugen
    image_bytes = generate_epc_qr_png(registration, config=config)

    response = HttpResponse(image_bytes, content_type="image/png")
    response['Cache-Control'] = 'private, no-store, must-revalidate'
    return response


@login_required
def registration_checkin_qr_view(request, registration_id):
    """
    Liefert das generierte Check-In QR-Code PNG für die angegebene EventRegistration.
    Zugriffsschutz: Nur der Eigentümer der Anmeldung oder Staff-Mitglieder.
    Bedingungen:
    - Status muss PAID sein
    """
    registration = get_object_or_404(
        EventRegistration.objects.select_related('user', 'event'),
        pk=registration_id,
    )

    if not (request.user == registration.user or request.user.is_staff):
        raise PermissionDenied("Keine Berechtigung zum Zugriff auf diesen Check-in-QR-Code.")

    if registration.payment_status != EventRegistration.PaymentStatus.PAID:
        return HttpResponseBadRequest("Check-in-QR-Code ist nur für bezahlte Anmeldungen verfügbar.")

    if not registration.checkin_token:
        registration.checkin_token = uuid.uuid4()
        registration.save(update_fields=['checkin_token'])

    checkin_path = reverse(
        'process_checkin',
        kwargs={'registration_id': registration.id, 'token': registration.checkin_token},
    )
    full_url = request.build_absolute_uri(checkin_path)

    image_bytes = generate_checkin_qr_png(full_url)
    response = HttpResponse(image_bytes, content_type="image/png")
    response['Cache-Control'] = 'private, no-store, must-revalidate'
    return response





# ==============================================================================
# ANMELDUNG ZUM EVENT
# ==============================================================================


@login_required
@require_POST
def register_for_event(request, event_id):
    """Meldet den eingeloggten Benutzer für das angegebene Event an."""
    ticket_type_id = request.POST.get('ticket_type_id')

    try:
        registration, created, reactivated = RegistrationService.register_user(
            user=request.user,
            event_id=event_id,
            ticket_type_id=ticket_type_id,
        )
        if reactivated:
            messages.success(
                request,
                get_translation(
                    'msg_event_reg_reactivated',
                    'Deine Anmeldung für "{event_title}" wurde reaktiviert. '
                    'Bitte wähle bei Bedarf deinen Sitzplatz erneut aus.',
                    event_title=registration.event.title,
                ),
            )
        elif created:
            messages.success(
                request,
                get_translation(
                    'msg_event_reg_success',
                    'Du bist jetzt für "{event_title}" angemeldet.',
                    event_title=registration.event.title,
                ),
            )
        else:
            messages.info(
                request, f'Du warst bereits für "{registration.event.title}" angemeldet.'
            )
    except RegistrationError as e:
        messages.error(request, str(e))
    except Exception as e:
        logger.exception("Unerwarteter Fehler bei der Event-Registrierung für Event %s von User %s: %s", event_id, request.user, e)
        messages.error(
            request,
            'Bei der Anmeldung ist ein unerwarteter Fehler aufgetreten. '
            'Bitte lade die Seite neu oder wende dich an das Orga-Team.'
        )

    return redirect('dashboard')



# ==============================================================================
# CHECK-IN
# ==============================================================================


def _wants_json(request):
    """Erkennt AJAX-/API-Aufrufe."""
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
    )


@staff_member_required
@require_POST
def toggle_check_in_api(request):
    """Schaltet den Check-in-Status eines Gastes um (Einlass-Tool)."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
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

    active_event = get_active_event()
    if not active_event or registration.event_id != active_event.id:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Check-in abgelehnt: Diese Anmeldung gehört nicht zur aktuellen Veranstaltung.',
            },
            status=400,
        )

    if registration.is_checked_in:
        registration.check_out()
        status_msg = 'ausgecheckt'
    else:
        try:
            registration.check_in(actor=request.user, target_event=active_event)
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
    can_ci, reason = registration.can_check_in(target_event=active_event)
    if not can_ci:
        if _wants_json(request):
            return JsonResponse({'status': 'error', 'message': reason}, status=400)
        return render(
            request,
            'events/checkin_failed.html',
            {
                'registration': registration,
                'reason': reason,
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
    unpaid_count = 0
    checked_in_count = 0
    pending_count = 0
    checkin_percent = 0

    if event:
        regs_qs = EventRegistration.objects.filter(event=event).select_related(
            'user', 'ticket_type'
        ).prefetch_related('seats')
        total_count = regs_qs.count()
        paid_count = regs_qs.filter(
            payment_status=EventRegistration.PaymentStatus.PAID
        ).count()
        unpaid_count = regs_qs.exclude(
            payment_status=EventRegistration.PaymentStatus.PAID
        ).count()
        checked_in_count = regs_qs.filter(is_checked_in=True).count()
        pending_count = max(0, total_count - checked_in_count)
        checkin_percent = round((checked_in_count / total_count * 100)) if total_count > 0 else 0
        # Noch nicht eingecheckte Gäste zuerst anzeigen (Priorität am Einlass)
        registrations = regs_qs.order_by('is_checked_in', 'user__username')

    context = {
        'event': event,
        'registrations': registrations,
        'total_count': total_count,
        'paid_count': paid_count,
        'unpaid_count': unpaid_count,
        'checked_in_count': checked_in_count,
        'pending_count': pending_count,
        'checkin_percent': checkin_percent,
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
        logger.warning("QR-Scan Rate-Limiting Cache-Fehler für User %s: %s. Fail-Open aktiv.", request.user.id, e)
        attempts = 1

    if attempts > 60:
        return JsonResponse(
            {'status': 'error', 'message': 'Zu viele Scan-Anfragen in kurzer Zeit. Bitte kurz warten.'},
            status=429,
        )


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

    # Zentrale fachliche Prüfung (Single Source of Truth)
    result = registration.can_check_in(target_event=active_event)
    if not result.allowed:
        return JsonResponse(
            {
                'status': result.code,
                'user': registration.user.username,
                'full_name': registration.user.get_full_name()
                or registration.user.username,
                'ticket': (
                    registration.ticket_type.name
                    if registration.ticket_type
                    else "Standard"
                ),
                'seat': seat_label,
                'message': result.reason,
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


# ==============================================================================
# GÄSTELISTE & KONTOCHECK
# ==============================================================================


def guest_list_view(request, slug=None):
    """
    Rendert die öffentliche Gästeliste für das aktive Event (oder nach Slug).
    Zeigt Username, Clan (verlinkt), Sitzplatz (mit Highlighting-Link) und Bezahlstatus (Icon).
    Beinhaltet Suchfunktion für Username und Filter für Clans sowie die Anzeige des letzten Kontochecks.
    """
    if slug:
        event = get_object_or_404(Event, slug=slug)
    else:
        event = get_active_event()

    registrations = []
    total_count = 0
    paid_count = 0
    unpaid_count = 0
    paid_percent = 0
    unique_clans = []
    can_update_payment_check = False

    if request.user.is_authenticated:
        can_update_payment_check = (
            request.user.has_perm('events.can_update_payment_check')
            or request.user.is_staff
            or request.user.is_superuser
        )

    q = request.GET.get('q', '').strip()
    clan_filter = request.GET.get('clan', '').strip()
    status_filter = request.GET.get('status', '').strip()

    if event:
        # 1. Alle aktiven (nicht stornierten) Anmeldungen mit Sitzen und User laden
        regs_qs = (
            EventRegistration.objects.filter(event=event)
            .exclude(payment_status=EventRegistration.PaymentStatus.CANCELLED)
            .select_related('user', 'ticket_type')
            .prefetch_related('seats')
            .order_by('user__username')
        )
        all_regs = list(regs_qs)
        total_count = len(all_regs)
        paid_count = sum(
            1 for r in all_regs if r.payment_status == EventRegistration.PaymentStatus.PAID
        )
        unpaid_count = total_count - paid_count
        paid_percent = round((paid_count / total_count * 100)) if total_count > 0 else 0

        # 2. Clans in EINER Batch-Query auflösen (0 N+1 Queries)
        user_ids = [r.user_id for r in all_regs]
        active_memberships = ClanMembership.objects.filter(
            user_id__in=user_ids, status=ClanMembership.Status.ACCEPTED
        ).select_related('clan')
        clan_map = {m.user_id: m.clan for m in active_memberships}

        # Vorkommende Clans für das Filter-Dropdown sammeln
        unique_clans = sorted(
            {m.clan for m in active_memberships},
            key=lambda c: c.name.lower()
        )

        for r in all_regs:
            r.cached_clan = clan_map.get(r.user_id)

        # 3. Server-seitiges Filtern (sofern GET-Parameter gesetzt sind)
        filtered = all_regs
        if q:
            q_lower = q.lower()
            filtered = [r for r in filtered if q_lower in r.user.username.lower()]
        if clan_filter:
            if clan_filter == 'none':
                filtered = [r for r in filtered if not r.cached_clan]
            else:
                filtered = [
                    r for r in filtered
                    if r.cached_clan and (r.cached_clan.slug == clan_filter or r.cached_clan.name == clan_filter)
                ]
        if status_filter:
            if status_filter == 'paid':
                filtered = [r for r in filtered if r.payment_status == EventRegistration.PaymentStatus.PAID]
            elif status_filter == 'unpaid':
                filtered = [r for r in filtered if r.payment_status != EventRegistration.PaymentStatus.PAID]

        registrations = filtered

    context = {
        'event': event,
        'registrations': registrations,
        'total_count': total_count,
        'paid_count': paid_count,
        'unpaid_count': unpaid_count,
        'paid_percent': paid_percent,
        'clans': unique_clans,
        'search_query': q,
        'selected_clan': clan_filter,
        'selected_status': status_filter,
        'can_update_payment_check': can_update_payment_check,
        'last_payment_check': event.last_payment_check if event else None,
    }
    return render(request, 'events/guest_list.html', context)


@login_required
@require_POST
def update_payment_check_api(request, event_id):
    """
    Aktualisiert den Zeitpunkt des letzten Kontochecks für ein Event.
    Berechtigung: events.can_update_payment_check oder Staff/Superuser.
    Akzeptiert optional ein benutzerdefiniertes Datum/Uhrzeit (custom_date) oder setzt auf Jetzt.
    Unterstützt sowohl AJAX/JSON als auch reguläre POST-Formulare.
    """
    event = get_object_or_404(Event, pk=event_id)

    if not (
        request.user.has_perm('events.can_update_payment_check')
        or request.user.is_staff
        or request.user.is_superuser
    ):
        error_msg = get_translation(
            'msg_payment_check_forbidden',
            'Du hast keine Berechtigung, den Kontocheck zu aktualisieren.'
        )
        if _wants_json(request):
            return JsonResponse({'status': 'error', 'message': error_msg}, status=403)
        raise PermissionDenied(error_msg)

    custom_date_str = None
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
            custom_date_str = data.get('custom_date')
        except (json.JSONDecodeError, AttributeError):
            pass
    else:
        custom_date_str = request.POST.get('custom_date')

    new_time = timezone.now()
    if custom_date_str:
        parsed_dt = parse_datetime(custom_date_str)
        if parsed_dt:
            if timezone.is_naive(parsed_dt):
                parsed_dt = timezone.make_aware(parsed_dt)
            new_time = parsed_dt

    event.last_payment_check = new_time
    event.save(update_fields=['last_payment_check', 'updated_at'])
    invalidate_active_event_cache()

    local_time = timezone.localtime(new_time)
    formatted_time = local_time.strftime('%d.%m.%Y, %H:%M Uhr')
    success_msg = get_translation(
        'msg_payment_check_updated',
        'Zeitpunkt des letzten Kontochecks erfolgreich auf {time} gesetzt.',
        time=formatted_time
    )

    if _wants_json(request) or request.content_type == 'application/json':
        return JsonResponse({
            'status': 'success',
            'message': success_msg,
            'formatted_time': formatted_time,
            'iso_time': new_time.isoformat(),
        })

    messages.success(request, success_msg)
    return redirect(request.META.get('HTTP_REFERER') or 'guest_list')

