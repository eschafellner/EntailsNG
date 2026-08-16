import json
import logging
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from events.models import Event, EventRegistration
from configuration.cache import invalidate_event_capacity_cache
from .models import SeatingCell, SeatingPlan

logger = logging.getLogger(__name__)



def seating_plan_view(request):
    """Rendert die öffentliche Sitzplanseite für das aktive Event."""
    event = Event.objects.get_active()
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
    """Speichert das geänderte Raster per AJAX-Call mit atomarer Transaktionssicherheit, Eingabevalidierung und Schutz belegter Plätze."""
    plan = get_object_or_404(SeatingPlan, pk=plan_id)

    try:
        data = json.loads(request.body)
        cells_to_save = data.get('cells', [])
        if not isinstance(cells_to_save, list):
            return JsonResponse({'status': 'error', 'message': 'Ungültiges Datenformat: "cells" muss eine Liste sein.'}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Ungültiges JSON übermittelt.'}, status=400)

    VALID_CELL_TYPES = set(SeatingCell.CellType.values)
    sent_coords = {}

    for idx, c in enumerate(cells_to_save):
        if not isinstance(c, dict):
            return JsonResponse({'status': 'error', 'message': f'Ungültiger Kacheleintrag an Index {idx}.'}, status=400)

        # 1. Koordinaten validieren
        try:
            x = int(c.get('x'))
            y = int(c.get('y'))
        except (ValueError, TypeError):
            return JsonResponse({'status': 'error', 'message': f'Ungültige Koordinaten an Index {idx}.'}, status=400)

        if not (1 <= x <= plan.columns and 1 <= y <= plan.rows):
            return JsonResponse(
                {'status': 'error', 'message': f'Koordinaten ({x},{y}) liegen außerhalb des Rasters ({plan.columns}x{plan.rows}).'},
                status=400
            )

        # 2. Zelltyp validieren
        cell_type = c.get('cell_type', SeatingCell.CellType.EMPTY)
        if cell_type not in VALID_CELL_TYPES:
            return JsonResponse(
                {'status': 'error', 'message': f'Ungültiger Zelltyp "{cell_type}" an Position ({x},{y}).'},
                status=400
            )

        # 3. Feldlängen validieren
        seat_label = str(c.get('seat_label', '') or '')[:20]
        text_label = str(c.get('text_label', '') or '')[:50]

        sent_coords[(x, y)] = {
            'cell_type': cell_type,
            'seat_label': seat_label,
            'text_label': text_label,
        }

    try:
        with transaction.atomic():
            existing_cells = {
                (cell.x, cell.y): cell 
                for cell in SeatingCell.objects.filter(plan=plan).select_related('registration__user')
            }

            # 4. Schutz belegter / reservierter Plätze vor Löschung
            coords_to_delete = set(existing_cells.keys()) - set(sent_coords.keys())
            for coord in coords_to_delete:
                cell = existing_cells[coord]
                if cell.registration is not None or cell.reservation_status in [
                    SeatingCell.ReservationStatus.RESERVED,
                    SeatingCell.ReservationStatus.PRE_RESERVED
                ]:
                    user_name = cell.registration.user.username if cell.registration else "einem Teilnehmer"
                    return JsonResponse(
                        {
                            'status': 'error',
                            'message': f'Kachel an Position ({coord[0]},{coord[1]}) kann nicht gelöscht werden, da sie aktuell von {user_name} belegt/reserviert ist.',
                        },
                        status=400,
                    )

            if coords_to_delete:
                pks_to_delete = [existing_cells[coord].pk for coord in coords_to_delete]
                SeatingCell.objects.filter(pk__in=pks_to_delete).delete()

            cells_to_create = []
            cells_to_update = []

            # 5. Bestehende Kacheln updaten oder neue zur Bulk-Erstellung sammeln
            for coord, cdata in sent_coords.items():
                x, y = coord
                cell_type = cdata['cell_type']
                seat_label = cdata['seat_label']
                text_label = cdata['text_label']

                if coord in existing_cells:
                    cell = existing_cells[coord]

                    # Schutz vor destruktiver Typ-Änderung belegter Plätze
                    if cell.registration is not None and cell_type != SeatingCell.CellType.SEAT:
                        user_name = cell.registration.user.username
                        return JsonResponse(
                            {
                                'status': 'error',
                                'message': f'Sitzplatz ({x},{y}) kann nicht in "{cell_type}" umgewandelt werden, da er von {user_name} belegt ist.',
                            },
                            status=400,
                        )

                    if (cell.cell_type != cell_type or 
                        cell.seat_label != seat_label or 
                        cell.text_label != text_label):
                        cell.cell_type = cell_type
                        cell.seat_label = seat_label
                        cell.text_label = text_label
                        cells_to_update.append(cell)
                else:
                    cells_to_create.append(
                        SeatingCell(
                            plan=plan,
                            x=x,
                            y=y,
                            cell_type=cell_type,
                            seat_label=seat_label,
                            text_label=text_label,
                        )
                    )

            if cells_to_create:
                SeatingCell.objects.bulk_create(cells_to_create, batch_size=500)
            if cells_to_update:
                SeatingCell.objects.bulk_update(
                    cells_to_update,
                    fields=['cell_type', 'seat_label', 'text_label'],
                    batch_size=500
                )

            # Einmalige Cache-Invalidierung nach DB-Commit
            if plan.event_id:
                invalidate_event_capacity_cache(plan.event_id)

        return JsonResponse(
            {'status': 'success', 'message': 'Sitzplan erfolgreich gespeichert!'}
        )

    except Exception as e:
        logger.error("Interner Fehler beim Speichern des Sitzplans (ID: %s): %s", plan_id, e, exc_info=True)
        return JsonResponse({'status': 'error', 'message': 'Beim Speichern des Sitzplans ist ein interner Fehler aufgetreten.'}, status=500)




def get_event_seating_api(request, event_id):
    """
    Liefert den Sitzplan einer Veranstaltung inkl. Belegung, dynamischem Bezahlstatus & Check-in-Status als JSON.
    Datenschutz / DSGVO:
    Personenbezogene Daten (Benutzername, Clan-Name, Check-in-Status) werden NUR an eingeloggte Benutzer ausgeliefert.
    Nicht eingeloggte Besucher sehen ausschließlich den aggregierten Status (FREE, PRE_RESERVED, RESERVED, BLOCKED).
    """
    try:
        plan = SeatingPlan.objects.get(event_id=event_id)
    except SeatingPlan.DoesNotExist:
        return JsonResponse(
            {'error': 'Kein Sitzplan für diese Veranstaltung vorhanden.'},
            status=404,
        )

    is_authenticated = request.user.is_authenticated
    user_clan_map = {}
    current_user_clan_name = None

    cells_qs = plan.cells.select_related('registration__user').all()

    if is_authenticated:
        from clans.models import ClanMembership
        # Performance: Nur User-IDs sammeln, die tatsächlich auf diesem Saalplan platziert sind + aktueller User
        seated_user_ids = {
            c.registration.user_id
            for c in cells_qs
            if c.registration and c.registration.user_id
        }
        seated_user_ids.add(request.user.id)

        if seated_user_ids:
            active_memberships = ClanMembership.objects.filter(
                user_id__in=seated_user_ids,
                status=ClanMembership.Status.ACCEPTED
            ).values('user_id', 'clan__name')

            for m in active_memberships:
                user_clan_map[m['user_id']] = m['clan__name']

        current_user_clan_name = user_clan_map.get(request.user.id)

    cells = []
    for c in cells_qs:
        username = None
        clan_name = None
        is_checked_in = False

        # Dynamische Statusbestimmung für das Frontend:
        if c.reservation_status == SeatingCell.ReservationStatus.BLOCKED:
            computed_status = 'BLOCKED'
        elif c.registration and c.registration.event_id == plan.event_id:
            if is_authenticated:
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
@transaction.atomic
def reserve_seat_api(request, event_id):
    """API fürs Frontend:

    Ermöglicht einem angemeldeten User, sich genau EINEN freien Platz
    auszusuchen. Falls bereits ein Platz reserviert wurde, wird dieser
    automatisch freigegeben. Transaktionssicher mit DB-Locks.
    """
    try:
        data = json.loads(request.body)
        x = data.get('x')
        y = data.get('y')

        # 1. Prüfen, ob der User für das Event angemeldet ist
        registration = EventRegistration.objects.get(
            event_id=event_id, user=request.user
        )

        # 2. Ziel-Sitzplatz mit DB-Lock holen (select_for_update)
        cell = SeatingCell.objects.select_for_update().get(
            plan__event_id=event_id, x=x, y=y
        )

        # 3. Vorab-Prüfung: Ist der Zielplatz überhaupt reservierbar? (Pre-Check vor Freigabe des Altsitzes)
        can_res, err_msg = cell.can_reserve_for_user(registration)
        if not can_res:
            transaction.set_rollback(True)
            return JsonResponse({'status': 'error', 'message': err_msg}, status=400)

        # 4. Bisherige Sitzplätze des Users mit DB-Lock freigeben
        previous_seats = list(
            SeatingCell.objects.select_for_update().filter(
                plan__event_id=event_id, registration=registration
            )
        )
        for prev in previous_seats:
            if prev.pk != cell.pk:
                prev.registration = None
                prev.reservation_status = SeatingCell.ReservationStatus.FREE
                prev.save(update_fields=['registration', 'reservation_status'])

        # 5. Neuen Platz über die Geschäftslogik reservieren
        success, message = cell.reserve_for_user(registration)

        if success:
            return JsonResponse({'status': 'success', 'message': message})
        else:
            transaction.set_rollback(True)
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
        logger.exception("Fehler in reserve_seat_api: %s", e)
        return JsonResponse(
            {'status': 'error', 'message': 'Die Aktion konnte nicht ausgeführt werden. Bitte versuche es erneut.'},
            status=500,
        )


@login_required
@require_POST
@transaction.atomic
def release_seat_api(request, event_id):
    """
    API fürs Frontend:
    Ermöglicht einem angemeldeten User, seinen aktuell reservierten Platz wieder freizugeben.
    """
    try:
        registration = EventRegistration.objects.get(
            event_id=event_id, user=request.user
        )

        # Finde den aktuellen Platz des Users mit DB-Lock
        cell = SeatingCell.objects.select_for_update().filter(
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
        logger.exception("Fehler in release_seat_api: %s", e)
        return JsonResponse(
            {'status': 'error', 'message': 'Die Freigabe konnte nicht durchgeführt werden. Bitte versuche es erneut.'},
            status=500,
        )




@staff_member_required
@require_POST
@transaction.atomic
def admin_assign_seat(request):
    """
    API für Admins:
    Weist einem Benutzer gezielt einen Sitzplatz zu mit strikter Validierung von Zelltyp, Sperrstatus und Belegung.
    """
    try:
        data = json.loads(request.body)
        registration_id = data.get('registration_id')
        x = data.get('x')
        y = data.get('y')
        force = bool(data.get('force', False))

        if registration_id is None or x is None or y is None:
            return JsonResponse(
                {'status': 'error', 'message': 'Unvollständige Parameter übergeben.'},
                status=400,
            )

        registration = EventRegistration.objects.select_related('event', 'user').get(pk=registration_id)
        plan = SeatingPlan.objects.get(event=registration.event)

        # 1. Zielzelle mit DB-Lock laden
        target_cell = SeatingCell.objects.select_for_update().filter(plan=plan, x=int(x), y=int(y)).first()
        if not target_cell:
            return JsonResponse(
                {'status': 'error', 'message': 'Ziel-Kachel existiert nicht auf diesem Sitzplan.'},
                status=404,
            )

        # 2. Prüfen, ob die Zielkachel überhaupt ein Sitzplatz ist
        if target_cell.cell_type != SeatingCell.CellType.SEAT:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': f'Zuweisung fehlgeschlagen: Die gewählte Kachel ist kein Sitzplatz (Typ: {target_cell.get_cell_type_display()}).',
                },
                status=400,
            )

        # 3. Prüfen, ob der Platz gesperrt ist
        if target_cell.reservation_status == SeatingCell.ReservationStatus.BLOCKED and not force:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': f"Platz '{target_cell.seat_label or f'Pos ({x},{y})'}' ist gesperrt (Status: Blockiert).",
                },
                status=400,
            )

        # 4. Prüfen, ob der Platz bereits von einem anderen Gast belegt ist
        if target_cell.registration and target_cell.registration != registration and not force:
            occupied_username = target_cell.registration.user.username
            return JsonResponse(
                {
                    'status': 'error',
                    'message': f"Platz '{target_cell.seat_label or f'Pos ({x},{y})'}' ist bereits von '{occupied_username}' belegt.",
                },
                status=400,
            )

        # 5. Bisherigen Platz des Users freigeben (falls vorhanden)
        SeatingCell.objects.select_for_update().filter(
            plan=plan, registration=registration
        ).update(
            registration=None,
            reservation_status=SeatingCell.ReservationStatus.FREE,
        )

        # 6. Neuen Platz zuweisen und Bezahlstatus korrekt auswerten
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

        # Cache-Invalidierung für Kapazitätsanzeige
        invalidate_event_capacity_cache(registration.event_id)

        return JsonResponse(
            {'status': 'success', 'message': f"Platz '{target_cell.seat_label or f'Pos ({x},{y})'}' erfolgreich an {registration.user.username} zugewiesen!"}
        )

    except EventRegistration.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Anmeldung nicht gefunden.'}, status=404)
    except SeatingPlan.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Kein Sitzplan für diese Veranstaltung vorhanden.'}, status=404)
    except Exception as e:
        logger.exception("Fehler in admin_assign_seat: %s", e)
        return JsonResponse({'status': 'error', 'message': 'Die Zuweisung konnte nicht gespeichert werden. Bitte versuche es erneut.'}, status=500)



