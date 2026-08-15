from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from events.models import Event, EventRegistration

from tournaments.models import (
    Game, Team, TeamMember, Tournament, TournamentMatch, TournamentRegistration, generate_invite_code
)

from tournaments.services import (
    advance_match_winner, check_user_event_checkin, generate_bracket, get_or_create_solo_team
)


# =============================================================================
# TURNIERE VIEWS
# =============================================================================

def tournament_list(request):
    """
    Übersichtsseite aller Turniere für die aktive Hauptveranstaltung.
    """
    active_event = Event.objects.filter(is_active=True).first()
    tournaments = Tournament.objects.filter(event=active_event).select_related('game', 'event') if active_event else []

    user_checkin = False
    if request.user.is_authenticated and active_event:
        user_checkin = check_user_event_checkin(request.user, active_event)

    context = {
        'active_event': active_event,
        'tournaments': tournaments,
        'user_checkin': user_checkin,
    }
    return render(request, 'tournaments/tournament_list.html', context)


def tournament_detail(request, slug):
    """
    Detailseite eines Turniers inkl. Turnierbaum-Visualisierung, Teams & Vorschau.
    """
    tournament = get_object_or_404(
        Tournament.objects.select_related('event', 'game', 'tournament_admin', 'tournament_support'),
        slug=slug
    )

    user_checkin = False
    is_admin = False
    user_team = None
    is_registered = False

    if request.user.is_authenticated:
        user_checkin = check_user_event_checkin(request.user, tournament.event)
        is_admin = (
            request.user.is_staff or
            request.user == tournament.tournament_admin or
            request.user == tournament.tournament_support
        )

        # Finde Team des Benutzers für dieses Spiel
        user_memberships = TeamMember.objects.filter(
            user=request.user,
            status=TeamMember.Status.ACCEPTED,
        ).select_related('team')

        for mem in user_memberships:
            if mem.team.game == tournament.game or mem.team.game is None:
                user_team = mem.team
                break

        if user_team:
            is_registered = TournamentRegistration.objects.filter(
                tournament=tournament,
                team=user_team
            ).exists()

    registrations = tournament.registrations.select_related('team', 'team__captain').all()
    matches = tournament.matches.select_related('team1', 'team2', 'winner', 'loser').order_by('bracket_type', 'round_number', 'match_number')

    # Vorschau-Daten generieren falls Turnierbaum noch nicht generiert
    preview_data = None
    if not tournament.is_generated:
        preview_data = generate_bracket(tournament, preview=True)

    # Für 1v1 Teams Verfügbarkeit ermitteln
    my_user_teams = []
    if request.user.is_authenticated:
        my_user_teams = Team.objects.filter(
            memberships__user=request.user,
            memberships__status=TeamMember.Status.ACCEPTED
        ).distinct()

    context = {
        'tournament': tournament,
        'user_checkin': user_checkin,
        'is_admin': is_admin,
        'user_team': user_team,
        'is_registered': is_registered,
        'registrations': registrations,
        'matches': matches,
        'preview_data': preview_data,
        'my_user_teams': my_user_teams,
    }
    return render(request, 'tournaments/tournament_detail.html', context)


@login_required
@require_POST
def tournament_register(request, slug):
    """
    Meldet ein Team oder einen Einzelspieler für das Turnier an.
    Prüft Vor-Ort Check-in!
    """
    tournament = get_object_or_404(Tournament, slug=slug)

    # 1. Check-in Validierung
    if not check_user_event_checkin(request.user, tournament.event):
        messages.error(
            request,
            "❌ Anmeldefehler: Nur vor Ort eingecheckte Gäste können sich für Turniere anmelden! Bitte checke am Einlass ein."
        )
        return redirect('tournament_detail', slug=slug)

    # 2. Status Validierung
    if tournament.status != Tournament.Status.REGISTRATION_OPEN:
        messages.error(request, "❌ Die Anmeldung für dieses Turnier ist aktuell nicht geöffnet.")
        return redirect('tournament_detail', slug=slug)

    # 3. Max Teams Validierung
    if tournament.registrations.count() >= tournament.max_teams:
        messages.error(request, "❌ Die maximale Teilnehmeranzahl für dieses Turnier wurde bereits erreicht.")
        return redirect('tournament_detail', slug=slug)

    # 4. Einzelspieler (1v1) Auto-Team oder gewähltes Team
    team_id = request.POST.get('team_id')

    if tournament.game.team_size == 1:
        # Automatisches Solo-Team erstellen / abrufen
        team = get_or_create_solo_team(request.user, tournament.game)
    else:
        if not team_id:
            messages.error(request, "❌ Bitte wähle ein Team für die Anmeldung aus.")
            return redirect('tournament_detail', slug=slug)
        team = get_object_or_404(Team, id=team_id)

        # Prüfen ob User Kapitän/Mitglied ist
        if not team.is_member(request.user):
            messages.error(request, "❌ Du bist kein Mitglied dieses Teams.")
            return redirect('tournament_detail', slug=slug)

    # 5. Anmelden
    reg, created = TournamentRegistration.objects.get_or_create(
        tournament=tournament,
        team=team,
    )
    if created:
        messages.success(request, f"🎉 Team '{team.name}' erfolgreich für '{tournament.title}' angemeldet!")
    else:
        messages.info(request, f"Dein Team '{team.name}' ist bereits angemeldet.")

    return redirect('tournament_detail', slug=slug)


