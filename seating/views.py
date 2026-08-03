import json
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from events.models import Event, EventRegistration
from .models import SeatingCell, SeatingPlan


def seating_plan_view(request):
    """Rendert die öffentliche Sitzplanseite für das aktive Event."""
    event = Event.objects.filter(is_active=True).first()
    return render(request, 'seating/seating.html', {'event': event})


@staff_member_required
def seating_editor(request, plan_id):
    """Rendert die Editor-Spezialseite für Admins/Staff"""
    plan = get_object_or_404(SeatingPlan, pk=plan_id)

    # Alle bestehenden Kacheln als Dictionary laden
    cells_data = list(
        plan.cells.values(
            'x',
            'y',
            'cell_type',
            'seat_label',
            'text_label',
            'reservation_status',
        )
    )

    context = {
        'plan': plan,
        'cells_json': json.dumps(cells_data),
    }
    return render(request, 'seating/editor.html', context)


@staff_member_required
@require_POST
def save_seating_plan(request, plan_id):
    """Speichert das geänderte Raster per AJAX-Call und löscht entfernte Kacheln."""
    plan = get_object_or_404(SeatingPlan, pk=plan_id)

    try:
        data = json.loads(request.body)
        cells_to_save = data.get('cells', [])

        # 1. Alle Koordinaten sammeln, die das Frontend aktuell mitschickt
        sent_coordinates = set()
        for cell_data in cells_to_save:
            sent_coordinates.add((cell_data['x'], cell_data['y']))

        # 2. Alle Kacheln aus der Datenbank LÖSCHEN, die im Frontend gelöscht wurden
        existing_cells = plan.cells.all()
        for cell in existing_cells:
            if (cell.x, cell.y) not in sent_coordinates:
                cell.delete()

        # 3. Bestehende Kacheln aktualisieren oder neue erstellen
        for cell_data in cells_to_save:
            x = cell_data['x']
            y = cell_data['y']
            cell_type = cell_data['cell_type']
            seat_label = cell_data.get('seat_label', '')
            text_label = cell_data.get('text_label', '')

            cell, created = SeatingCell.objects.get_or_create(
                plan=plan,
                x=x,
                y=y,
                defaults={
                    'cell_type': cell_type,
                    'seat_label': seat_label,
                    'text_label': text_label,
                },
            )

            if not created:
                cell.cell_type = cell_type
                cell.seat_label = seat_label
                cell.text_label = text_label
                cell.save()

        return JsonResponse(
            {'status': 'success', 'message': 'Sitzplan erfolgreich gespeichert!'}
        )

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


def get_event_seating_api(request, event_id):
    """
    Liefert den Sitzplan einer Veranstaltung inkl. Belegung, dynamischem Bezahlstatus & Check-in-Status als JSON.
    """
    try:
        plan = SeatingPlan.objects.get(event_id=event_id)
    except SeatingPlan.DoesNotExist:
        return JsonResponse(
            {'error': 'Kein Sitzplan für diese Veranstaltung vorhanden.'},
            status=404,
        )

    # Clan-Zugehörigkeiten für angemeldete User laden
    from clans.models import ClanMembership
    user_clan_map = {}
    active_memberships = ClanMembership.objects.filter(
        status=ClanMembership.Status.ACCEPTED
    ).select_related('clan', 'user')
    for m in active_memberships:
        user_clan_map[m.user_id] = m.clan.name

    current_user_clan_name = None
    if request.user.is_authenticated:
        current_user_clan_name = user_clan_map.get(request.user.id)

    cells = []
    for c in plan.cells.select_related('registration__user').all():
        username = None
        clan_name = None
        is_checked_in = False

        # Dynamische Statusbestimmung für das Frontend:
        if c.reservation_status == SeatingCell.ReservationStatus.BLOCKED:
            computed_status = 'BLOCKED'
        elif c.registration:
            user = c.registration.user
            username = user.username if user else None
            if user:
                clan_name = user_clan_map.get(user.id)
            is_checked_in = c.registration.is_checked_in

            # Differenzierung: Bezahlt vs. Vorgemerkt (Unbezahlt)
            if (
                c.registration.payment_status
                == EventRegistration.PaymentStatus.PAID
            ):
                computed_status = 'RESERVED'  # Rot / Belegt
            else:
                computed_status = 'PRE_RESERVED'  # Gelb / Vorreserviert
        else:
            computed_status = 'FREE'  # Grün / Frei

        cells.append({
            'x': c.x,
            'y': c.y,
            'cell_type': c.cell_type,
            'seat_label': c.seat_label,
            'text_label': c.text_label,
            'status': computed_status,
            'occupied_by': username,
            'clan_name': clan_name,
            'is_checked_in': is_checked_in,
        })

    return JsonResponse({
        'plan_id': plan.id,
        'name': plan.name,
        'columns': plan.columns,
        'rows': plan.rows,
        'user_clan_name': current_user_clan_name,
        'cells': cells,
    })


