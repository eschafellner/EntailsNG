import logging
from tournaments.models import Team, TournamentMatch

logger = logging.getLogger(__name__)


def _calculate_standings_base(matches, teams):
    """
    Gemeinsamer Kern zur Tabellenberechnung für Liga und Gruppenphase.
    Wertung: Sieg = 3 Pkt, Unentschieden = 1 Pkt, Niederlage = 0 Pkt.
    Tiebreak: 1. Punkte, 2. Tordifferenz / Score-Diff, 3. Erzielte Scores, 4. Teamname.
    """
    if not teams:
        return []

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

    sorted_list = sorted(
        stats.values(),
        key=lambda s: (
            -s['points'],
            -s['score_diff'],
            -s['score_for'],
            s['team'].name.lower(),
        )
    )

    for idx, item in enumerate(sorted_list, 1):
        item['rank'] = idx

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
        return _calculate_standings_base(matches, teams)


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
        return _calculate_standings_base(matches, teams)

    @staticmethod
    def check_and_advance_group_stage(tournament):
        """
        Prüft nach jedem Match, ob alle Gruppenspiele beendet sind.
        Falls ja, werden die Gruppenstände ermittelt und die qualifizierten Teams
        automatisch in die Halbfinals / das Finale eingetragen und auf READY gesetzt.
        """
        group_matches = tournament.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP)
        if not group_matches.exists():
            return False

        if group_matches.exclude(status=TournamentMatch.Status.COMPLETED).exists():
            return False

        # Wenn Finalspiele bereits begonnen oder abgeschlossen wurden, nicht erneut überschreiben
        playoff_matches = tournament.matches.filter(bracket_type=TournamentMatch.BracketType.FINAL)
        if playoff_matches.filter(status__in=[TournamentMatch.Status.IN_PROGRESS, TournamentMatch.Status.COMPLETED]).exists():
            return False

        standings_a = GroupStageStandingService.calculate_group_standings(tournament, 'Gruppe A')
        standings_b = GroupStageStandingService.calculate_group_standings(tournament, 'Gruppe B')

        if not standings_a or not standings_b:
            return False

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
            return True

        if len(semi_matches) == 1:
            final_match = semi_matches[0]
            final_match.team1 = team_a1
            final_match.team2 = team_b1
            if final_match.team1 and final_match.team2:
                final_match.status = TournamentMatch.Status.READY
            final_match.save(update_fields=['team1', 'team2', 'status'])
            return True

        return False


check_and_advance_group_stage = GroupStageStandingService.check_and_advance_group_stage
