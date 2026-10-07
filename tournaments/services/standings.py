import logging
from django.db import transaction
from tournaments.models import Team, Tournament, TournamentMatch
from .locking import lock_tournament, event_is_closed

logger = logging.getLogger(__name__)


def _calculate_standings_base(matches, teams, *, tiebreak=Tournament.Tiebreak.LEGACY,
                              withdrawn=None, seeds=None, group=False):
    """
    Gemeinsamer Kern zur Tabellenberechnung für Liga und Gruppenphase.
    Wertung: Sieg = 3 Pkt, Unentschieden = 1 Pkt, Niederlage = 0 Pkt.
    Gleichstandsregel nach Turniereinstellung; Rückzüge erhalten keinen Rang.
    Gruppen benötigen eindeutige Qualifikanten und verwenden zuletzt den Seed
    (bei historischen LEGACY-Turnieren den Teamnamen).
    """
    if not teams:
        return []
    matches = list(matches)
    withdrawn, seeds = set(withdrawn or ()), seeds or {}

    stats = {
        team.id: {
            'team': team,
            'played': 0,
            'won': 0,
            'drawn': 0,
            'lost': 0,
            'points': 0,
            'score_for': 0,
            'score_against': 0,
            'score_diff': 0,
            'head_to_head_points': {},
            'withdrawn': team.id in withdrawn,
        }
        for team in teams
    }

    for m in matches:
        if not m.team1 or not m.team2:
            continue
        if m.team1.id not in stats or m.team2.id not in stats:
            continue

        s1 = m.score_team1 if m.score_team1 is not None else 0
        s2 = m.score_team2 if m.score_team2 is not None else 0

        stats[m.team1.id]['played'] += 1
        stats[m.team2.id]['played'] += 1
        stats[m.team1.id]['score_for'] += s1
        stats[m.team1.id]['score_against'] += s2
        stats[m.team2.id]['score_for'] += s2
        stats[m.team2.id]['score_against'] += s1

        if m.winner == m.team1:
            stats[m.team1.id]['won'] += 1
            stats[m.team1.id]['points'] += 3
            stats[m.team2.id]['lost'] += 1
            stats[m.team1.id]['head_to_head_points'][m.team2.id] = 3
            stats[m.team2.id]['head_to_head_points'][m.team1.id] = 0
        elif m.winner == m.team2:
            stats[m.team2.id]['won'] += 1
            stats[m.team2.id]['points'] += 3
            stats[m.team1.id]['lost'] += 1
            stats[m.team2.id]['head_to_head_points'][m.team1.id] = 3
            stats[m.team1.id]['head_to_head_points'][m.team2.id] = 0
        else:
            stats[m.team1.id]['drawn'] += 1
            stats[m.team2.id]['drawn'] += 1
            stats[m.team1.id]['points'] += 1
            stats[m.team2.id]['points'] += 1
            stats[m.team1.id]['head_to_head_points'][m.team2.id] = 1
            stats[m.team2.id]['head_to_head_points'][m.team1.id] = 1

    for s in stats.values():
        s['score_diff'] = s['score_for'] - s['score_against']

    # Mini-table for teams tied on points. Use it only after every encounter
    # in the tied set is complete; partial results cannot decide the tiebreak.
    mini = {team_id: [0, 0, 0] for team_id in stats}
    if tiebreak == Tournament.Tiebreak.HEAD_TO_HEAD:
        for points in {row['points'] for row in stats.values()}:
            ids = {team_id for team_id, row in stats.items() if row['points'] == points and not row['withdrawn']}
            meetings = [m for m in matches if m.team1_id in ids and m.team2_id in ids]
            if len(meetings) != len(ids) * (len(ids) - 1) // 2:
                continue
            for m in meetings:
                for team_id, opponent_id, score, against in (
                    (m.team1_id, m.team2_id, m.score_team1 or 0, m.score_team2 or 0),
                    (m.team2_id, m.team1_id, m.score_team2 or 0, m.score_team1 or 0)):
                    mini[team_id][0] += 3 if m.winner_id == team_id else (1 if m.winner_id is None else 0)
                    mini[team_id][1] += score - against
                    mini[team_id][2] += score

    def sporting_key(row):
        direct = tuple(-value for value in mini[row['team'].pk]) if tiebreak == Tournament.Tiebreak.HEAD_TO_HEAD else ()
        return (-row['points'], *direct, -row['score_diff'], -row['score_for'])

    sorted_list = sorted(
        stats.values(),
        key=lambda s: (s['withdrawn'], *sporting_key(s),
                       seeds.get(s['team'].pk, s['team'].pk) if group and tiebreak != Tournament.Tiebreak.LEGACY
                       else s['team'].name.lower(), s['team'].pk)
    )

    previous, rank, active_index = None, 0, 0
    for item in sorted_list:
        if item['withdrawn']:
            item['rank'] = None
            continue
        active_index += 1
        key = sporting_key(item)
        # Group qualification uses seed as an explicit last criterion.
        if group or tiebreak == Tournament.Tiebreak.LEGACY or key != previous:
            rank = active_index
        item['rank'], previous = rank, key

    return sorted_list