@login_required
@require_POST
def tournament_unregister(request, slug):
    """
    Meldet das Team des Benutzers vom Turnier ab.
    """
    tournament = get_object_or_404(Tournament, slug=slug)
    team_id = request.POST.get('team_id')
    
    if tournament.is_generated:
        messages.error(request, "❌ Eine Abmeldung ist nicht mehr möglich, da der Turnierbaum bereits generiert wurde.")
        return redirect('tournament_detail', slug=slug)

    registration = TournamentRegistration.objects.filter(
        tournament=tournament,
        team_id=team_id,
        team__memberships__user=request.user,
    ).first()

    if registration:
        registration.delete()
        messages.success(request, f"Team erfolgreich vom Turnier '{tournament.title}' abgemeldet.")
    else:
        messages.error(request, "Keine aktive Turnieranmeldung gefunden.")

    return redirect('tournament_detail', slug=slug)


@login_required
@require_POST
def tournament_generate_bracket(request, slug):
    """
    Admin-Aktion: Schließt die Anmeldung und generiert den Turnierbaum.
    """
    tournament = get_object_or_404(Tournament, slug=slug)

    is_admin = (
        request.user.is_staff or
        request.user == tournament.tournament_admin or
        request.user == tournament.tournament_support
    )

    if not is_admin:
        messages.error(request, "Keine Berechtigung zur Generierung des Turnierbaums.")
        return redirect('tournament_detail', slug=slug)

    tournament.status = Tournament.Status.REGISTRATION_CLOSED
    tournament.save()

    res = generate_bracket(tournament, preview=False)
    if res:
        messages.success(request, f"🚀 Turnierbaum für '{tournament.title}' erfolgreich generiert! Das Turnier läuft jetzt.")
    else:
        messages.error(request, "Fehler bei der Generierung. Es sind mindestens 2 angemeldete Teams erforderlich.")

    return redirect('tournament_detail', slug=slug)


@login_required
@require_POST
def match_update_score(request, match_id):
    """
    Quick-Result Modal für Turnier-Admins: Trägt Spielergebnisse ein und rückt Sieger vor.
    """
    match_obj = get_object_or_404(
        TournamentMatch.objects.select_related('tournament', 'team1', 'team2'),
        id=match_id
    )
    tournament = match_obj.tournament

    is_admin = (
        request.user.is_staff or
        request.user == tournament.tournament_admin or
        request.user == tournament.tournament_support
    )

    if not is_admin:
        return JsonResponse({'success': False, 'error': 'Keine Berechtigung zur Ergebniseingabe.'}, status=403)

    try:
        score1 = int(request.POST.get('score_team1', 0))
        score2 = int(request.POST.get('score_team2', 0))
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Ungültige Punkte/Scores eingetragen.'}, status=400)

    winner_id = request.POST.get('winner_id')
    winner_team = None

    if winner_id:
        try:
            winner_id_int = int(winner_id)
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'error': 'Ungültige Sieger-ID.'}, status=400)

        if match_obj.team1 and match_obj.team1.id == winner_id_int:
            winner_team = match_obj.team1
        elif match_obj.team2 and match_obj.team2.id == winner_id_int:
            winner_team = match_obj.team2
        else:
            return JsonResponse({'success': False, 'error': 'Das gewählte Team nimmt nicht an diesem Match teil.'}, status=400)
    else:
        if score1 > score2:
            winner_team = match_obj.team1
        elif score2 > score1:
            winner_team = match_obj.team2
        else:
            return JsonResponse({'success': False, 'error': 'Unentschieden ist in KO-Matches nicht erlaubt. Wähle den Sieger aus.'}, status=400)

    if not winner_team:
        return JsonResponse({'success': False, 'error': 'Konnte keinen gültigen Sieger ermitteln.'}, status=400)

    advance_match_winner(match_obj, winner_team, score1, score2)

    messages.success(request, f"Ergebnis gespeichert! Sieger: {winner_team.name}")
    return JsonResponse({'success': True, 'winner': winner_team.name})


