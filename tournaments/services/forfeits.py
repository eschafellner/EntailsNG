import logging
from django.db import models, transaction

logger = logging.getLogger(__name__)


def forfeit_team_in_active_tournaments(team, reason="Walkover / Aufgabe"):
    """
    Wickelt alle offenen Matches eines Teams in generierten oder laufenden Turnieren
    als Walkover / Freilos für den jeweiligen Gegner ab, sodass der Turnierbaum
    nicht blockiert wird.
    """
    from tournaments.models import Tournament, TournamentMatch, TournamentMatchParticipant, TournamentRegistration
    from .matches import TournamentMatchService, check_and_advance_match

    with transaction.atomic():
        # 0. Turnieranmeldungen in aktiven Turnieren als aufgegeben markieren
        TournamentRegistration.objects.filter(
            team=team,
        ).exclude(
            tournament__status__in=[
                Tournament.Status.FINISHED,
                Tournament.Status.CANCELLED,
            ]
        ).update(is_forfeited=True)

        # 1. FFA-Matches
        TournamentMatchParticipant.objects.filter(
            team=team,
            match__status__in=[
                TournamentMatch.Status.PENDING,
                TournamentMatch.Status.READY,
                TournamentMatch.Status.IN_PROGRESS,
            ]
        ).update(is_disqualified=True)

        # 2. KO- / 1v1-Matches
        open_matches = list(
            TournamentMatch.objects.select_for_update().filter(
                models.Q(team1=team) | models.Q(team2=team),
                status__in=[
                    TournamentMatch.Status.PENDING,
                    TournamentMatch.Status.READY,
                    TournamentMatch.Status.IN_PROGRESS,
                ]
            ).order_by('round_number')
        )

        for match in open_matches:
            match.refresh_from_db()
            if match.status == TournamentMatch.Status.COMPLETED:
                continue

            opponent = match.team2 if match.team1 == team else match.team1
            if opponent:
                # Gegner gewinnt kampflos
                TournamentMatchService.update_match_score(
                    match_id=match.id,
                    score1=0 if match.team1 == team else 1,
                    score2=1 if match.team1 == team else 0,
                    winner_id=opponent.id,
                    decision_reason=reason,
                )
            else:
                # Noch kein Gegner vorhanden: Slot des forfeiting Teams leeren
                if match.team1 == team:
                    match.team1 = None
                if match.team2 == team:
                    match.team2 = None
                match.decision_reason = reason
                match.save(update_fields=['team1', 'team2', 'decision_reason'])
                check_and_advance_match(match)