class LeagueStandingService:
    @staticmethod
    def generate_round_robin_schedule(teams):
        """
        Erzeugt einen rundenbasierten Spielplan nach dem Berger-System (Circle-Methode).
        Rückgabe: Dict {round_num: [(team1, team2), ...]}
        """
        teams_list = list(teams)
        num_teams = len(teams_list)
        if num_teams < 2:
            return {}

        has_bye = (num_teams % 2 != 0)
        if has_bye:
            teams_list.append(None)

        n = len(teams_list)
        rounds_count = n - 1
        schedule = {}

        current_teams = list(teams_list)
        for r in range(1, rounds_count + 1):
            pairings = []
            for i in range(n // 2):
                t1 = current_teams[i]
                t2 = current_teams[n - 1 - i]
                if t1 is not None and t2 is not None:
                    if r % 2 == 1:
                        pairings.append((t1, t2))
                    else:
                        pairings.append((t2, t1))
            schedule[r] = pairings
            current_teams = [current_teams[0]] + [current_teams[-1]] + current_teams[1:-1]

        return schedule

    @staticmethod
    def calculate_league_standings(tournament):
        """
        Berechnet die dynamische Ligatabelle aus allen bisher gespielten Matches.
        """
        registrations = tournament.registrations.select_related('team').all()
        teams = [r.team for r in registrations]
        matches = tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.GROUP,
            status=TournamentMatch.Status.COMPLETED
        ).select_related('team1', 'team2', 'winner')
        return _calculate_standings_base(matches, teams, tiebreak=tournament.standings_tiebreak,
            withdrawn={r.team_id for r in registrations if r.is_forfeited})


class GroupStageStandingService:
    @staticmethod
    def calculate_group_standings(tournament, group_name):
        """
        Berechnet die Tabelle für eine spezifische Gruppe (z. B. 'Gruppe A' oder 'Gruppe B').
        """
        registrations = tournament.registrations.filter(group_name=group_name).select_related('team')
        teams = [r.team for r in registrations]
        if not teams:
            group_matches = tournament.matches.filter(group_name=group_name)
            team_ids = set()
            for m in group_matches:
                if m.team1_id:
                    team_ids.add(m.team1_id)
                if m.team2_id:
                    team_ids.add(m.team2_id)
            teams = list(Team.objects.filter(id__in=team_ids))

        matches = tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.GROUP,
            group_name=group_name,
            status=TournamentMatch.Status.COMPLETED
        ).select_related('team1', 'team2', 'winner')
        return _calculate_standings_base(matches, teams, tiebreak=tournament.standings_tiebreak,
            withdrawn={r.team_id for r in registrations if r.is_forfeited},
            seeds={r.team_id: r.seed or r.pk for r in registrations}, group=True)

    @staticmethod
    @transaction.atomic
    def check_and_advance_group_stage(tournament):
        """
        Prüft nach jedem Match, ob alle Gruppenspiele beendet sind.
        Falls ja, werden die Gruppenstände ermittelt und die qualifizierten Teams
        automatisch in die Halbfinals / das Finale eingetragen und auf READY gesetzt.
        """
        tournament = lock_tournament(tournament.pk)
        if event_is_closed(tournament) or tournament.status in (Tournament.Status.FINISHED, Tournament.Status.CANCELLED):
            return False
        group_matches = tournament.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP)
        if not group_matches.exists():
            return False

        if group_matches.exclude(status=TournamentMatch.Status.COMPLETED).exists():
            return False

        if tournament.playoffs_released_at:
            return False

        # Wenn Finalspiele bereits begonnen oder abgeschlossen wurden, nicht erneut überschreiben
        playoff_matches = tournament.matches.filter(bracket_type=TournamentMatch.BracketType.FINAL)
        if playoff_matches.filter(status__in=[TournamentMatch.Status.IN_PROGRESS, TournamentMatch.Status.COMPLETED]).exists():
            return False

        standings_a = GroupStageStandingService.calculate_group_standings(tournament, 'Gruppe A')
        standings_b = GroupStageStandingService.calculate_group_standings(tournament, 'Gruppe B')

        forfeited = set(tournament.registrations.filter(is_forfeited=True).values_list('team_id', flat=True))
        standings_a = [row for row in standings_a if row['team'].pk not in forfeited]
        standings_b = [row for row in standings_b if row['team'].pk not in forfeited]

        team_a1 = standings_a[0]['team'] if len(standings_a) > 0 else None
        team_a2 = standings_a[1]['team'] if len(standings_a) > 1 else None
        team_b1 = standings_b[0]['team'] if len(standings_b) > 0 else None
        team_b2 = standings_b[1]['team'] if len(standings_b) > 1 else None

        semi_matches = list(tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.FINAL,
            round_number=2
        ).order_by('match_number'))

        final_matches = list(tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.FINAL,
            round_number=3
        ).order_by('match_number'))

        if len(semi_matches) == 2 and len(final_matches) == 1:
            hf1 = semi_matches[0]
            hf2 = semi_matches[1]

            hf1.team1 = team_a1
            hf1.team2 = team_b2
            if hf1.team1 and hf1.team2:
                hf1.status = TournamentMatch.Status.READY
            hf1.save(update_fields=['team1', 'team2', 'status'])

            hf2.team1 = team_b1
            hf2.team2 = team_a2
            if hf2.team1 and hf2.team2:
                hf2.status = TournamentMatch.Status.READY
            hf2.save(update_fields=['team1', 'team2', 'status'])
            from .matches import check_and_advance_match
            check_and_advance_match(hf1)
            check_and_advance_match(hf2)
            return True

        if len(semi_matches) == 1:
            final_match = semi_matches[0]
            final_match.team1 = team_a1
            final_match.team2 = team_b1
            if final_match.team1 and final_match.team2:
                final_match.status = TournamentMatch.Status.READY
            final_match.save(update_fields=['team1', 'team2', 'status'])
            from .matches import check_and_advance_match
            check_and_advance_match(final_match)
            return True

        return False


check_and_advance_group_stage = GroupStageStandingService.check_and_advance_group_stage
