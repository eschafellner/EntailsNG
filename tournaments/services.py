import math
from django.db import transaction
from django.utils import timezone
from events.models import EventRegistration
from tournaments.models import (
    Game, Team, TeamMember, Tournament, TournamentMatch, TournamentRegistration
)


def check_user_event_checkin(user, event):
    """
    Prüft, ob der angegebene Benutzer für das aktive Event eingecheckt ist.
    """
    if not user or not user.is_authenticated or not event:
        return False
    return EventRegistration.objects.filter(
        user=user,
        event=event,
        is_checked_in=True
    ).exists()


def archive_teams_for_event(event):
    """
    Archiviert alle Teams, die der angegebenen Veranstaltung zugeordnet sind
    oder an Turnieren dieser Veranstaltung teilgenommen haben.
    """
    if not event:
        return 0
    direct_teams = Team.objects.filter(event=event, is_archived=False)
    tournament_teams = Team.objects.filter(
        tournament_registrations__tournament__event=event,
        is_archived=False
    )
    combined_ids = set(direct_teams.values_list('id', flat=True)) | set(tournament_teams.values_list('id', flat=True))
    count = Team.objects.filter(id__in=combined_ids).update(is_archived=True, event=event)
    return count



def get_or_create_solo_team(user, game):
    """
    Erstellt oder holt ein 1v1 Solo-Team für den angegebenen Benutzer und das angegebene Spiel.
    """
    team_name = f"{user.username} (Solo)"
    team = Team.objects.filter(captain=user, game=game, is_solo=True).first()
    if not team:
        team = Team.objects.create(
            name=team_name,
            game=game,
            captain=user,
            is_solo=True,
        )
        TeamMember.objects.get_or_create(
            team=team,
            user=user,
            defaults={
                'role': TeamMember.Role.CAPTAIN,
                'status': TeamMember.Status.ACCEPTED,
            }
        )
    return team


def next_power_of_two(n):
    if n <= 1:
        return 2
    return 1 << (n - 1).bit_length()


def advance_match_winner(match, winner_team, score1, score2):
    """
    Trägt das Spielergebnis ein und rückt den Sieger in das Folgematch vor.
    """
    with transaction.atomic():
        match.score_team1 = score1
        match.score_team2 = score2
        match.winner = winner_team

        if winner_team == match.team1:
            match.loser = match.team2
        elif winner_team == match.team2:
            match.loser = match.team1

        match.status = TournamentMatch.Status.COMPLETED
        match.save()

        # Sieger rückt weiter vor
        if match.next_match_winner:
            next_m = match.next_match_winner
            if not next_m.team1:
                next_m.team1 = winner_team
            elif not next_m.team2 and next_m.team1 != winner_team:
                next_m.team2 = winner_team

            if next_m.team1 and next_m.team2:
                next_m.status = TournamentMatch.Status.READY
            next_m.save()

        # Verlierer ins Loser Bracket setzen (bei Double Elimination)
        if match.next_match_loser and match.loser:
            next_l = match.next_match_loser
            if not next_l.team1:
                next_l.team1 = match.loser
            elif not next_l.team2 and next_l.team1 != match.loser:
                next_l.team2 = match.loser

            if next_l.team1 and next_l.team2:
                next_l.status = TournamentMatch.Status.READY
            next_l.save()


def generate_bracket(tournament, preview=False):
    """
    Hauptfunktion zur Generierung und Vorschau von Turnierbäumen für alle 5 Turniermodi.
    Wenn preview=True, werden keine Daten in die DB geschrieben, sondern ein Dict mit der Vorschau-Struktur geliefert.
    """
    teams = list(tournament.registrations.select_related('team').order_by('registered_at'))
    num_teams = len(teams)

    if tournament.mode == Tournament.Mode.FFA:
        return _generate_ffa(tournament, teams, preview)
    elif tournament.mode == Tournament.Mode.LEAGUE:
        return _generate_league(tournament, teams, preview)
    elif tournament.mode == Tournament.Mode.GROUP_STAGE:
        return _generate_group_stage(tournament, teams, preview)
    elif tournament.mode == Tournament.Mode.DOUBLE_ELIMINATION:
        return _generate_double_elimination(tournament, teams, preview)
    else:
        # Standard: SINGLE_ELIMINATION
        return _generate_single_elimination(tournament, teams, preview)


