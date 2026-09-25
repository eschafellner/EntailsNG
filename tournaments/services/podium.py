"""Platzierungen abgeschlossener Turniere für UI und spätere Exporte."""

from tournaments.models import Tournament, TournamentMatch
from tournaments.services.standings import LeagueStandingService


class TournamentPodiumService:
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

        elif tournament.mode == Tournament.Mode.LEAGUE:
            if league_standings is None:
                league_standings = LeagueStandingService.calculate_league_standings(tournament)
            for place, standing in zip(podium, league_standings):
                podium[place] = standing['team']

        elif tournament.mode == Tournament.Mode.FFA:
            if ffa_participants is None:
                ffa_match = matches.filter(bracket_type=TournamentMatch.BracketType.FFA).first()
                ffa_participants = (
                    ffa_match.participants.select_related('team').order_by('rank', '-score', 'id')
                    if ffa_match else []
                )
            ranked = (participant for participant in ffa_participants if participant.rank)
            for place, participant in zip(podium, ranked):
                podium[place] = participant.team

        return podium