@login_required
@require_POST
def reserve_seat_api(request, event_id):
    """API fürs Frontend:

    Ermöglicht einem angemeldeten User, sich genau EINEN freien Platz
    auszusuchen. Falls bereits ein Platz reserviert wurde, wird dieser
    automatisch freigegeben.
    """
    try:
        data = json.loads(request.body)
        x = data.get('x')
        y = data.get('y')

        # 1. Prüfen, ob der User für das Event angemeldet ist
        registration = EventRegistration.objects.get(
            event_id=event_id, user=request.user
        )

        # 2. Ziel-Sitzplatz finden
        cell = SeatingCell.objects.get(plan__event_id=event_id, x=x, y=y)

        # 3. Bisherigen Sitzplatz des Users für dieses Event freigeben (sofern vorhanden)
        SeatingCell.objects.filter(
            plan__event_id=event_id, registration=registration
        ).update(
            registration=None,
            reservation_status=SeatingCell.ReservationStatus.FREE,
        )

        # 4. Neuen Platz über die Geschäftslogik reservieren
        success, message = cell.reserve_for_user(registration)

        if success:
            return JsonResponse({'status': 'success', 'message': message})
        else:
            return JsonResponse(
                {'status': 'error', 'message': message}, status=400
            )

    except EventRegistration.DoesNotExist:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Du bist für diese Veranstaltung nicht angemeldet.',
            },
            status=403,
        )
    except SeatingCell.DoesNotExist:
        return JsonResponse(
            {'status': 'error', 'message': 'Ungültiger Sitzplatz.'}, status=404
        )
    except Exception as e:
        return JsonResponse(
            {'status': 'error', 'message': str(e)}, status=500
        )


