from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from configuration.translations import get_translation
from events.models import Event, EventRegistration

from tournaments.models import (
    Game, Team, TeamMember, Tournament, TournamentMatch, TournamentRegistration, generate_invite_code
)

from tournaments.exceptions import (
    TournamentError,
    TournamentRegistrationError,
    TournamentBracketError,
    TournamentMatchError,
    MatchPermissionDeniedError,
)
from tournaments.services import (
    FFAMatchService,
    GroupStageStandingService,
    LeagueStandingService,
    TournamentBracketService,
    TournamentMatchService,
    TournamentPodiumService,
    TournamentRegistrationService,
    advance_match_winner,
    check_user_event_checkin,
    generate_bracket,
    get_or_create_solo_team,
)


# =============================================================================
# TURNIERE VIEWS
# =============================================================================

def tournament_list(request):
    """
    Übersichtsseite aller Turniere für die aktive Hauptveranstaltung.
    """
    active_event = Event.objects.get_active()
    tournaments = (
        Tournament.objects.filter(event=active_event)
        .select_related('game', 'event')
        .annotate(annotated_registered_teams_count=models.Count('registrations'))
    ) if active_event else []

    user_checkin = False
    registered_tournament_ids = set()
    if request.user.is_authenticated and active_event:
        user_checkin = check_user_event_checkin(request.user, active_event)
        registered_tournament_ids = set(
            TournamentRegistration.objects.filter(
                tournament__in=tournaments,
                team__memberships__user=request.user,
                team__memberships__status=TeamMember.Status.ACCEPTED,
            ).values_list('tournament_id', flat=True)
        )

    context = {
        'active_event': active_event,
        'tournaments': tournaments,
        'user_checkin': user_checkin,
        'registered_tournament_ids': registered_tournament_ids,
    }
    return render(request, 'tournaments/tournament_list.html', context)