# =============================================================================
# TEAMMANAGER VIEWS
# =============================================================================


def team_list(request):
    """
    Teammanager Hauptseite: Zeigt Teams des aktiven Events sowie archivierte Teams vergangener Events.
    """
    active_event = Event.objects.filter(is_active=True).first()
    games = Game.objects.all()
    active_tab = request.GET.get('tab', 'active')

    # Aktive Teams: Nicht archiviert & entweder dem aktiven Event zugeordnet oder ohne Zuordnung
    if active_event:
        active_teams = Team.objects.filter(
            is_solo=False,
            is_archived=False,
        ).filter(models.Q(event=active_event) | models.Q(event__isnull=True)).select_related('captain', 'game', 'event').prefetch_related('memberships__user')

        archived_teams = Team.objects.filter(
            is_solo=False
        ).filter(models.Q(is_archived=True) | ~models.Q(event=active_event) & models.Q(event__isnull=False)).select_related('captain', 'game', 'event').prefetch_related('memberships__user')
    else:
        active_teams = Team.objects.filter(is_solo=False, is_archived=False).select_related('captain', 'game', 'event').prefetch_related('memberships__user')
        archived_teams = Team.objects.filter(is_solo=False, is_archived=True).select_related('captain', 'game', 'event').prefetch_related('memberships__user')

    my_active_teams = []
    my_archived_teams = []
    if request.user.is_authenticated:
        user_teams = Team.objects.filter(
            memberships__user=request.user,
            memberships__status=TeamMember.Status.ACCEPTED
        ).select_related('captain', 'game', 'event').distinct()

        for t in user_teams:
            if t.is_archived or (active_event and t.event_id and t.event_id != active_event.id):
                my_archived_teams.append(t)
            else:
                my_active_teams.append(t)

    context = {
        'active_event': active_event,
        'active_tab': active_tab,
        'active_teams': active_teams,
        'archived_teams': archived_teams,
        'my_active_teams': my_active_teams,
        'my_archived_teams': my_archived_teams,
        'games': games,
    }
    return render(request, 'tournaments/team_list.html', context)


@login_required
@require_POST
def team_create(request):
    """
    Erstellt ein neues Team für den Benutzer für das aktive Event (Benutzer wird Kapitän).
    """
    active_event = Event.objects.filter(is_active=True).first()
    name = request.POST.get('name', '').strip()
    tag = request.POST.get('tag', '').strip()
    game_id = request.POST.get('game_id')

    if not name:
        messages.error(request, "Bitte gib einen Teamnamen ein.")
        return redirect('team_list')

    if Team.objects.filter(name__iexact=name, is_archived=False).exists():
        messages.error(request, "Ein aktives Team mit diesem Namen existiert bereits.")
        return redirect('team_list')

    game = Game.objects.filter(id=game_id).first() if game_id else None

    team = Team.objects.create(
        name=name,
        tag=tag,
        game=game,
        captain=request.user,
        event=active_event,
        is_archived=False,
    )
    TeamMember.objects.create(
        team=team,
        user=request.user,
        role=TeamMember.Role.CAPTAIN,
        status=TeamMember.Status.ACCEPTED,
    )

    messages.success(request, f"🎉 Team '{team.name}' erfolgreich gegründet! Einladungscode: {team.invite_code}")
    return redirect('team_detail', slug=team.slug)