@login_required
@require_POST
def release_seat_api(request, event_id):
    """
    API fürs Frontend:
    Ermöglicht einem angemeldeten User, seinen aktuell reservierten Platz wieder freizugeben.
    """
    try:
        registration = EventRegistration.objects.get(
            event_id=event_id, user=request.user
        )

        # Finde den aktuellen Platz des Users für dieses Event
        cell = SeatingCell.objects.filter(
            plan__event_id=event_id, registration=registration
        ).first()

        if not cell:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'Du hast aktuell keinen Sitzplatz reserviert.',
                },
                status=400,
            )

        # Freigabe-Methode des Modells aufrufen
        success, message = cell.release_seat(registration=registration)

        if success:
            return JsonResponse({
                'status': 'success',
                'message': 'Sitzplatz erfolgreich freigegeben.',
            })
        else:
            return JsonResponse(
                {'status': 'error', 'message': message}, status=400
            )

    except EventRegistration.DoesNotExist:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Du bist für diese Veranstaltung nicht angemeldet.',
            },
            status=403,
        )
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@staff_member_required
@require_POST
def admin_assign_seat(request):
    try:
        data = json.loads(request.body)
        registration_id = data.get('registration_id')
        x = data.get('x')
        y = data.get('y')

        registration = EventRegistration.objects.get(pk=registration_id)
        plan = SeatingPlan.objects.get(event=registration.event)
        target_cell = SeatingCell.objects.get(plan=plan, x=x, y=y)

        # 1. Bisherigen Platz des Users freigeben
        SeatingCell.objects.filter(
            plan=plan, registration=registration
        ).update(
            registration=None,
            reservation_status=SeatingCell.ReservationStatus.FREE,
        )

        # 2. Neuen Platz zuweisen und Bezahlstatus sofort auswerten!
        has_paid = (
            registration.payment_status == EventRegistration.PaymentStatus.PAID
        )

        target_cell.registration = registration
        target_cell.reservation_status = (
            SeatingCell.ReservationStatus.RESERVED
            if has_paid
            else SeatingCell.ReservationStatus.PRE_RESERVED
        )
        target_cell.save()

        return JsonResponse(
            {'status': 'success', 'message': 'Platz erfolgreich zugewiesen!'}
        )

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@staff_member_required
@require_POST
def admin_toggle_block_seat(request):
    """
    API für Admins:
    Sperrt einen Platz ohne Anmeldung (Status BLOCKED) oder gibt ihn wieder frei (Status FREE).
    """
    try:
        data = json.loads(request.body)
        event_id = data.get('event_id')
        x = data.get('x')
        y = data.get('y')

        plan = SeatingPlan.objects.get(event_id=event_id)
        cell = SeatingCell.objects.get(plan=plan, x=x, y=y)

        if cell.cell_type != SeatingCell.CellType.SEAT:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'Nur Sitzplätze können gesperrt werden.',
                },
                status=400,
            )

        # Switchen zwischen BLOCKED und FREE
        if cell.reservation_status == SeatingCell.ReservationStatus.BLOCKED:
            cell.reservation_status = SeatingCell.ReservationStatus.FREE
            cell.registration = None
            message = f"Platz '{cell.seat_label or 'Pos (' + str(x) + ',' + str(y) + ')'}' wurde wieder FREIGEGEBEN."
        else:
            cell.reservation_status = SeatingCell.ReservationStatus.BLOCKED
            cell.registration = None  # Keine Anmeldung nötig
            message = f"Platz '{cell.seat_label or 'Pos (' + str(x) + ',' + str(y) + ')'}' wurde GESPERRT."

        cell.save()

        return JsonResponse({
            'status': 'success',
            'message': message,
            'new_status': cell.reservation_status,
        })

    except (SeatingPlan.DoesNotExist, SeatingCell.DoesNotExist):
        return JsonResponse(
            {'status': 'error', 'message': 'Sitzplatz nicht gefunden.'},
            status=404,
        )
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@staff_member_required
@require_POST
def admin_release_seat(request):
    """
    API für Admins:
    Gibt den Sitzplatz einer bestimmten Anmeldung frei ODER gibt eine Kachel per Koordinate frei.
    """
    try:
        data = json.loads(request.body)
        registration_id = data.get('registration_id')
        event_id = data.get('event_id')
        x = data.get('x')
        y = data.get('y')

        # Fall 1: Freigabe über Registration-ID
        if registration_id:
            registration = EventRegistration.objects.get(pk=registration_id)
            seats = SeatingCell.objects.filter(registration=registration)
            for seat in seats:
                seat.registration = None
                seat.reservation_status = SeatingCell.ReservationStatus.FREE
                seat.save()
            return JsonResponse({
                'status': 'success',
                'message': 'Sitzplatzzuweisung erfolgreich aufgehoben.',
            })

        # Fall 2: Freigabe über Event-ID & Koordinaten
        elif event_id and x is not None and y is not None:
            plan = SeatingPlan.objects.get(event_id=event_id)
            cell = SeatingCell.objects.get(plan=plan, x=x, y=y)
            cell.registration = None
            cell.reservation_status = SeatingCell.ReservationStatus.FREE
            cell.save()
            return JsonResponse({
                'status': 'success',
                'message': f'Platz {cell.seat_label or "Pos (" + str(x) + "," + str(y) + ")"} wurde freigegeben.',
            })

        return JsonResponse(
            {'status': 'error', 'message': 'Ungültige Parameter.'}, status=400
        )

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