def tournament_detail(request, slug):
    """
    Detailansicht eines Turniers: Infos, Anmeldungen, Turnierbaum & Live-Matches.
    """
    tournament = get_object_or_404(
        Tournament.objects.select_related('game', 'event', 'tournament_admin', 'tournament_support'),
        slug=slug
    )

    now = timezone.now()
    user_checkin = False
    has_event_ticket = False
    is_admin = False
    user_team = None
    is_registered = False
    my_user_teams = []
    user_member_team = None

    if request.user.is_authenticated:
        is_admin = tournament.is_managed_by(request.user)

        if tournament.event:
            user_reg = EventRegistration.objects.filter(user=request.user, event=tournament.event).first()
            if user_reg:
                has_event_ticket = True
                user_checkin = user_reg.is_checked_in

        # Für Admins/Staff gilt der Check-in im Frontend immer als erfüllt
        if is_admin:
            user_checkin = True

        # Finde heraus, ob der User bereits mit einem Team für dieses Turnier angemeldet ist
        registered_team_reg = TournamentRegistration.objects.filter(
            tournament=tournament,
            team__memberships__user=request.user,
            team__memberships__status=TeamMember.Status.ACCEPTED
        ).select_related('team').first()

        if registered_team_reg:
            is_registered = True
            user_team = registered_team_reg.team

        # Teams, bei denen der User Kapitän ist, für dieses Spiel und Event (nicht archiviert, nicht solo)
        my_user_teams = Team.objects.filter(
            captain=request.user,
            is_archived=False,
            is_solo=False,
            game=tournament.game,
        ).filter(
            models.Q(event=tournament.event) | models.Q(event__isnull=True)
        ).distinct()

        # Team, in dem der User einfaches Mitglied ist (nicht Kapitän), für dieses Spiel und Event
        user_member_team = Team.objects.filter(
            memberships__user=request.user,
            memberships__status=TeamMember.Status.ACCEPTED,
            is_archived=False,
            is_solo=False,
            game=tournament.game,
        ).exclude(
            captain=request.user
        ).filter(
            models.Q(event=tournament.event) | models.Q(event__isnull=True)
        ).select_related('captain').first()

    registrations = tournament.registrations.select_related('team', 'team__captain').all()
    matches = tournament.matches.select_related('team1', 'team2', 'winner', 'loser').order_by('bracket_type', 'round_number', 'match_number')

    # Status & Zeitfenster-Details für die UI
    tournament_is_full = bool(tournament.max_teams and registrations.count() >= tournament.max_teams)
    registration_not_started_yet = bool(tournament.registration_start and now < tournament.registration_start)
    registration_ended = bool(tournament.registration_end and now > tournament.registration_end)

    # Vorschau-Daten generieren: Exklusiv für Turnier-Admins / Staff vor Bracket-Generierung (Variante B)
    preview_data = None
    if is_admin and not tournament.is_generated:
        preview_data = TournamentBracketService.get_bracket_preview(tournament.id)

    # Standings & Modus-spezifische Match- und Tabellendaten
    league_standings = []
    group_a_standings = []
    group_b_standings = []
    ffa_match = None
    ffa_participants = []
    wb_matches = []
    lb_matches = []
    grand_final_matches = []
    se_matches = []

    if tournament.is_generated:
        if tournament.mode == Tournament.Mode.DOUBLE_ELIMINATION:
            wb_matches = matches.filter(bracket_type=TournamentMatch.BracketType.WINNERS).order_by('round_number', 'match_number')
            lb_matches = matches.filter(bracket_type=TournamentMatch.BracketType.LOSERS).order_by('round_number', 'match_number')
            grand_final_matches = matches.filter(bracket_type__in=[
                TournamentMatch.BracketType.GRAND_FINAL,
                TournamentMatch.BracketType.GRAND_FINAL_RESET
            ]).order_by('round_number', 'id')
        elif tournament.mode == Tournament.Mode.SINGLE_ELIMINATION:
            se_matches = matches.filter(bracket_type__in=[
                TournamentMatch.BracketType.WINNERS,
                TournamentMatch.BracketType.FINAL
            ]).order_by('round_number', 'match_number')
        elif tournament.mode == Tournament.Mode.LEAGUE:
            league_standings = LeagueStandingService.calculate_league_standings(tournament)
        elif tournament.mode == Tournament.Mode.GROUP_STAGE:
            group_a_standings = GroupStageStandingService.calculate_group_standings(tournament, 'Gruppe A')
            group_b_standings = GroupStageStandingService.calculate_group_standings(tournament, 'Gruppe B')
        elif tournament.mode == Tournament.Mode.FFA:
            ffa_match = tournament.matches.filter(bracket_type=TournamentMatch.BracketType.FFA).first()
            if ffa_match:
                ffa_participants = list(ffa_match.participants.select_related('team').order_by('rank', '-score', 'id'))

    podium = TournamentPodiumService.calculate(
        tournament, league_standings=league_standings, ffa_participants=ffa_participants,
    )

    # Read-only presentation data; registration services remain authoritative.
    candidate_teams = list(my_user_teams)
    readiness_teams = candidate_teams or ([user_member_team] if user_member_team else [])
    memberships = list(TeamMember.objects.filter(
        team__in=readiness_teams, status=TeamMember.Status.ACCEPTED,
    ).values('team_id', 'user_id'))
    checked_in_ids = set(EventRegistration.objects.filter(
        event=tournament.event,
        user_id__in=[m['user_id'] for m in memberships], is_checked_in=True,
    ).values_list('user_id', flat=True)) if memberships else set()
    team_readiness = []
    for team in readiness_teams:
        ids = [m['user_id'] for m in memberships if m['team_id'] == team.id]
        team_readiness.append({
            'team': team, 'count': len(ids),
            'checked_in': sum(uid in checked_in_ids for uid in ids),
            'size_ok': len(ids) == tournament.game.team_size,
            'ready': len(ids) == tournament.game.team_size and (is_admin or all(uid in checked_in_ids for uid in ids)),
        })

    match_list = list(matches)
    next_match = None
    if user_team and tournament.status == Tournament.Status.IN_PROGRESS:
        personal_matches = [m for m in match_list if not m.is_bye
                            and m.status != TournamentMatch.Status.COMPLETED
                            and user_team.id in (m.team1_id, m.team2_id)]
        personal_matches.sort(key=lambda m: (
            m.status != TournamentMatch.Status.IN_PROGRESS,
            m.status != TournamentMatch.Status.READY, m.round_number, m.match_number,
        ))
        next_match = next(iter(personal_matches), None)

    score_matches = {}
    for match in match_list:
        role = 1 if user_team and user_team.id == match.team1_id else 2 if user_team and user_team.id == match.team2_id else 0
        score_matches[str(match.id)] = {
            'id': match.id, 'team1': match.team1.name if match.team1 else '',
            'team2': match.team2.name if match.team2 else '',
            'team1Id': match.team1_id, 'team2Id': match.team2_id,
            'score1': match.score_team1, 'score2': match.score_team2,
            'winner': match.winner_id, 'reason': match.decision_reason,
            'isAdmin': is_admin, 'role': role,
            'allowsDraw': tournament.mode == Tournament.Mode.LEAGUE or match.bracket_type == TournamentMatch.BracketType.GROUP,
        }

    context = {
        'next_match': next_match,
        'team_readiness': team_readiness,
        'team_registration_ready': any(row['ready'] for row in team_readiness),
        'match_list_cards': sorted(match_list, key=lambda m: (
            {TournamentMatch.Status.IN_PROGRESS: 0, TournamentMatch.Status.READY: 1,
             TournamentMatch.Status.PENDING: 2, TournamentMatch.Status.COMPLETED: 3}.get(m.status, 4),
            m.round_number,
            {TournamentMatch.BracketType.GROUP: 0, TournamentMatch.BracketType.WINNERS: 1,
             TournamentMatch.BracketType.LOSERS: 2, TournamentMatch.BracketType.FINAL: 3,
             TournamentMatch.BracketType.GRAND_FINAL: 4,
             TournamentMatch.BracketType.GRAND_FINAL_RESET: 5}.get(m.bracket_type, 6),
            m.match_number,
        )),
        'score_matches': score_matches,
        'tournament': tournament,
        'user_checkin': user_checkin,
        'has_event_ticket': has_event_ticket,
        'is_admin': is_admin,
        'user_team': user_team,
        'is_registered': is_registered,
        'registrations': registrations,
        'matches': matches,
        'wb_matches': wb_matches,
        'lb_matches': lb_matches,
        'grand_final_matches': grand_final_matches,
        'se_matches': se_matches,
        'podium': podium,
        'preview_data': preview_data,
        'my_user_teams': my_user_teams,
        'user_member_team': user_member_team,
        'tournament_is_full': tournament_is_full,
        'registration_not_started_yet': registration_not_started_yet,
        'registration_ended': registration_ended,
        'league_standings': league_standings,
        'group_a_standings': group_a_standings,
        'group_b_standings': group_b_standings,
        'ffa_match': ffa_match,
        'ffa_participants': ffa_participants,
    }
    return render(request, 'tournaments/tournament_detail.html', context)