@staff_member_required
@require_POST
@transaction.atomic
def admin_toggle_block_seat(request):
    """
    API für Admins:
    Sperrt einen Platz ohne Anmeldung (Status BLOCKED) oder gibt ihn wieder frei (Status FREE).
    Transaktionssicher mit DB-Row-Lock.
    """
    try:
        data = json.loads(request.body)
        event_id = data.get('event_id')
        x = data.get('x')
        y = data.get('y')

        plan = SeatingPlan.objects.get(event_id=event_id)
        cell = SeatingCell.objects.select_for_update().get(plan=plan, x=x, y=y)

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
            message = f"Platz '{cell.seat_label or f'Pos ({x},{y})'}' wurde wieder FREIGEGEBEN."
        else:
            cell.reservation_status = SeatingCell.ReservationStatus.BLOCKED
            cell.registration = None  # Keine Anmeldung nötig
            message = f"Platz '{cell.seat_label or f'Pos ({x},{y})'}' wurde GESPERRT."

        cell.save(update_fields=['reservation_status', 'registration'])

        invalidate_event_capacity_cache(event_id)

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
        logger.exception("Fehler in admin_toggle_block_seat: %s", e)
        return JsonResponse({'status': 'error', 'message': 'Der Sperrstatus konnte nicht geändert werden. Bitte versuche es erneut.'}, status=500)


