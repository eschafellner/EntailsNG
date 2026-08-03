from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from events.models import Event, EventRegistration
from seating.models import SeatingCell
from .forms import ClanForm, ClanJoinPasswordForm
from .models import Clan, ClanMembership


def clan_list_view(request):
    """
    Übersicht aller Clans, die bei der aktuellen Veranstaltung mindestens 
    ein angemeldetes Mitglied haben (oder alle Clans, falls kein Event aktiv ist).
    """
    active_event = Event.objects.filter(is_active=True).first()
    user_membership = (
        ClanMembership.get_user_active_membership(request.user)
        if request.user.is_authenticated
        else None
    )

    if active_event:
        # Filter: Nur Clans, deren akzeptierte Mitglieder für das aktive Event angemeldet sind
        clans = Clan.objects.filter(
            memberships__status=ClanMembership.Status.ACCEPTED,
            memberships__user__registrations__event=active_event,
        ).distinct()
    else:
        clans = Clan.objects.all()

    context = {
        'clans': clans,
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

    accepted_memberships = clan.get_accepted_memberships()
    pending_memberships = (
        clan.get_pending_memberships() if is_clan_admin else []
    )

    # Sitzplätze der Mitglieder beim aktiven Event ermitteln
    active_event = Event.objects.filter(is_active=True).first()
    members_with_seats = []
    for m in accepted_memberships:
        seat_label = None
        if active_event:
            cell = SeatingCell.objects.filter(
                plan__event=active_event, registration__user=m.user
            ).first()
            if cell:
                seat_label = cell.seat_label or f"Pos ({cell.x},{cell.y})"

        members_with_seats.append({
            'membership': m,
            'user': m.user,
            'seat_label': seat_label,
        })

    join_form = ClanJoinPasswordForm()

    context = {
        'clan': clan,
        'user_membership': user_membership,
        'current_clan_membership': current_clan_membership,
        'is_clan_admin': is_clan_admin,
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
        messages.error(request, 'Nur Clan-Admins können den Clan bearbeiten.')
        return redirect('clan_detail', slug=clan.slug)

    if request.method == 'POST':
        form = ClanForm(request.POST, request.FILES, instance=clan)
        if form.is_valid():
            form.save()
            messages.success(request, 'Clan-Daten wurden erfolgreich aktualisiert.')
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
            f'Du bist bereits Mitglied im Clan "{existing_membership.clan.name}".',
        )
        return redirect('clan_detail', slug=clan.slug)

    form = ClanJoinPasswordForm(request.POST)
    if form.is_valid():
        entered_password = form.cleaned_data.get('password')
        if entered_password == clan.password:
            # Bestehende ausstehende Anfragen löschen/überschreiben
            ClanMembership.objects.filter(user=request.user, clan=clan).delete()
            ClanMembership.objects.create(
                user=request.user,
                clan=clan,
                role=ClanMembership.Role.MEMBER,
                status=ClanMembership.Status.ACCEPTED,
            )
            messages.success(request, f'Du bist dem Clan "{clan.name}" beigetreten!')
        else:
            messages.error(request, 'Das eingegebene Clan-Passwort ist falsch.')

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
    """Verarbeitet Beitrittsanfragen (Akzeptieren oder Ablehnen) durch einen Clan-Admin."""
    clan = get_object_or_404(Clan, slug=slug)
    if not clan.is_admin(request.user):
        messages.error(request, 'Keine Berechtigung.')
        return redirect('clan_detail', slug=clan.slug)

    membership = get_object_or_404(ClanMembership, pk=membership_id, clan=clan)
    action = request.POST.get('action')

    if action == 'accept':
        # Prüfen ob der Bewerber in der Zwischenzeit in einem anderen Clan akzeptiert wurde
        other_active = ClanMembership.get_user_active_membership(membership.user)
        if other_active:
            messages.error(
                request,
                f'{membership.user.username} ist in der Zwischenzeit bereits dem Clan "{other_active.clan.name}" beigetreten.',
            )
            membership.delete()
        else:
            membership.status = ClanMembership.Status.ACCEPTED
            membership.save()
            messages.success(
                request,
                f'{membership.user.username} wurde als Clan-Mitglied akzeptiert.',
            )

    elif action == 'reject':
        username = membership.user.username
        membership.delete()
        messages.info(request, f'Beitrittsanfrage von {username} abgelehnt.')

    return redirect('clan_detail', slug=clan.slug)


@login_required
@require_POST
def clan_manage_member_view(request, slug, membership_id):
    """Ermöglicht Clan-Admins das Befördern von Mitgliedern oder Entfernen (Kick)."""
    clan = get_object_or_404(Clan, slug=slug)
    if not clan.is_admin(request.user):
        messages.error(request, 'Keine Berechtigung.')
        return redirect('clan_detail', slug=clan.slug)

    membership = get_object_or_404(ClanMembership, pk=membership_id, clan=clan)
    action = request.POST.get('action')

    if action == 'promote':
        membership.role = ClanMembership.Role.ADMIN
        membership.save()
        messages.success(
            request, f'{membership.user.username} wurde zum Clan-Admin befördert.'
        )

    elif action == 'kick':
        if membership.user == request.user:
            messages.error(
                request,
                'Du kannst dich nicht selbst entfernen. Nutze "Clan verlassen".',
            )
        else:
            username = membership.user.username
            membership.delete()
            messages.info(request, f'{username} wurde aus dem Clan entfernt.')

    return redirect('clan_detail', slug=clan.slug)


@login_required
@require_POST
def clan_leave_view(request, slug):
    """
    User verlässt den Clan.
    Verlässt der letzte Clan-Admin den Clan, springt die Admin-Rolle automatisch 
    auf das nächste älteste akzeptierte Mitglied um.
    """
    clan = get_object_or_404(Clan, slug=slug)
    membership = ClanMembership.objects.filter(
        user=request.user, clan=clan, status=ClanMembership.Status.ACCEPTED
    ).first()

    if not membership:
        messages.error(request, 'Du bist kein aktives Mitglied dieses Clans.')
        return redirect('clan_detail', slug=clan.slug)

    was_admin = (membership.role == ClanMembership.Role.ADMIN)

    with transaction.atomic():
        membership.delete()

        if was_admin:
            # Prüfen ob noch ein anderer Admin existiert
            remaining_admins = clan.memberships.filter(
                role=ClanMembership.Role.ADMIN,
                status=ClanMembership.Status.ACCEPTED,
            ).exists()

            if not remaining_admins:
                # Befördere das dienstälteste verbleibende Mitglied zum Admin
                next_member = (
                    clan.memberships.filter(status=ClanMembership.Status.ACCEPTED)
                    .order_by('created_at')
                    .first()
                )
                if next_member:
                    next_member.role = ClanMembership.Role.ADMIN
                    next_member.save()
                    messages.info(
                        request,
                        f'Du hast den Clan verlassen. {next_member.user.username} wurde als neuer Clan-Admin bestimmt.',
                    )
                else:
                    messages.info(
                        request,
                        'Du hast den Clan verlassen. Es sind keine weiteren Mitglieder im Clan verblieben.',
                    )
            else:
                messages.info(request, 'Du hast den Clan erfolgreich verlassen.')
        else:
            messages.info(request, 'Du hast den Clan erfolgreich verlassen.')

    return redirect('clan_list')