@login_required
@require_POST
def tournament_register(request, slug):
    """
    Meldet ein Team oder einen Einzelspieler für das Turnier an.
    Prüft Zeitfenster, Vor-Ort Check-in, Kapazitätslimits und Team-Berechtigungen transaktionssicher.
    """
    tournament = get_object_or_404(Tournament, slug=slug)
    team_id = request.POST.get('team_id')

    try:
        reg, created = TournamentRegistrationService.register_team(
            tournament_id=tournament.id,
            user=request.user,
            team_id=team_id,
            actor=request.user,
        )
        if created:
            messages.success(
                request,
                get_translation(
                    'msg_tournament_reg_success',
                    'Team "{team_name}" erfolgreich für "{tournament_title}" angemeldet!',
                    team_name=reg.team.name,
                    tournament_title=tournament.title,
                ),
            )
        else:
            messages.info(
                request,
                get_translation(
                    'msg_tournament_already_registered',
                    'Dein Team "{team_name}" ist bereits angemeldet.',
                    team_name=reg.team.name,
                ),
            )
    except TournamentError as e:
        messages.error(request, str(e))

    return redirect('tournament_detail', slug=slug)


@login_required
@require_POST
def tournament_unregister(request, slug):
    """
    Meldet das Team des Benutzers vom Turnier ab.
    """
    tournament = get_object_or_404(Tournament, slug=slug)
    team_id = request.POST.get('team_id')

    try:
        team_name = TournamentRegistrationService.unregister_team(
            tournament_id=tournament.id,
            user=request.user,
            team_id=team_id,
            actor=request.user,
        )
        messages.success(
            request,
            get_translation(
                'msg_tournament_unreg_success',
                'Team "{team_name}" erfolgreich vom Turnier "{tournament_title}" abgemeldet.',
                team_name=team_name,
                tournament_title=tournament.title,
            ),
        )
    except TournamentError as e:
        messages.error(request, str(e))

    return redirect('tournament_detail', slug=slug)


@login_required
@require_POST
def tournament_generate_bracket(request, slug):
    """
    Admin-Aktion: Validiert Mindestteams, generiert den Turnierbaum und schließt erst dann atomar die Anmeldung.
    """
    tournament = get_object_or_404(Tournament, slug=slug)

    is_admin = tournament.is_managed_by(request.user)

    if not is_admin:
        messages.error(
            request,
            get_translation('msg_tournament_no_perm_bracket', 'Keine Berechtigung zur Generierung des Turnierbaums.'),
        )
        return redirect('tournament_detail', slug=slug)

    try:
        TournamentBracketService.generate_bracket(tournament_id=tournament.id, actor=request.user)
        messages.success(
            request,
            get_translation(
                'msg_bracket_generated',
                'Turnierbaum für "{tournament_title}" erfolgreich generiert! Das Turnier läuft jetzt.',
                tournament_title=tournament.title,
            ),
        )
    except TournamentError as e:
        messages.error(request, str(e))

    return redirect('tournament_detail', slug=slug)