@staff_member_required
@require_POST
@transaction.atomic
def admin_release_seat(request):
    """
    API für Admins:
    Gibt den Sitzplatz einer bestimmten Anmeldung frei ODER gibt eine Kachel per Koordinate frei.
    Transaktionssicher mit DB-Row-Lock.
    """
    try:
        data = json.loads(request.body)
        registration_id = data.get('registration_id')
        event_id = data.get('event_id')
        x = data.get('x')
        y = data.get('y')

        # Fall 1: Freigabe über Registration-ID
        if registration_id:
            registration = EventRegistration.objects.select_related('event').get(pk=registration_id)
            seats = list(SeatingCell.objects.select_for_update().filter(registration=registration))
            for seat in seats:
                seat.registration = None
                seat.reservation_status = SeatingCell.ReservationStatus.FREE
                seat.save(update_fields=['registration', 'reservation_status'])
            invalidate_event_capacity_cache(registration.event_id)
            return JsonResponse({
                'status': 'success',
                'message': 'Sitzplatzzuweisung erfolgreich aufgehoben.',
            })

        # Fall 2: Freigabe über Event-ID & Koordinaten
        elif event_id and x is not None and y is not None:
            plan = SeatingPlan.objects.get(event_id=event_id)
            cell = SeatingCell.objects.select_for_update().get(plan=plan, x=x, y=y)
            cell.registration = None
            cell.reservation_status = SeatingCell.ReservationStatus.FREE
            cell.save(update_fields=['registration', 'reservation_status'])
            invalidate_event_capacity_cache(event_id)
            return JsonResponse({
                'status': 'success',
                'message': f'Platz {cell.seat_label or f"Pos ({x},{y})"} wurde freigegeben.',
            })

        return JsonResponse(
            {'status': 'error', 'message': 'Ungültige Parameter.'}, status=400
        )

    except Exception as e:
        logger.exception("Fehler in admin_release_seat: %s", e)
        return JsonResponse({'status': 'error', 'message': 'Die Freigabe konnte nicht durchgeführt werden. Bitte versuche es erneut.'}, status=500)



