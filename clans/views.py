from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.db import transaction
from django.db.models import Count, IntegerField, Q, Value
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from configuration.translations import get_translation
from events.models import Event, EventRegistration
from seating.services import get_user_seat_map
from seating.clan_services import selection_status
from .forms import ClanForm, ClanJoinPasswordForm
from .models import Clan, ClanMembership
from .services import ClanManagementError, leave_clan, locked_management, manage_member, manage_request
from .texts import TEXTS


def clan_list_view(request):
    """
    Übersicht aller Clans (veranstaltungsübergreifend).
    Zeigt für jeden Clan die Mitgliederanzahl sowie optional die Anzahl der für das aktive Event angemeldeten Mitglieder.
    """
    active_event = Event.objects.get_active()
    user_membership = (
        ClanMembership.get_user_active_membership(request.user)
        if request.user.is_authenticated
        else None
    )

    annotations = {
        'total_members': Count(
            'memberships',
            filter=Q(memberships__status=ClanMembership.Status.ACCEPTED),
            distinct=True,
        ),
    }

    if active_event:
        annotations['event_registered_members'] = Count(
            'memberships__user__registrations',
            filter=Q(
                memberships__status=ClanMembership.Status.ACCEPTED,
                memberships__user__registrations__event=active_event,
                memberships__user__registrations__cancelled_at__isnull=True,
            ) & ~Q(memberships__user__registrations__payment_status=EventRegistration.PaymentStatus.CANCELLED),
            distinct=True,
        )
    else:
        annotations['event_registered_members'] = Value(0, output_field=IntegerField())

    clans_qs = Clan.objects.annotate(**annotations).order_by('name')

    paginator = Paginator(clans_qs, 24)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    clan_data = [
        {
            'clan': clan,
            'total_members': clan.total_members,
            'event_registered_members': clan.event_registered_members,
        }
        for clan in page_obj
    ]

    context = {
        'clan_data': clan_data,
        'page_obj': page_obj,
        'active_event': active_event,
        'user_membership': user_membership,
    }
    return render(request, 'clans/clan_list.html', context)



def clan_detail_view(request, slug):
    """
    Zeigt die Profilseite eines Clans inkl. Mitgliederliste, Sitzplätzen 
    und Admin-Steuerelementen.
    """
    clan = get_object_or_404(Clan, slug=slug)
    user_membership = (
        ClanMembership.get_user_active_membership(request.user)
        if request.user.is_authenticated
        else None
    )
    current_clan_membership = (
        clan.get_user_membership(request.user)
        if request.user.is_authenticated
        else None
    )
    is_clan_admin = clan.is_admin(request.user)
    from seating.models import ClanSeatPayment
    payment_history = ClanSeatPayment.objects.filter(allocation__clan=clan).select_related('allocation__event').order_by('-created_at') if is_clan_admin else []

    accepted_memberships = list(clan.get_accepted_memberships())
    clan_admins = [m for m in accepted_memberships if m.role == ClanMembership.Role.ADMIN
                   and m.user.is_active and m.user.deleted_at is None]
    admin_count = len(clan_admins)
    pending_memberships = (
        list(clan.get_pending_memberships()) if is_clan_admin else []
    )

    # Sitzplätze aller Mitglieder beim aktiven Event via Domain Service abfragen (N+1 Vermeidung)
    active_event = Event.objects.get_active()
    user_seat_map = {}
    if active_event and accepted_memberships:
        member_user_ids = [m.user_id for m in accepted_memberships]
        user_seat_map = get_user_seat_map(active_event, member_user_ids)

    members_with_seats = [
        {
            'membership': m,
            'user': m.user,
            'seat_label': user_seat_map.get(m.user_id),
            'can_promote': m.role != ClanMembership.Role.ADMIN and m.user.is_active and m.user.deleted_at is None,
            'can_demote': m.role == ClanMembership.Role.ADMIN and (
                admin_count > 1 or not m.user.is_active or m.user.deleted_at is not None
            ),
        }
        for m in accepted_memberships
    ]


    join_form = ClanJoinPasswordForm()

    context = {
        'clan': clan,
        'user_membership': user_membership,
        'current_clan_membership': current_clan_membership,
        'is_clan_admin': is_clan_admin,
        'clan_seats_available': bool(is_clan_admin and active_event and selection_status(clan, active_event)['enabled']),
        'clan_payment_available': bool(is_clan_admin and (active_event or payment_history)),
        'clan_payment_history': payment_history,
        'clan_admins': clan_admins,
        'admin_count': admin_count,
        'is_last_member': len(accepted_memberships) <= 1,
        'members_with_seats': members_with_seats,
        'pending_memberships': pending_memberships,
        'join_form': join_form,
    }
    return render(request, 'clans/clan_detail.html', context)




