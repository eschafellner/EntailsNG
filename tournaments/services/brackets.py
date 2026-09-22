import math
from django.db import models, transaction

from tournaments.models import (
    Tournament,
    TournamentMatch,
    TournamentMatchParticipant,
)
from tournaments.exceptions import (
    TournamentBracketError,
    InsufficientTeamsError,
    BracketAlreadyGeneratedError,
)
from tournaments.services.standings import LeagueStandingService
from tournaments.services.matches import check_and_advance_match


def next_power_of_two(n):
    """Gibt die kleinste Zweierpotenz zurück, die >= n ist."""
    if n <= 1:
        return 2
    return 2 ** math.ceil(math.log2(n))


def generate_standard_seed_order(n):
    """
    Erzeugt die Standard-Seeding-Paarungsreihenfolge für eine Zweierpotenz n.
    Beispiel n=4: [1, 4, 2, 3] -> Paarungen (1, 4) und (2, 3)
    Beispiel n=8: [1, 8, 4, 5, 2, 7, 3, 6]
    """
    if n <= 1:
        return [1]
    rounds = int(math.log2(n))
    seeds = [1, 2]
    for _ in range(1, rounds):
        next_seeds = []
        next_sum = len(seeds) * 2 + 1
        for s in seeds:
            next_seeds.extend([s, next_sum - s])
        seeds = next_seeds
    return seeds


class TournamentBracketService:
    @staticmethod
    def generate_bracket(tournament_id, actor=None):
        """
        Atomare Generierung des Turnierbaums.
        Prüft Vorbedingungen, generiert Matches und setzt den Status erst bei absolutem Erfolg auf IN_PROGRESS.
        """
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().get(pk=tournament_id)

            if actor and not tournament.is_managed_by(actor):
                raise TournamentBracketError("Keine Berechtigung zur Generierung des Turnierbaums.")

            # 1. Prüfe ob bereits generiert
            if tournament.is_generated or tournament.status in [Tournament.Status.IN_PROGRESS, Tournament.Status.FINISHED]:
                raise BracketAlreadyGeneratedError(
                    f"Der Turnierbaum für '{tournament.title}' wurde bereits generiert und kann nicht erneut generiert werden."
                )

            # 2. Mindestanzahl Teams prüfen
            teams = list(tournament.registrations.select_related('team').order_by('registered_at'))
            num_teams = len(teams)
            if num_teams < 2:
                raise InsufficientTeamsError(
                    f"Für die Generierung des Turnierbaums sind mindestens 2 angemeldete Teams erforderlich (aktuell: {num_teams})."
                )

            # 3. Generierung der Matches
            success = generate_bracket(tournament, preview=False)
            if not success:
                raise TournamentBracketError("Die Generierung der Matches ist fehlgeschlagen.")

            # 4. Status auf IN_PROGRESS setzen
            tournament.is_generated = True
            tournament.status = Tournament.Status.IN_PROGRESS
            tournament.save(update_fields=['is_generated', 'status'])
            return True

    @staticmethod
    def reset_bracket(tournament_id, actor=None, force=False):
        """
        Setzt einen generierten Turnierbaum zurück und öffnet die Anmeldung wieder.
        Sicherheit: Nur möglich, wenn noch keine Matches mit Ergebnissen gespielt wurden (außer mit force=True).
        """
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().get(pk=tournament_id)

            if actor and not tournament.is_managed_by(actor):
                raise TournamentBracketError("Keine Berechtigung zum Zurücksetzen des Turnierbaums.")

            if not tournament.is_generated:
                raise TournamentBracketError(f"Für das Turnier '{tournament.title}' existiert noch kein generierter Turnierbaum.")

            completed_matches = TournamentMatch.objects.filter(
                tournament=tournament,
                status=TournamentMatch.Status.COMPLETED
            ).exclude(is_bye=True)

            if completed_matches.exists() and not force:
                raise TournamentBracketError(
                    "Der Turnierbaum kann nicht zurückgesetzt werden, da bereits Matches gespielt und gewertet wurden. "
                    "Ein Reset würde alle Spielergebnisse unwiderruflich löschen."
                )

            # Matches löschen und Status zurücksetzen
            TournamentMatch.objects.filter(tournament=tournament).delete()
            tournament.is_generated = False
            tournament.status = Tournament.Status.REGISTRATION_OPEN
            tournament.save(update_fields=['is_generated', 'status'])
            return True

    @staticmethod
    def get_bracket_preview(tournament_id):
        """
        Liefert eine unverbindliche Vorschau der Turnierbaum-Struktur ohne Datenbankmutation.
        """
        tournament = Tournament.objects.get(pk=tournament_id)
        return generate_bracket(tournament, preview=True)