def team_detail(request, slug):
    """
    Übersichtsseite eines einzelnen Teams inkl. Archiv-Status und Reaktivierungsoption.
    """
    active_event = Event.objects.filter(is_active=True).first()
    team = get_object_or_404(Team.objects.select_related('captain', 'game', 'event'), slug=slug)

    members = team.memberships.select_related('user').all()
    accepted_members = [m for m in members if m.status == TeamMember.Status.ACCEPTED]
    pending_members = [m for m in members if m.status == TeamMember.Status.PENDING]

    is_captain = team.is_captain(request.user)
    is_member = team.is_member(request.user)

    user_membership = None
    if request.user.is_authenticated:
        user_membership = team.memberships.filter(user=request.user).first()

    # Roster-Status für das aktive Event prüfen
    roster_with_event_status = []
    if active_event:
        for m in accepted_members:
            reg = EventRegistration.objects.filter(user=m.user, event=active_event).first()
            roster_with_event_status.append({
                'membership': m,
                'user': m.user,
                'is_registered': reg is not None,
                'is_checked_in': reg.is_checked_in if reg else False,
            })
    else:
        for m in accepted_members:
            roster_with_event_status.append({
                'membership': m,
                'user': m.user,
                'is_registered': False,
                'is_checked_in': False,
            })

    is_team_archived = team.is_archived or bool(active_event and team.event_id and team.event_id != active_event.id)

    context = {
        'team': team,
        'active_event': active_event,
        'is_team_archived': is_team_archived,
        'accepted_members': accepted_members,
        'roster_with_event_status': roster_with_event_status,
        'pending_members': pending_members,
        'is_captain': is_captain,
        'is_member': is_member,
        'user_membership': user_membership,
    }
    return render(request, 'tournaments/team_detail.html', context)


@login_required
def team_reactivate(request, slug):
    """
    Reaktivierungs-Assistent: Ermöglicht dem Kapitän, ein archiviertes Team für das aktive Event zu reaktivieren.
    Inklusive Smart Roster Check (Mitglieder behalten/entfernen basierend auf Event-Anmeldung).
    """
    team = get_object_or_404(Team.objects.select_related('captain', 'game', 'event'), slug=slug)
    active_event = Event.objects.filter(is_active=True).first()

    if not team.is_captain(request.user) and not request.user.is_staff:
        messages.error(request, "Nur der Teamkapitän kann das Team reaktivieren.")
        return redirect('team_detail', slug=team.slug)

    if not active_event:
        messages.error(request, "Derzeit ist keine aktive Veranstaltung vorhanden, für die das Team reaktiviert werden kann.")
        return redirect('team_detail', slug=team.slug)

    accepted_members = list(team.get_accepted_members())

    if request.method == 'POST':
        game_id = request.POST.get('game_id')
        keep_user_ids = [int(uid) for uid in request.POST.getlist('keep_members') if uid.isdigit()]
        reset_invite = request.POST.get('reset_invite_code') == '1'

        with transaction.atomic():
            team.event = active_event
            team.is_archived = False
            if game_id:
                team.game_id = game_id
            if reset_invite:
                team.invite_code = generate_invite_code()
            team.save()

            # Mitglieder bereinigen (Kapitän bleibt immer)
            TeamMember.objects.filter(team=team).exclude(user=team.captain).exclude(user_id__in=keep_user_ids).delete()

        messages.success(request, f"🎉 Team '{team.name}' wurde erfolgreich für '{active_event.title}' reaktiviert!")
        return redirect('team_detail', slug=team.slug)

    # GET: Roster vorbereiten
    roster = []
    for m in accepted_members:
        reg = EventRegistration.objects.filter(user=m.user, event=active_event).first()
        roster.append({
            'member': m,
            'user': m.user,
            'is_captain': (m.user == team.captain),
            'is_registered': reg is not None,
            'is_checked_in': reg.is_checked_in if reg else False,
            'ticket_name': reg.ticket_type.name if (reg and reg.ticket_type) else None,
        })

    games = Game.objects.all()

    context = {
        'team': team,
        'active_event': active_event,
        'roster': roster,
        'games': games,
    }
    return render(request, 'tournaments/team_reactivate.html', context)