@login_required
@require_POST
def match_update_score(request, match_id):
    """
    Quick-Result Modal für Turnier-Admins und Teilnehmer: Trägt Spielergebnisse ein und rückt Sieger vor.
    Validierung und Berechtigungsprüfung (inkl. Fairplay-Schutz) erfolgen
    vollständig und atomar im Service unter DB-Row-Locks.
    """
    try:
        score1 = request.POST.get('score_team1', 0)
        score2 = request.POST.get('score_team2', 0)
        winner_id = request.POST.get('winner_id')
        decision_reason = (request.POST.get('decision_reason') or '').strip()

        match_updated, winner_team = TournamentMatchService.update_match_score(
            match_id=match_id,
            score1=score1,
            score2=score2,
            winner_id=winner_id,
            decision_reason=decision_reason,
            actor=request.user,
        )

        if winner_team:
            messages.success(
                request,
                get_translation(
                    'msg_tournament_score_saved',
                    'Ergebnis gespeichert! Sieger: {winner_name}',
                    winner_name=winner_team.name,
                ),
            )
            return JsonResponse({'success': True, 'winner': winner_team.name})
        else:
            messages.success(
                request,
                get_translation(
                    'msg_tournament_score_draw',
                    'Ergebnis gespeichert! Unentschieden.',
                ),
            )
            return JsonResponse({'success': True, 'winner': None, 'draw': True})
    except TournamentMatch.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Match nicht gefunden.'}, status=404)
    except MatchPermissionDeniedError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=403)
    except TournamentError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Interner Fehler: {e}'}, status=500)


@login_required
@require_POST
def match_update_ffa_score(request, match_id):
    """
    Erfasst Ränge und Scores für alle Teilnehmer eines FFA-Matches.
    """
    match_obj = get_object_or_404(
        TournamentMatch.objects.select_related('tournament'),
        id=match_id
    )
    tournament = match_obj.tournament

    is_admin = tournament.is_managed_by(request.user)

    if not is_admin:
        messages.error(
            request,
            get_translation('msg_tournament_no_perm_score', 'Keine Berechtigung zur Ergebniseingabe.'),
        )
        return redirect('tournament_detail', slug=tournament.slug)

    try:
        participant_scores = []
        participants = match_obj.participants.all()
        for p in participants:
            rank_val = request.POST.get(f'rank_{p.id}')
            score_val = request.POST.get(f'score_{p.id}', 0)
            notes_val = request.POST.get(f'notes_{p.id}', '')
            is_dq = bool(request.POST.get(f'dq_{p.id}'))
            participant_scores.append({
                'participant_id': p.id,
                'rank': rank_val,
                'score': score_val,
                'notes': notes_val,
                'is_disqualified': is_dq,
            })

        decision_reason = request.POST.get('decision_reason', '')

        FFAMatchService.update_ffa_scores(
            match_id=match_obj.id,
            participant_scores=participant_scores,
            decision_reason=decision_reason,
            actor=request.user,
        )

        messages.success(
            request,
            get_translation(
                'msg_tournament_ffa_scores_saved',
                'FFA-Ergebnisse für "{tournament_title}" erfolgreich gespeichert!',
                tournament_title=tournament.title,
            ),
        )
    except TournamentError as e:
        messages.error(request, str(e))
    except Exception as e:
        messages.error(request, get_translation('tournament_ffa_unexpected_error', 'Unerwarteter Fehler: {error}', error=e))

    return redirect('tournament_detail', slug=tournament.slug)


# =============================================================================
# TEAMMANAGER VIEWS
# =============================================================================


def team_list(request):
    """
    Teammanager Hauptseite: Zeigt Teams des aktiven Events sowie archivierte Teams vergangener Events.
    Unterstützt Filterung nach Spielen und Sortierung nach Spielen & Teamnamen.
    """
    active_event = Event.objects.get_active()
    games = Game.objects.all().order_by('name')
    active_tab = request.GET.get('tab', 'active')
    game_filter = request.GET.get('game', '').strip()
    selected_game_id = int(game_filter) if game_filter.isdigit() else None

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

    # Nach Spiel und Teamname sortieren
    active_teams = active_teams.order_by('game__name', 'name')
    archived_teams = archived_teams.order_by('game__name', 'name')

    # Optionaler Filter nach Spiel
    if selected_game_id:
        active_teams = active_teams.filter(game_id=selected_game_id)
        archived_teams = archived_teams.filter(game_id=selected_game_id)

    my_active_teams = []
    my_archived_teams = []
    if request.user.is_authenticated:
        user_teams = Team.objects.filter(
            memberships__user=request.user,
            memberships__status=TeamMember.Status.ACCEPTED
        ).select_related('captain', 'game', 'event').prefetch_related('memberships__user').distinct().order_by('game__name', 'name')

        for t in user_teams:
            if selected_game_id and t.game_id != selected_game_id:
                continue
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
        'selected_game_id': selected_game_id,
    }
    return render(request, 'tournaments/team_list.html', context)