@login_required
def clan_create_view(request):
    """Erstellt einen neuen Clan und macht den Ersteller zum Clan-Admin."""
    existing_membership = ClanMembership.get_user_active_membership(request.user)
    if existing_membership:
        messages.warning(
            request,
            f'Du bist bereits Mitglied im Clan "{existing_membership.clan.name}". '
            'Du musst deinen aktuellen Clan zuerst verlassen, um einen neuen zu erstellen.',
        )
        return redirect('clan_detail', slug=existing_membership.clan.slug)

    if request.method == 'POST':
        form = ClanForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                clan = form.save()
                ClanMembership.objects.create(
                    user=request.user,
                    clan=clan,
                    role=ClanMembership.Role.ADMIN,
                    status=ClanMembership.Status.ACCEPTED,
                )
            messages.success(
                request, f'Der Clan "{clan.name}" wurde erfolgreich erstellt!'
            )
            return redirect('clan_detail', slug=clan.slug)
    else:
        form = ClanForm()

    return render(request, 'clans/clan_form.html', {'form': form, 'title': 'Neuen Clan erstellen'})


@login_required
def clan_edit_view(request, slug):
    """Ermöglicht Clan-Admins das Bearbeiten von Clanname, Website, Logo und Passwort."""
    clan = get_object_or_404(Clan, slug=slug)
    if not clan.is_admin(request.user):
        messages.error(
            request,
            get_translation(
                'msg_clan_admin_only_edit',
                'Nur Clan-Admins können den Clan bearbeiten.',
            ),
        )
        return redirect('clan_detail', slug=clan.slug)

    if request.method == 'POST':
        form = ClanForm(request.POST, request.FILES, instance=clan)
        if form.is_valid():
            try:
                with locked_management(clan.pk, request.user.pk):
                    form.save()
            except Clan.DoesNotExist as exc:
                raise Http404 from exc
            except ClanManagementError as exc:
                messages.error(request, str(exc))
                return redirect('clan_detail', slug=clan.slug)
            messages.success(
                request,
                get_translation(
                    'msg_clan_updated',
                    'Clan-Daten wurden erfolgreich aktualisiert.',
                ),
            )
            return redirect('clan_detail', slug=clan.slug)
    else:
        form = ClanForm(instance=clan)

    return render(
        request,
        'clans/clan_form.html',
        {'form': form, 'clan': clan, 'title': f'Clan "{clan.name}" bearbeiten'},
    )


@login_required
@require_POST
def clan_join_password_view(request, slug):
    """Ermöglicht den sofortigen Clanbeitritt mittels Clan-Passwort."""
    clan = get_object_or_404(Clan, slug=slug)
    existing_membership = ClanMembership.get_user_active_membership(request.user)

    if existing_membership:
        messages.error(
            request,
            get_translation(
                'msg_clan_already_member',
                'Du bist bereits Mitglied im Clan "{clan_name}".',
                clan_name=existing_membership.clan.name,
            ),
        )
        return redirect('clan_detail', slug=clan.slug)

    form = ClanJoinPasswordForm(request.POST)
    if form.is_valid():
        entered_password = form.cleaned_data.get('password')
        if clan.check_password(entered_password):
            with transaction.atomic():
                # Bestehende ausstehende Anfragen löschen/überschreiben
                ClanMembership.objects.filter(user=request.user, clan=clan).delete()
                ClanMembership.objects.create(
                    user=request.user,
                    clan=clan,
                    role=ClanMembership.Role.MEMBER,
                    status=ClanMembership.Status.ACCEPTED,
                )
            messages.success(
                request,
                get_translation(
                    'msg_clan_joined',
                    'Du bist dem Clan "{clan_name}" beigetreten!',
                    clan_name=clan.name,
                ),
            )
        else:
            messages.error(
                request,
                get_translation(
                    'msg_clan_password_incorrect',
                    'Das eingegebene Clan-Passwort ist falsch.',
                ),
            )

    return redirect('clan_detail', slug=clan.slug)