def _generate_single_elimination(tournament, registered_teams, preview=False):
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 2:
        if preview:
            return {'error': 'Mindestens 2 Teams erforderlich für Turnierbaum-Generierung.'}
        return False

    bracket_size = next_power_of_two(num_teams)
    num_rounds = int(math.log2(bracket_size))
    num_byes = bracket_size - num_teams

    # Struktur vorbereiten
    rounds_matches = []

    # Seeding-Slots auffüllen (Teams + BYEs)
    seeded_slots = teams + [None] * num_byes

    if preview:
        preview_rounds = []
        # Runde 1 Paarungen
        r1_matches = []
        for i in range(0, bracket_size, 2):
            t1 = seeded_slots[i]
            t2 = seeded_slots[i+1]
            is_bye = (t2 is None)
            r1_matches.append({
                'match_number': (i // 2) + 1,
                'team1': t1.name if t1 else 'TBD',
                'team2': t2.name if t2 else ('BYE' if is_bye else 'TBD'),
                'is_bye': is_bye,
                'status': 'COMPLETED' if is_bye else 'READY'
            })
        preview_rounds.append({'round': 1, 'name': 'Runde 1', 'matches': r1_matches})

        current_count = len(r1_matches)
        r_num = 2
        while current_count > 1:
            current_count = current_count // 2
            round_name = 'Finale' if current_count == 1 else ('Halbfinale' if current_count == 2 else f'Runde {r_num}')
            m_list = []
            for m_idx in range(1, current_count + 1):
                m_list.append({
                    'match_number': m_idx,
                    'team1': 'Sieger M' + str((m_idx*2)-1),
                    'team2': 'Sieger M' + str(m_idx*2),
                    'is_bye': False,
                    'status': 'PENDING'
                })
            preview_rounds.append({'round': r_num, 'name': round_name, 'matches': m_list})
            r_num += 1

        return {'mode': 'SINGLE_ELIMINATION', 'rounds': preview_rounds, 'total_teams': num_teams, 'byes': num_byes}

    # Echtes Speichern in DB
    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()

        # Erstelle Runden von hinten nach vorne (Finale zuerst) um FKs für next_match_winner setzen zu können
        round_matches_db = {}  # round_num -> list of match objects

        # Runde 1 bis Finalrunde initialisieren
        prev_round_matches = []
        for r in range(num_rounds, 0, -1):
            matches_in_round = 2 ** (num_rounds - r)
            round_matches_db[r] = []

            for m in range(matches_in_round):
                match_obj = TournamentMatch(
                    tournament=tournament,
                    round_number=r,
                    match_number=m + 1,
                    bracket_type=TournamentMatch.BracketType.FINAL if r == num_rounds else TournamentMatch.BracketType.WINNERS,
                    status=TournamentMatch.Status.PENDING,
                )
                if r < num_rounds:
                    # Nächstes Match zuweisen (Elternmatch)
                    match_obj.next_match_winner = round_matches_db[r + 1][m // 2]
                match_obj.save()
                round_matches_db[r].append(match_obj)

        # Runde 1 Teams & BYEs zuweisen
        r1_matches = round_matches_db[1]
        for i in range(0, bracket_size, 2):
            match_idx = i // 2
            m = r1_matches[match_idx]
            t1 = seeded_slots[i]
            t2 = seeded_slots[i + 1]

            m.team1 = t1
            m.team2 = t2

            if t2 is None:
                # Freilos -> t1 gewinnt automatisch und rückt vor
                m.is_bye = True
                m.winner = t1
                m.status = TournamentMatch.Status.COMPLETED
                m.save()

                if m.next_match_winner:
                    nm = m.next_match_winner
                    if not nm.team1:
                        nm.team1 = t1
                    elif not nm.team2:
                        nm.team2 = t1
                    nm.save()
            else:
                m.status = TournamentMatch.Status.READY
                m.save()

        tournament.is_generated = True
        tournament.status = Tournament.Status.IN_PROGRESS
        tournament.save(update_fields=['is_generated', 'status'])

    return True


def _generate_double_elimination(tournament, registered_teams, preview=False):
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 2:
        if preview:
            return {'error': 'Mindestens 2 Teams erforderlich für Double Elimination.'}
        return False

    # Ein vereinfachter Double Elimination Baum (Winners Bracket + Losers Bracket + Grand Finals)
    if preview:
        se_res = _generate_single_elimination(tournament, registered_teams, preview=True)
        se_res['mode'] = 'DOUBLE_ELIMINATION'
        se_res['has_loser_bracket'] = True
        return se_res

    # Für DB-Speicherung: Erst Single Elimination Winners Tree anlegen, dann Losers Bracket erweitern
    _generate_single_elimination(tournament, registered_teams, preview=False)

    # Loser Bracket Platzhalter-Matches hinzufügen
    with transaction.atomic():
        # Füge 1 Losers Bracket Match + 1 Grand Finale hinzu
        wb_final = TournamentMatch.objects.filter(tournament=tournament, round_number__gt=1).order_by('-round_number').first()

        loser_match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.LOSERS,
            status=TournamentMatch.Status.PENDING,
        )

        grand_final = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=99,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.FINAL,
            status=TournamentMatch.Status.PENDING,
        )

        if wb_final:
            wb_final.next_match_winner = grand_final
            wb_final.next_match_loser = loser_match
            wb_final.save()

        loser_match.next_match_winner = grand_final
        loser_match.save()

    return True