@login_required
@require_POST
def team_create(request):
    """
    Erstellt ein neues Team für den Benutzer für das aktive Event (Benutzer wird Kapitän).
    Regel: Ein Gast darf nur einem aktiven Team pro Spiel angehören.
    """
    active_event = Event.objects.get_active()
    name = request.POST.get('name', '').strip()
    tag = request.POST.get('tag', '').strip()
    game_id = request.POST.get('game_id')

    if not name:
        messages.error(request, get_translation('msg_team_name_required', 'Bitte gib einen Teamnamen ein.'))
        return redirect('team_list')

    if len(name) > 32:
        messages.error(request, get_translation('msg_team_name_too_long', 'Der Teamname darf maximal 32 Zeichen lang sein.'))
        return redirect('team_list')

    if len(tag) > 5:
        messages.error(request, get_translation('msg_team_tag_too_long', 'Der Team-Tag darf maximal 5 Zeichen lang sein.'))
        return redirect('team_list')

    tag = tag.upper()

    if not game_id:
        messages.error(request, get_translation('msg_team_game_required', 'Bitte wähle ein Spiel für das Team aus.'))
        return redirect('team_list')

    game = Game.objects.filter(id=game_id).first()
    if not game:
        messages.error(request, get_translation('msg_team_game_invalid', 'Das ausgewählte Spiel ist ungültig.'))
        return redirect('team_list')

    # Regel: Nur 1 aktives Team pro Spiel pro Gast
    existing_membership = TeamMember.objects.filter(
        user=request.user,
        status=TeamMember.Status.ACCEPTED,
        team__game=game,
        team__is_archived=False,
    ).select_related('team').first()
    if existing_membership:
        messages.error(
            request,
            get_translation(
                'msg_team_user_already_has_team',
                'Du gehörst für das Spiel "{game_name}" bereits dem Team "{team_name}" an. Ein Gast darf nur einem Team pro Spiel angehören.',
                game_name=game.name,
                team_name=existing_membership.team.name,
            ),
        )
        return redirect('team_list')

    if Team.objects.filter(name__iexact=name, is_archived=False).exists():
        messages.error(request, get_translation('msg_team_name_exists', 'Ein aktives Team mit diesem Namen existiert bereits.'))
        return redirect('team_list')

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

    messages.success(
        request,
        get_translation(
            'msg_team_created',
            'Team "{team_name}" erfolgreich gegründet! Einladungscode: {invite_code}',
            team_name=team.name,
            invite_code=team.invite_code,
        ),
    )
    return redirect('team_detail', slug=team.slug)