def generate_bracket(tournament, preview=False):
    """
    Hauptfunktion zur Generierung und Vorschau von Turnierbäumen für alle 5 Turniermodi.
    Wenn preview=True, werden keine Daten in die DB geschrieben, sondern ein Dict mit der Vorschau-Struktur geliefert.
    """
    teams = list(
        tournament.registrations.select_related('team').order_by(
            models.F('seed').asc(nulls_last=True),
            'registered_at',
        )
    )
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

    seed_order = generate_standard_seed_order(bracket_size)
    seeded_slots = [teams[s - 1] if s <= num_teams else None for s in seed_order]

    if preview:
        preview_rounds = []
        r1_matches = []
        for i in range(0, bracket_size, 2):
            t1 = seeded_slots[i]
            t2 = seeded_slots[i + 1]
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
                    'team1': 'Sieger M' + str((m_idx * 2) - 1),
                    'team2': 'Sieger M' + str(m_idx * 2),
                    'is_bye': False,
                    'status': 'PENDING'
                })
            preview_rounds.append({'round': r_num, 'name': round_name, 'matches': m_list})
            r_num += 1

        return {'mode': 'SINGLE_ELIMINATION', 'rounds': preview_rounds, 'total_teams': num_teams, 'byes': num_byes}

    # Echtes Speichern in DB
    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()

        round_matches_db = {}  # round_num -> list of match objects

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
                    match_obj.next_match_winner = round_matches_db[r + 1][m // 2]
                    match_obj.next_match_winner_slot = 1 if (m % 2 == 0) else 2
                match_obj.save()
                round_matches_db[r].append(match_obj)

        r1_matches = round_matches_db[1]
        for i in range(0, bracket_size, 2):
            match_idx = i // 2
            m = r1_matches[match_idx]
            t1 = seeded_slots[i]
            t2 = seeded_slots[i + 1]

            m.team1 = t1
            m.team2 = t2

            if t2 is None:
                m.is_bye = True
                m.winner = t1
                m.status = TournamentMatch.Status.COMPLETED
                m.save()

                if m.next_match_winner:
                    nm = m.next_match_winner
                    if m.next_match_winner_slot == 1:
                        nm.team1 = t1
                    else:
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
    """
    Vollständige, mathematisch hergeleitete Double-Elimination-Baumerzeugung
    für beliebige Teilnehmerzahlen N >= 2 inkl. Nicht-Zweierpotenzen, BYE-Handling,
    deterministischer Slot-Verkettung und Grand Final / Reset.
    """
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 2:
        if preview:
            return {'error': 'Mindestens 2 Teams erforderlich für Double Elimination.'}
        return False

    bracket_size = next_power_of_two(num_teams)
    k = int(math.log2(bracket_size))
    num_byes = bracket_size - num_teams

    seed_order = generate_standard_seed_order(bracket_size)
    seeded_slots = [teams[s - 1] if s <= num_teams else None for s in seed_order]

    if preview:
        wb_rounds_preview = []
        for r in range(1, k + 1):
            m_count = 2 ** (k - r)
            m_list = []
            for m in range(1, m_count + 1):
                if r == 1:
                    t1 = seeded_slots[(m - 1) * 2]
                    t2 = seeded_slots[(m - 1) * 2 + 1]
                    is_bye = (t2 is None and t1 is not None)
                    m_list.append({
                        'match_number': m,
                        'team1': t1.name if t1 else 'TBD',
                        'team2': t2.name if t2 else ('BYE' if is_bye else 'TBD'),
                        'is_bye': is_bye,
                        'status': 'COMPLETED' if is_bye else 'READY'
                    })
                else:
                    m_list.append({
                        'match_number': m,
                        'team1': f"Sieger WB R{r-1} M{m*2-1}",
                        'team2': f"Sieger WB R{r-1} M{m*2}",
                        'is_bye': False,
                        'status': 'PENDING'
                    })
            r_name = "WB Finale" if r == k else f"WB Runde {r}"
            wb_rounds_preview.append({'round': r, 'name': r_name, 'matches': m_list})

        lb_rounds_preview = []
        if k >= 2:
            num_lb_rounds = 2 * (k - 1)
            for r in range(1, num_lb_rounds + 1):
                if r % 2 == 1:
                    m_count = 2 ** (k - 1 - (r + 1) // 2)
                    m_list = []
                    for m in range(1, m_count + 1):
                        if r == 1:
                            t1_desc = f"Verlierer WB R1 M{m*2-1}"
                            t2_desc = f"Verlierer WB R1 M{m*2}"
                        else:
                            t1_desc = f"Sieger LB R{r-1} M{m*2-1}"
                            t2_desc = f"Sieger LB R{r-1} M{m*2}"
                        m_list.append({
                            'match_number': m,
                            'team1': t1_desc,
                            'team2': t2_desc,
                            'is_bye': False,
                            'status': 'PENDING'
                        })
                else:
                    m_count = 2 ** (k - 1 - r // 2)
                    wb_feed_round = (r // 2) + 1
                    m_list = []
                    for m in range(1, m_count + 1):
                        m_list.append({
                            'match_number': m,
                            'team1': f"Sieger LB R{r-1} M{m}",
                            'team2': f"Verlierer WB R{wb_feed_round} M{m}",
                            'is_bye': False,
                            'status': 'PENDING'
                        })
                r_name = "LB Finale" if r == num_lb_rounds else f"LB Runde {r}"
                lb_rounds_preview.append({'round': r, 'name': r_name, 'matches': m_list})

        gf_matches = [{
            'match_number': 1,
            'team1': "Sieger Winner Bracket",
            'team2': "Sieger Loser Bracket" if k >= 2 else "Verlierer WB R1",
            'is_bye': False,
            'status': 'PENDING'
        }]

        return {
            'mode': 'DOUBLE_ELIMINATION',
            'wb_rounds': wb_rounds_preview,
            'lb_rounds': lb_rounds_preview,
            'grand_final': gf_matches,
            'total_teams': num_teams,
            'byes': num_byes,
        }

    # DB Erzeugung
    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()

        # 1. Grand Final Match initialisieren
        grand_final = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.GRAND_FINAL,
            status=TournamentMatch.Status.PENDING,
        )

        # Sonderfall N = 2
        if k == 1:
            wb_final = TournamentMatch.objects.create(
                tournament=tournament,
                round_number=1,
                match_number=1,
                bracket_type=TournamentMatch.BracketType.WINNERS,
                team1=teams[0],
                team2=teams[1],
                status=TournamentMatch.Status.READY,
                next_match_winner=grand_final,
                next_match_winner_slot=1,
                next_match_loser=grand_final,
                next_match_loser_slot=2,
            )
            tournament.is_generated = True
            tournament.status = Tournament.Status.IN_PROGRESS
            tournament.save(update_fields=['is_generated', 'status'])
            return True

        # Für N >= 4 (k >= 2):
        # 2. Winner Bracket Matches (r = 1 .. k)
        wb_matches = {}
        for r in range(1, k + 1):
            m_count = 2 ** (k - r)
            wb_matches[r] = {}
            for m in range(1, m_count + 1):
                match_obj = TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=r,
                    match_number=m,
                    bracket_type=TournamentMatch.BracketType.WINNERS,
                    status=TournamentMatch.Status.PENDING,
                )
                wb_matches[r][m] = match_obj

        # 3. Loser Bracket Matches (r = 1 .. 2(k - 1))
        num_lb_rounds = 2 * (k - 1)
        lb_matches = {}
        for r in range(1, num_lb_rounds + 1):
            if r % 2 == 1:
                m_count = 2 ** (k - 1 - (r + 1) // 2)
            else:
                m_count = 2 ** (k - 1 - r // 2)
            lb_matches[r] = {}
            for m in range(1, m_count + 1):
                match_obj = TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=r,
                    match_number=m,
                    bracket_type=TournamentMatch.BracketType.LOSERS,
                    status=TournamentMatch.Status.PENDING,
                )
                lb_matches[r][m] = match_obj

        # 4. Verknüpfungen für Winner Bracket (Sieger -> nächstes WB Match / Grand Final)
        for r in range(1, k + 1):
            m_count = 2 ** (k - r)
            for m in range(1, m_count + 1):
                match_obj = wb_matches[r][m]
                if r < k:
                    match_obj.next_match_winner = wb_matches[r + 1][(m + 1) // 2]
                    match_obj.next_match_winner_slot = 1 if (m % 2 == 1) else 2
                else:
                    match_obj.next_match_winner = grand_final
                    match_obj.next_match_winner_slot = 1

        # 5. Verknüpfungen für Loser Bracket (Sieger -> nächstes LB Match / Grand Final)
        for r in range(1, num_lb_rounds + 1):
            m_count = len(lb_matches[r])
            for m in range(1, m_count + 1):
                match_obj = lb_matches[r][m]
                if r < num_lb_rounds:
                    if r % 2 == 1:
                        match_obj.next_match_winner = lb_matches[r + 1][m]
                        match_obj.next_match_winner_slot = 1
                    else:
                        match_obj.next_match_winner = lb_matches[r + 1][(m + 1) // 2]
                        match_obj.next_match_winner_slot = 1 if (m % 2 == 1) else 2
                else:
                    match_obj.next_match_winner = grand_final
                    match_obj.next_match_winner_slot = 2

        # 6. Einspeisung aus Winner Bracket ins Loser Bracket (Verlierer -> LB)
        # 6.1 WB Runde 1 -> LB Runde 1
        for m in range(1, (2 ** (k - 1)) + 1):
            wb_m = wb_matches[1][m]
            wb_m.next_match_loser = lb_matches[1][(m + 1) // 2]
            wb_m.next_match_loser_slot = 1 if (m % 2 == 1) else 2

        # 6.2 WB Runde 2 .. k-1 -> LB Major Runden (LB Runde 2, 4, 6, ...)
        for i in range(1, k - 1):
            wb_round = i + 1
            lb_round = 2 * i
            m_count = 2 ** (k - wb_round)
            for m in range(1, m_count + 1):
                wb_m = wb_matches[wb_round][m]
                wb_m.next_match_loser = lb_matches[lb_round][m]
                wb_m.next_match_loser_slot = 2

        # 6.3 WB Finale (WB Runde k, Match 1) -> LB Finale (LB Runde 2(k-1), Match 1)
        wb_final = wb_matches[k][1]
        lb_final = lb_matches[num_lb_rounds][1]
        wb_final.next_match_loser = lb_final
        wb_final.next_match_loser_slot = 2

        # Alle Matches speichern
        for r_dict in wb_matches.values():
            for m_obj in r_dict.values():
                m_obj.save()
        for r_dict in lb_matches.values():
            for m_obj in r_dict.values():
                m_obj.save()

        # 7. Teams und Freilose in WB Runde 1 setzen
        for m in range(1, (bracket_size // 2) + 1):
            match_obj = wb_matches[1][m]
            t1 = seeded_slots[(m - 1) * 2]
            t2 = seeded_slots[(m - 1) * 2 + 1]

            match_obj.team1 = t1
            match_obj.team2 = t2

            if t1 and t2:
                match_obj.status = TournamentMatch.Status.READY
                match_obj.save(update_fields=['team1', 'team2', 'status'])
            elif t1 and not t2:
                match_obj.is_bye = True
                match_obj.winner = t1
                match_obj.loser = None
                match_obj.score_team1 = 0
                match_obj.score_team2 = 0
                match_obj.status = TournamentMatch.Status.COMPLETED
                match_obj.save(update_fields=['team1', 'team2', 'is_bye', 'winner', 'loser', 'score_team1', 'score_team2', 'status'])

                # t1 direkt ins WB Folgematch rücken
                target_wb = match_obj.next_match_winner
                if target_wb:
                    if match_obj.next_match_winner_slot == 1:
                        target_wb.team1 = t1
                    else:
                        target_wb.team2 = t1
                    if target_wb.team1 and target_wb.team2:
                        target_wb.status = TournamentMatch.Status.READY
                    target_wb.save()

                # Prüfen, ob das Ziel-LB-Match von diesem BYE betroffen ist
                if match_obj.next_match_loser:
                    check_and_advance_match(match_obj.next_match_loser)
            elif not t1 and not t2:
                match_obj.is_bye = True
                match_obj.status = TournamentMatch.Status.COMPLETED
                match_obj.save(update_fields=['team1', 'team2', 'is_bye', 'status'])
                if match_obj.next_match_loser:
                    check_and_advance_match(match_obj.next_match_loser)

        # Initialer Durchlauf für alle LB-Matches der 1. Runde
        for m_obj in lb_matches[1].values():
            check_and_advance_match(m_obj)

        tournament.is_generated = True
        tournament.status = Tournament.Status.IN_PROGRESS
        tournament.save(update_fields=['is_generated', 'status'])

    return True


def _generate_league(tournament, registered_teams, preview=False):
    """
    Erzeugt einen vollständigen rundenbasierten Liga-Spielplan nach dem Berger-System (Round Robin).
    """
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 2:
        if preview:
            return {'error': 'Mindestens 2 Teams erforderlich für Liga.'}
        return False

    schedule = LeagueStandingService.generate_round_robin_schedule(teams)

    if preview:
        rounds_preview = []
        for r_num, pairings in schedule.items():
            matches_list = []
            for m_idx, (t1, t2) in enumerate(pairings, 1):
                matches_list.append({
                    'match_number': m_idx,
                    'team1': t1.name if t1 else 'BYE',
                    'team2': t2.name if t2 else 'BYE',
                    'status': 'READY'
                })
            rounds_preview.append({
                'round': r_num,
                'name': f"Spieltag {r_num}",
                'matches': matches_list
            })
        return {
            'mode': 'LEAGUE',
            'rounds': rounds_preview,
            'total_teams': num_teams
        }

    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()

        for r_num, pairings in schedule.items():
            for m_idx, (t1, t2) in enumerate(pairings, 1):
                TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=r_num,
                    match_number=m_idx,
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
    """
    Erzeugt eine Gruppenphase (Gruppe A & B) mit anschließendem KO-Baum (Halbfinale/Finale).
    """
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 4:
        if preview:
            return {'error': 'Mindestens 4 Teams erforderlich für Gruppenphase.'}
        return False

    # Snake-Verteilung in Gruppe A und B
    group_a = [teams[i] for i in range(len(teams)) if i % 2 == 0]
    group_b = [teams[i] for i in range(len(teams)) if i % 2 == 1]

    schedule_a = LeagueStandingService.generate_round_robin_schedule(group_a)
    schedule_b = LeagueStandingService.generate_round_robin_schedule(group_b)

    has_semifinals = (num_teams >= 8)

    if preview:
        groups_preview = {
            'Gruppe A': [t.name for t in group_a],
            'Gruppe B': [t.name for t in group_b],
        }
        ko_preview = []
        if has_semifinals:
            ko_preview.append({
                'round': 2,
                'name': 'Halbfinale',
                'matches': [
                    {'match_number': 1, 'team1': '1. Gruppe A', 'team2': '2. Gruppe B', 'status': 'PENDING'},
                    {'match_number': 2, 'team1': '1. Gruppe B', 'team2': '2. Gruppe A', 'status': 'PENDING'},
                ]
            })
            ko_preview.append({
                'round': 3,
                'name': 'Finale',
                'matches': [
                    {'match_number': 1, 'team1': 'Sieger Halbfinale 1', 'team2': 'Sieger Halbfinale 2', 'status': 'PENDING'}
                ]
            })
        else:
            ko_preview.append({
                'round': 2,
                'name': 'Finale',
                'matches': [
                    {'match_number': 1, 'team1': '1. Gruppe A', 'team2': '1. Gruppe B', 'status': 'PENDING'}
                ]
            })

        return {
            'mode': 'GROUP_STAGE',
            'groups': groups_preview,
            'ko_stage': ko_preview,
            'total_teams': num_teams,
        }

    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()

        # 1. Gruppen-Zugehörigkeit in Registrierungen hinterlegen
        for reg in registered_teams:
            if reg.team in group_a:
                reg.group_name = 'Gruppe A'
            else:
                reg.group_name = 'Gruppe B'
            reg.save(update_fields=['group_name'])

        # 2. Gruppe A Matches erstellen
        for r_num, pairings in schedule_a.items():
            for m_idx, (t1, t2) in enumerate(pairings, 1):
                TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=r_num,
                    match_number=m_idx,
                    bracket_type=TournamentMatch.BracketType.GROUP,
                    group_name='Gruppe A',
                    team1=t1,
                    team2=t2,
                    status=TournamentMatch.Status.READY,
                )

        # 3. Gruppe B Matches erstellen
        for r_num, pairings in schedule_b.items():
            for m_idx, (t1, t2) in enumerate(pairings, 1):
                TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=r_num,
                    match_number=m_idx,
                    bracket_type=TournamentMatch.BracketType.GROUP,
                    group_name='Gruppe B',
                    team1=t1,
                    team2=t2,
                    status=TournamentMatch.Status.READY,
                )

        # 4. KO-Phase erstellen
        if has_semifinals:
            # Finale anlegen (Runde 3)
            final_match = TournamentMatch.objects.create(
                tournament=tournament,
                round_number=3,
                match_number=1,
                bracket_type=TournamentMatch.BracketType.FINAL,
                status=TournamentMatch.Status.PENDING,
            )
            # Halbfinale 1 & 2 anlegen (Runde 2)
            TournamentMatch.objects.create(
                tournament=tournament,
                round_number=2,
                match_number=1,
                bracket_type=TournamentMatch.BracketType.FINAL,
                status=TournamentMatch.Status.PENDING,
                next_match_winner=final_match,
                next_match_winner_slot=1,
            )
            TournamentMatch.objects.create(
                tournament=tournament,
                round_number=2,
                match_number=2,
                bracket_type=TournamentMatch.BracketType.FINAL,
                status=TournamentMatch.Status.PENDING,
                next_match_winner=final_match,
                next_match_winner_slot=2,
            )
        else:
            # Direktes Finale (Runde 2)
            TournamentMatch.objects.create(
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


def _generate_ffa(tournament, registered_teams, preview=False):
    """
    Erzeugt ein Free For All (FFA) Match mit n Teilnehmern via TournamentMatchParticipant.
    """
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

        ffa_match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.FFA,
            status=TournamentMatch.Status.READY,
        )

        for team in teams:
            TournamentMatchParticipant.objects.create(
                match=ffa_match,
                team=team,
            )

        tournament.is_generated = True
        tournament.status = Tournament.Status.IN_PROGRESS
        tournament.save(update_fields=['is_generated', 'status'])

    return True