@login_required
@require_POST
def clan_request_join_view(request, slug):
    """Stellt eine Beitrittsanfrage an den Clan-Admin."""
    clan = get_object_or_404(Clan, slug=slug)
    existing_membership = ClanMembership.get_user_active_membership(request.user)

    if existing_membership:
        messages.error(
            request,
            f'Du bist bereits Mitglied im Clan "{existing_membership.clan.name}".',
        )
        return redirect('clan_detail', slug=clan.slug)

    membership, created = ClanMembership.objects.get_or_create(
        user=request.user,
        clan=clan,
        defaults={
            'role': ClanMembership.Role.MEMBER,
            'status': ClanMembership.Status.PENDING,
        },
    )

    if created:
        messages.info(
            request,
            f'Deine Beitrittsanfrage an den Clan "{clan.name}" wurde gesendet.',
        )
    else:
        messages.warning(
            request, 'Du hast bereits eine Beitrittsanfrage an diesen Clan gesendet.'
        )

    return redirect('clan_detail', slug=clan.slug)


@login_required
@require_POST
def clan_manage_request_view(request, slug, membership_id):
    """Verarbeitet ausschließlich noch offene Beitrittsanfragen."""
    clan = get_object_or_404(Clan, slug=slug)
    action = request.POST.get('action')
    try:
        username, other_clan = manage_request(clan.pk, request.user.pk, membership_id, action)
    except (Clan.DoesNotExist, ClanMembership.DoesNotExist) as exc:
        raise Http404 from exc
    except ClanManagementError as exc:
        messages.error(request, str(exc))
    else:
        if other_clan:
            messages.error(request, f'{username} ist in der Zwischenzeit bereits dem Clan "{other_clan}" beigetreten.')
        elif action == 'accept':
            messages.success(request, f'{username} wurde als Clan-Mitglied akzeptiert.')
        else:
            messages.info(request, get_translation(
                'msg_clan_request_rejected', 'Beitrittsanfrage von {username} abgelehnt.', username=username,
            ))
    return redirect('clan_detail', slug=clan.slug)


@login_required
@require_POST
def clan_manage_member_view(request, slug, membership_id):
    """Gleichberechtigte Admins verwalten bestätigte Mitglieder und Adminrollen."""
    clan = get_object_or_404(Clan, slug=slug)
    action = request.POST.get('action')
    try:
        if action in {'promote', 'demote'} and request.POST.get('confirmed') != '1':
            raise ClanManagementError('msg_clan_role_confirmation')
        username = manage_member(clan.pk, request.user.pk, membership_id, action)
    except (Clan.DoesNotExist, ClanMembership.DoesNotExist) as exc:
        raise Http404 from exc
    except ClanManagementError as exc:
        messages.error(request, str(exc))
    else:
        if action == 'kick':
            messages.info(request, get_translation(
                'msg_clan_member_removed', '{username} wurde aus dem Clan "{clan_name}" entfernt.',
                username=username, clan_name=clan.name,
            ))
        else:
            key = 'msg_clan_role_promoted' if action == 'promote' else 'msg_clan_role_demoted'
            messages.success(request, get_translation(key, TEXTS[key], username=username))
    return redirect('clan_detail', slug=clan.slug)


@login_required
@require_POST
def clan_leave_view(request, slug):
    """Clan-Austritt mit atomarer Auflösung beziehungsweise Admin-Nachfolge."""
    clan = get_object_or_404(Clan, slug=slug)
    try:
        dissolved, successor = leave_clan(clan.pk, request.user.pk)
    except Clan.DoesNotExist as exc:
        raise Http404 from exc
    except ClanManagementError as exc:
        messages.error(request, str(exc))
        return redirect('clan_detail', slug=clan.slug)
    if dissolved:
        messages.warning(request,
            f'Du hast den Clan verlassen. Da du das letzte Mitglied warst, wurde der Clan "{clan.name}" aufgelöst und gelöscht.')
    elif successor:
        messages.info(request, f'Du hast den Clan verlassen. {successor} wurde als neuer Clan-Admin bestimmt.')
    else:
        messages.info(request, get_translation(
            'msg_clan_left', 'Du hast den Clan "{clan_name}" erfolgreich verlassen.', clan_name=clan.name,
        ))
    return redirect('clan_list')
