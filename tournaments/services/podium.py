"""Platzierungen abgeschlossener Turniere für UI und spätere Exporte."""

from tournaments.models import Tournament, TournamentMatch
from tournaments.services.standings import LeagueStandingService


class TournamentPodiumService:
    @staticmethod
    def placements(tournament, *, swiss_standings=None):
        """All placements, including shared Swiss ranks, for UI and certificates."""
        if not tournament.is_generated or tournament.status != Tournament.Status.FINISHED:
            return []
        if tournament.mode == Tournament.Mode.SWISS:
            from .swiss import SwissStandingService
            rows = swiss_standings if swiss_standings is not None else SwissStandingService.calculate(tournament)
            return [{'rank': row['rank'], 'team': row['team']} for row in rows if row['rank'] is not None]
        if tournament.mode == Tournament.Mode.LEAGUE:
            return [{'rank': row['rank'], 'team': row['team']}
                    for row in LeagueStandingService.calculate_league_standings(tournament) if row['rank'] is not None]
        if tournament.mode == Tournament.Mode.FFA:
            participants = tournament.matches.filter(bracket_type=TournamentMatch.BracketType.FFA).first()
            return [{'rank': p.rank, 'team': p.team} for p in
                    participants.participants.filter(is_disqualified=False, rank__isnull=False).select_related('team').order_by('rank', 'pk')] if participants else []
        return [{'rank': number, 'team': team} for number, team in
                enumerate(TournamentPodiumService.calculate(tournament).values(), 1) if team is not None]

    @staticmethod
    def calculate(tournament, *, league_standings=None, ffa_participants=None):
        """Liefert die Podiums-Teams; unbekannte Plätze bleiben ``None``.

        Bereits für eine Ansicht berechnete Tabellen und FFA-Teilnehmer können
        übergeben werden. Ohne sie ist der Service eigenständig nutzbar.
        """
        podium = {'first': None, 'second': None, 'third': None}
        if not tournament.is_generated or tournament.status != Tournament.Status.FINISHED:
            return podium

        matches = tournament.matches.select_related('team1', 'team2', 'winner', 'loser')

        if tournament.mode == Tournament.Mode.DOUBLE_ELIMINATION:
            final = matches.filter(
                bracket_type__in=[
                    TournamentMatch.BracketType.GRAND_FINAL_RESET,
                    TournamentMatch.BracketType.GRAND_FINAL,
                ],
                status=TournamentMatch.Status.COMPLETED,
            ).order_by('-round_number', '-id').first()
            if final and final.winner:
                podium['first'] = final.winner
                podium['second'] = final.team2 if final.winner == final.team1 else final.team1

            loser_final = matches.filter(
                bracket_type=TournamentMatch.BracketType.LOSERS,
                status=TournamentMatch.Status.COMPLETED,
            ).order_by('-round_number', '-match_number').first()
            if loser_final and loser_final.loser:
                podium['third'] = loser_final.loser

        elif tournament.mode in (Tournament.Mode.SINGLE_ELIMINATION, Tournament.Mode.GROUP_STAGE):
            finals = matches.filter(
                bracket_type=TournamentMatch.BracketType.FINAL,
                status=TournamentMatch.Status.COMPLETED,
            )
            if tournament.mode == Tournament.Mode.GROUP_STAGE:
                finals = finals.order_by('-round_number')
            final = finals.first()
            if final and final.winner:
                podium['first'] = final.winner
                podium['second'] = final.loser
            bronze = matches.filter(bracket_type=TournamentMatch.BracketType.THIRD_PLACE,
                                    status=TournamentMatch.Status.COMPLETED).first()
            if bronze:
                podium['third'] = bronze.winner

        elif tournament.mode == Tournament.Mode.SWISS:
            # Legacy consumers must never invent a unique winner from a shared rank.
            places = TournamentPodiumService.placements(tournament)
            for key, number in zip(podium, (1, 2, 3)):
                teams = [p['team'] for p in places if p['rank'] == number]
                podium[key] = teams[0] if len(teams) == 1 else None

        elif tournament.mode == Tournament.Mode.LEAGUE:
            if league_standings is None:
                league_standings = LeagueStandingService.calculate_league_standings(tournament)
            for place, number in zip(podium, (1, 2, 3)):
                teams = [row['team'] for row in league_standings if row['rank'] == number]
                podium[place] = teams[0] if len(teams) == 1 else None

        elif tournament.mode == Tournament.Mode.FFA:
            if ffa_participants is None:
                ffa_match = matches.filter(bracket_type=TournamentMatch.BracketType.FFA).first()
                ffa_participants = (
                    ffa_match.participants.select_related('team').order_by('rank', '-score', 'id')
                    if ffa_match else []
                )
            places = {1: 'first', 2: 'second', 3: 'third'}
            participants = list(ffa_participants)
            for rank, place in places.items():
                teams = [p.team for p in participants if p.rank == rank and not p.is_disqualified]
                podium[place] = teams[0] if len(teams) == 1 else None

        return podium