@login_required
@require_POST
def team_join_by_code(request):
    """
    Tritt einem Team per Einladungscode bei.
    """
    code = request.POST.get('invite_code', '').strip().upper()

    if not code:
        messages.error(request, "Bitte gib einen Einladungscode ein.")
        return redirect('team_list')

    team = Team.objects.filter(invite_code=code).first()
    if not team:
        messages.error(request, "❌ Ungültiger Einladungscode.")
        return redirect('team_list')

    if team.is_member(request.user):
        messages.info(request, f"Du bist bereits Mitglied im Team '{team.name}'.")
        return redirect('team_detail', slug=team.slug)

    TeamMember.objects.get_or_create(
        team=team,
        user=request.user,
        defaults={
            'role': TeamMember.Role.MEMBER,
            'status': TeamMember.Status.ACCEPTED,
        }
    )

    messages.success(request, f"🤝 Du bist dem Team '{team.name}' erfolgreich beigetreten!")
    return redirect('team_detail', slug=team.slug)


@login_required
@require_POST
def team_leave(request, slug):
    """
    User verlässt das Team.
    Logik: Bei Kapitän-Austritt geht Rang an nächstes Mitglied; bei 0 Mitgliedern wird das Team gelöscht.
    """
    team = get_object_or_404(Team, slug=slug)

    res = team.leave_team(request.user)
    if res == 'deleted':
        messages.info(request, f"Du hast das Team '{team.name}' verlassen. Da du das letzte Mitglied warst, wurde das Team gelöscht.")
        return redirect('team_list')
    elif res == 'captain_transferred':
        messages.warning(request, f"Du hast das Team '{team.name}' verlassen. Die Kapitänswürde wurde an ein anderes Mitglied übertragen.")
        return redirect('team_list')
    elif res == 'left':
        messages.success(request, f"Du hast das Team '{team.name}' verlassen.")
        return redirect('team_list')
    else:
        messages.error(request, "Du bist kein Mitglied dieses Teams.")
        return redirect('team_detail', slug=slug)


@login_required
@require_POST
def team_kick_member(request, slug, user_id):
    """
    Kapitän kickt ein Mitglied aus dem Team.
    """
    team = get_object_or_404(Team, slug=slug)

    if not team.is_captain(request.user) and not request.user.is_staff:
        messages.error(request, "Nur der Kapitän oder Administratoren können Mitglieder entfernen.")
        return redirect('team_detail', slug=slug)

    try:
        target_user_id = int(user_id)
    except (ValueError, TypeError):
        messages.error(request, "Ungültige Benutzer-ID.")
        return redirect('team_detail', slug=slug)

    if target_user_id == team.captain_id:
        messages.error(request, "Der Kapitän kann sich nicht selbst kicken. Nutze stattdessen 'Team verlassen'.")
        return redirect('team_detail', slug=slug)

    membership = TeamMember.objects.filter(team=team, user_id=target_user_id).select_related('user').first()
    if membership:
        kicked_username = membership.user.username
        membership.delete()
        messages.success(request, f"Mitglied '{kicked_username}' wurde aus dem Team entfernt.")
    else:
        messages.error(request, "Mitglied nicht gefunden.")

    return redirect('team_detail', slug=slug)



@login_required
@require_POST
def team_apply(request, slug):
    """
    Gast bewirbt sich für ein Team (Status = PENDING).
    """
    team = get_object_or_404(Team, slug=slug)

    if team.is_member(request.user):
        messages.info(request, "Du bist bereits Mitglied in diesem Team.")
        return redirect('team_detail', slug=slug)

    TeamMember.objects.get_or_create(
        team=team,
        user=request.user,
        defaults={
            'role': TeamMember.Role.MEMBER,
            'status': TeamMember.Status.PENDING,
        }
    )

    messages.success(request, f"Bewerbung an Team '{team.name}' gesendet!")
    return redirect('team_detail', slug=slug)


@login_required
@require_POST
def team_accept_membership(request, slug, membership_id):
    """
    Kapitän akzeptiert eine ausstehende Bewerbung.
    """
    team = get_object_or_404(Team, slug=slug)

    if not team.is_captain(request.user) and not request.user.is_staff:
        messages.error(request, "Nur der Kapitän kann Bewerbungen annehmen.")
        return redirect('team_detail', slug=slug)

    membership = get_object_or_404(TeamMember, id=membership_id, team=team)
    membership.status = TeamMember.Status.ACCEPTED
    membership.save()

    messages.success(request, f"Bewerbung von '{membership.user.username}' angenommen!")
    return redirect('team_detail', slug=slug)