def team_detail(request, slug):
    """
    Übersichtsseite eines einzelnen Teams inkl. Archiv-Status und Reaktivierungsoption.
    """
    active_event = Event.objects.get_active()
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
    is_team_full = bool(team.game and len(accepted_members) >= team.game.team_size)

    context = {
        'team': team,
        'active_event': active_event,
        'is_team_archived': is_team_archived,
        'is_team_full': is_team_full,
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
    active_event = Event.objects.get_active()

    if not team.is_captain(request.user) and not request.user.is_staff:
        messages.error(request, get_translation('msg_team_reactivate_captain_only', 'Nur der Teamkapitän kann das Team reaktivieren.'))
        return redirect('team_detail', slug=team.slug)

    if not team.is_archived:
        messages.info(request, get_translation('msg_team_already_active', 'Dieses Team ist bereits aktiv und muss nicht reaktiviert werden.'))
        return redirect('team_detail', slug=team.slug)

    if team.is_in_active_tournament():
        messages.error(
            request,
            get_translation(
                'msg_team_reactivate_in_tournament',
                'Das Team nimmt an einem laufenden oder generierten Turnier teil und kann nicht reaktiviert oder verändert werden.',
            ),
        )
        return redirect('team_detail', slug=team.slug)

    if not active_event:
        messages.error(request, get_translation('msg_team_reactivate_no_event', 'Derzeit ist keine aktive Veranstaltung vorhanden, für die das Team reaktiviert werden kann.'))
        return redirect('team_detail', slug=team.slug)

    accepted_members = list(team.get_accepted_members())

    if request.method == 'POST':
        game_id = request.POST.get('game_id')
        keep_user_ids = [int(uid) for uid in request.POST.getlist('keep_members') if uid.isdigit()]
        reset_invite = request.POST.get('reset_invite_code') == '1'

        target_game = team.game
        if game_id:
            try:
                target_game = Game.objects.get(id=game_id)
            except Game.DoesNotExist:
                messages.error(request, get_translation('msg_team_game_invalid', 'Das ausgewählte Spiel ist ungültig.'))
                return redirect('team_reactivate', slug=team.slug)

        # Prüfen, ob Kapitän bereits ein aktives Team für target_game hat
        if target_game:
            existing_captain_team = TeamMember.objects.filter(
                user=team.captain,
                status=TeamMember.Status.ACCEPTED,
                team__game=target_game,
                team__is_archived=False,
            ).exclude(team=team).select_related('team').first()
            if existing_captain_team:
                messages.error(
                    request,
                    get_translation(
                        'msg_team_user_already_has_team',
                        'Du gehörst für das Spiel "{game_name}" bereits dem Team "{team_name}" an. Ein Gast darf nur einem Team pro Spiel angehören.',
                        game_name=target_game.name,
                        team_name=existing_captain_team.team.name,
                    ),
                )
                return redirect('team_reactivate', slug=team.slug)

            # Mitglieder, die bereits in einem anderen aktiven Team für dieses Spiel sind, ausschließen
            conflicting_user_ids = set(TeamMember.objects.filter(
                user_id__in=keep_user_ids,
                status=TeamMember.Status.ACCEPTED,
                team__game=target_game,
                team__is_archived=False,
            ).exclude(team=team).values_list('user_id', flat=True))
            keep_user_ids = [uid for uid in keep_user_ids if uid not in conflicting_user_ids]

        with transaction.atomic():
            team.event = active_event
            team.is_archived = False
            if target_game:
                team.game = target_game
            if reset_invite:
                team.invite_code = generate_invite_code()
            team.save()

            # Mitglieder bereinigen (Kapitän bleibt immer)
            TeamMember.objects.filter(team=team).exclude(user=team.captain).exclude(user_id__in=keep_user_ids).delete()

        messages.success(
            request,
            get_translation(
                'msg_team_reactivated',
                'Team "{team_name}" wurde erfolgreich für "{event_title}" reaktiviert!',
                team_name=team.name,
                event_title=active_event.title,
            ),
        )
        return redirect('team_detail', slug=team.slug)

    # GET: Roster vorbereiten (batch-loading gegen N+1 Queries)
    user_ids = [m.user_id for m in accepted_members]
    event_regs = {
        reg.user_id: reg
        for reg in EventRegistration.objects.filter(user_id__in=user_ids, event=active_event).select_related('ticket_type')
    }
    roster = []
    for m in accepted_members:
        reg = event_regs.get(m.user_id)
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
        messages.error(request, get_translation('msg_team_code_required', 'Bitte gib einen Einladungscode ein.'))
        return redirect('team_list')

    with transaction.atomic():
        team = Team.objects.select_for_update().filter(invite_code=code).first()
        if not team:
            messages.error(request, get_translation('msg_team_code_invalid', 'Ungültiger Einladungscode.'))
            return redirect('team_list')

        if team.is_in_active_tournament():
            messages.error(
                request,
                get_translation(
                    'msg_team_join_in_active_tournament',
                    'Das Team "{team_name}" nimmt an einem laufenden Turnier teil. Ein Beitritt ist während des Turniers nicht möglich.',
                    team_name=team.name,
                ),
            )
            return redirect('team_list')

        if team.is_member(request.user):
            messages.info(
                request,
                get_translation(
                    'msg_team_already_member',
                    'Du bist bereits Mitglied im Team "{team_name}".',
                    team_name=team.name,
                ),
            )
            return redirect('team_detail', slug=team.slug)

        # Regel: Nur 1 aktives Team pro Spiel pro Gast
        if team.game:
            existing_membership = TeamMember.objects.filter(
                user=request.user,
                status=TeamMember.Status.ACCEPTED,
                team__game=team.game,
                team__is_archived=False,
            ).exclude(team=team).select_related('team').first()
            if existing_membership:
                messages.error(
                    request,
                    get_translation(
                        'msg_team_user_already_has_team',
                        'Du gehörst für das Spiel "{game_name}" bereits dem Team "{team_name}" an. Ein Gast darf nur einem Team pro Spiel angehören.',
                        game_name=team.game.name,
                        team_name=existing_membership.team.name,
                    ),
                )
                return redirect('team_list')

        if team.game and team.get_accepted_members().count() >= team.game.team_size:
            messages.error(
                request,
                get_translation(
                    'msg_team_full',
                    'Das Team "{team_name}" ist bereits voll (maximal {max_players} Spieler für {game_name}).',
                    team_name=team.name,
                    max_players=team.game.team_size,
                    game_name=team.game.name,
                ),
            )
            return redirect('team_list')

        membership, created = TeamMember.objects.get_or_create(
            team=team,
            user=request.user,
            defaults={
                'role': TeamMember.Role.MEMBER,
                'status': TeamMember.Status.ACCEPTED,
            }
        )

        if not created and membership.status == TeamMember.Status.PENDING:
            membership.status = TeamMember.Status.ACCEPTED
            membership.save(update_fields=['status'])

    messages.success(
        request,
        get_translation(
            'msg_team_joined',
            'Du bist dem Team "{team_name}" erfolgreich beigetreten!',
            team_name=team.name,
        ),
    )
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
    if res == 'in_active_tournament':
        messages.error(
            request,
            get_translation(
                'msg_team_leave_in_tournament',
                'Du kannst das Team "{team_name}" nicht verlassen, da es an einem laufenden Turnier teilnimmt. Wende dich bitte an die Turnierleitung.',
                team_name=team.name,
            ),
        )
        return redirect('team_detail', slug=slug)
    elif res == 'deleted':
        messages.info(
            request,
            get_translation(
                'msg_team_leave_deleted',
                'Du hast das Team "{team_name}" verlassen. Da du das letzte Mitglied warst, wurde das Team gelöscht.',
                team_name=team.name,
            ),
        )
        return redirect('team_list')
    elif res == 'captain_transferred':
        messages.warning(
            request,
            get_translation(
                'msg_team_leave_captain_transferred',
                'Du hast das Team "{team_name}" verlassen. Die Kapitänswürde wurde an ein anderes Mitglied übertragen.',
                team_name=team.name,
            ),
        )
        return redirect('team_list')
    elif res == 'left':
        messages.success(
            request,
            get_translation(
                'msg_team_left',
                'Du hast das Team "{team_name}" verlassen.',
                team_name=team.name,
            ),
        )
        return redirect('team_list')
    else:
        messages.error(
            request,
            get_translation('msg_team_not_member', 'Du bist kein Mitglied dieses Teams.'),
        )
        return redirect('team_detail', slug=slug)


@login_required
@require_POST
def team_kick_member(request, slug, user_id):
    """
    Kapitän kickt ein Mitglied aus dem Team.
    """
    team = get_object_or_404(Team, slug=slug)

    if team.is_in_active_tournament():
        messages.error(
            request,
            get_translation(
                'msg_team_kick_in_tournament',
                'Mitglieder können während eines laufenden Turniers nicht aus dem Team entfernt werden. Wende dich bitte an die Turnierleitung.',
            ),
        )
        return redirect('team_detail', slug=slug)

    if not team.is_captain(request.user) and not request.user.is_staff:
        messages.error(
            request,
            get_translation('msg_team_kick_forbidden', 'Nur der Kapitän oder Administratoren können Mitglieder entfernen.'),
        )
        return redirect('team_detail', slug=slug)

    try:
        target_user_id = int(user_id)
    except (ValueError, TypeError):
        messages.error(
            request,
            get_translation('msg_team_invalid_user_id', 'Ungültige Benutzer-ID.'),
        )
        return redirect('team_detail', slug=slug)

    if target_user_id == team.captain_id:
        messages.error(
            request,
            get_translation('msg_team_kick_self', 'Der Kapitän kann sich nicht selbst kicken. Nutze stattdessen "Team verlassen".'),
        )
        return redirect('team_detail', slug=slug)

    membership = TeamMember.objects.filter(team=team, user_id=target_user_id).select_related('user').first()
    if membership:
        kicked_username = membership.user.username
        membership.delete()
        messages.success(
            request,
            get_translation(
                'msg_team_kicked',
                'Mitglied "{username}" wurde aus dem Team entfernt.',
                username=kicked_username,
            ),
        )
    else:
        messages.error(
            request,
            get_translation('msg_team_member_not_found', 'Mitglied nicht gefunden.'),
        )

    return redirect('team_detail', slug=slug)



@login_required
@require_POST
def team_apply(request, slug):
    """
    Gast bewirbt sich für ein Team (Status = PENDING).
    """
    team = get_object_or_404(Team, slug=slug)

    if team.is_member(request.user):
        messages.info(
            request,
            get_translation('msg_team_apply_already_member', 'Du bist bereits Mitglied in diesem Team.'),
        )
        return redirect('team_detail', slug=slug)

    if team.is_in_active_tournament():
        messages.error(
            request,
            get_translation(
                'msg_team_apply_in_active_tournament',
                'Das Team "{team_name}" nimmt an einem laufenden Turnier teil. Bewerbungen sind während des Turniers nicht möglich.',
                team_name=team.name,
            ),
        )
        return redirect('team_detail', slug=slug)

    # Regel: Nur 1 aktives Team pro Spiel pro Gast
    if team.game:
        existing_membership = TeamMember.objects.filter(
            user=request.user,
            status=TeamMember.Status.ACCEPTED,
            team__game=team.game,
            team__is_archived=False,
        ).exclude(team=team).select_related('team').first()
        if existing_membership:
            messages.error(
                request,
                get_translation(
                    'msg_team_user_already_has_team',
                    'Du gehörst für das Spiel "{game_name}" bereits dem Team "{team_name}" an. Ein Gast darf nur einem Team pro Spiel angehören.',
                    game_name=team.game.name,
                    team_name=existing_membership.team.name,
                ),
            )
            return redirect('team_detail', slug=slug)

    if team.game and team.get_accepted_members().count() >= team.game.team_size:
        messages.error(
            request,
            get_translation(
                'msg_team_apply_full',
                'Das Team "{team_name}" ist bereits voll (maximal {max_players} Spieler für {game_name}).',
                team_name=team.name,
                max_players=team.game.team_size,
                game_name=team.game.name,
            ),
        )
        return redirect('team_detail', slug=slug)

    TeamMember.objects.get_or_create(
        team=team,
        user=request.user,
        defaults={
            'role': TeamMember.Role.MEMBER,
            'status': TeamMember.Status.PENDING,
        }
    )

    messages.success(
        request,
        get_translation(
            'msg_team_applied',
            'Bewerbung an Team "{team_name}" gesendet!',
            team_name=team.name,
        ),
    )
    return redirect('team_detail', slug=slug)


@login_required
@require_POST
def team_accept_membership(request, slug, membership_id):
    """
    Kapitän akzeptiert eine ausstehende Bewerbung.
    """
    with transaction.atomic():
        team = get_object_or_404(Team.objects.select_for_update(), slug=slug)

        if not team.is_captain(request.user) and not request.user.is_staff:
            messages.error(
                request,
                get_translation('msg_team_accept_forbidden', 'Nur der Kapitän kann Bewerbungen annehmen.'),
            )
            return redirect('team_detail', slug=slug)

        if team.is_in_active_tournament():
            messages.error(
                request,
                get_translation(
                    'msg_team_accept_in_active_tournament',
                    'Das Team "{team_name}" nimmt an einem laufenden Turnier teil. Beitritte sind während des Turniers nicht möglich.',
                    team_name=team.name,
                ),
            )
            return redirect('team_detail', slug=slug)

        if team.game and team.get_accepted_members().count() >= team.game.team_size:
            messages.error(
                request,
                get_translation(
                    'msg_team_accept_full',
                    'Das Team "{team_name}" hat die maximale Mitgliederanzahl ({max_players} Spieler) bereits erreicht.',
                    team_name=team.name,
                    max_players=team.game.team_size,
                ),
            )
            return redirect('team_detail', slug=slug)

        membership = get_object_or_404(TeamMember.objects.select_for_update(), id=membership_id, team=team)

        # Regel: Nur 1 aktives Team pro Spiel pro Gast
        if team.game:
            existing_membership = TeamMember.objects.filter(
                user=membership.user,
                status=TeamMember.Status.ACCEPTED,
                team__game=team.game,
                team__is_archived=False,
            ).exclude(team=team).select_related('team').first()
            if existing_membership:
                messages.error(
                    request,
                    get_translation(
                        'msg_team_applicant_already_has_team',
                        'Der Benutzer "{username}" gehört für das Spiel "{game_name}" bereits dem Team "{team_name}" an.',
                        username=membership.user.username,
                        game_name=team.game.name,
                        team_name=existing_membership.team.name,
                    ),
                )
                return redirect('team_detail', slug=slug)

        membership.status = TeamMember.Status.ACCEPTED
        membership.save(update_fields=['status'])

    messages.success(
        request,
        get_translation(
            'msg_team_application_accepted',
            'Bewerbung von "{username}" angenommen!',
            username=membership.user.username,
        ),
    )
    return redirect('team_detail', slug=slug)