def _generate_league(tournament, registered_teams, preview=False):
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 2:
        if preview:
            return {'error': 'Mindestens 2 Teams erforderlich für Liga.'}
        return False

    # Jedes Team gegen jedes Team
    pairings = []
    for i in range(num_teams):
        for j in range(i + 1, num_teams):
            pairings.append((teams[i], teams[j]))

    if preview:
        matches_preview = []
        for idx, (t1, t2) in enumerate(pairings, 1):
            matches_preview.append({
                'match_number': idx,
                'team1': t1.name,
                'team2': t2.name,
                'status': 'READY'
            })
        return {'mode': 'LEAGUE', 'rounds': [{'round': 1, 'name': 'Alle Ligaspiele', 'matches': matches_preview}], 'total_teams': num_teams}

    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()
        for idx, (t1, t2) in enumerate(pairings, 1):
            TournamentMatch.objects.create(
                tournament=tournament,
                round_number=1,
                match_number=idx,
                bracket_type=TournamentMatch.BracketType.GROUP,
                team1=t1,
                team2=t2,
                status=TournamentMatch.Status.READY,
            )
        tournament.is_generated = True
        tournament.status = Tournament.Status.IN_PROGRESS
        tournament.save(update_fields=['is_generated', 'status'])

    return True


def _generate_group_stage(tournament, registered_teams, preview=False):
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 4:
        if preview:
            return {'error': 'Mindestens 4 Teams erforderlich für Gruppenphase.'}
        return False

    # Teile in 2 Gruppen auf
    group_a = teams[::2]
    group_b = teams[1::2]

    # Zuweisen in Registrierungen
    if not preview:
        with transaction.atomic():
            TournamentMatch.objects.filter(tournament=tournament).delete()

            for reg in registered_teams:
                if reg.team in group_a:
                    reg.group_name = 'Gruppe A'
                else:
                    reg.group_name = 'Gruppe B'
                reg.save(update_fields=['group_name'])

            # Gruppe A Matches
            for idx, (t1, t2) in enumerate([(group_a[i], group_a[j]) for i in range(len(group_a)) for j in range(i+1, len(group_a))], 1):
                TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=1,
                    match_number=idx,
                    bracket_type=TournamentMatch.BracketType.GROUP,
                    group_name='Gruppe A',
                    team1=t1,
                    team2=t2,
                    status=TournamentMatch.Status.READY,
                )

            # Gruppe B Matches
            for idx, (t1, t2) in enumerate([(group_b[i], group_b[j]) for i in range(len(group_b)) for j in range(i+1, len(group_b))], 1):
                TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=1,
                    match_number=idx,
                    bracket_type=TournamentMatch.BracketType.GROUP,
                    group_name='Gruppe B',
                    team1=t1,
                    team2=t2,
                    status=TournamentMatch.Status.READY,
                )

            # KO-Finale für Gruppensieger
            final_match = TournamentMatch.objects.create(
                tournament=tournament,
                round_number=2,
                match_number=1,
                bracket_type=TournamentMatch.BracketType.FINAL,
                status=TournamentMatch.Status.PENDING,
            )

            tournament.is_generated = True
            tournament.status = Tournament.Status.IN_PROGRESS
            tournament.save(update_fields=['is_generated', 'status'])

        return True

    return {
        'mode': 'GROUP_STAGE',
        'groups': {
            'Gruppe A': [t.name for t in group_a],
            'Gruppe B': [t.name for t in group_b],
        },
        'total_teams': num_teams,
    }


def _generate_ffa(tournament, registered_teams, preview=False):
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 2:
        if preview:
            return {'error': 'Mindestens 2 Teilnehmer erforderlich für FFA.'}
        return False

    if preview:
        return {
            'mode': 'FFA',
            'participants': [t.name for t in teams],
            'total_teams': num_teams,
        }

    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()
        TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.FFA,
            status=TournamentMatch.Status.IN_PROGRESS,
        )
        tournament.is_generated = True
        tournament.status = Tournament.Status.IN_PROGRESS
        tournament.save(update_fields=['is_generated', 'status'])

    return True
