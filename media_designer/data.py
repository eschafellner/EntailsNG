"""Explizit freigegebene Seriendruckdaten für Medienvorlagen."""

from clans.models import ClanMembership
from configuration.translations import get_translation
from tournaments.services import TournamentPodiumService


def badge_rows(registrations, event):
    registrations = list(registrations)
    memberships = ClanMembership.objects.filter(
        user_id__in=[registration.user_id for registration in registrations],
        status=ClanMembership.Status.ACCEPTED,
    ).select_related('clan')
    clans = {membership.user_id: membership.clan.name for membership in memberships}
    return [
        {
            'guest.username': registration.user.username,
            'guest.clan': clans.get(registration.user_id, ''),
            'guest.seat': ', '.join(
                seat.seat_label or f'{seat.x}/{seat.y}' for seat in registration.seats.all()
            ),
            'event.title': event.title,
        }
        for registration in registrations
    ]


def certificate_rows(teams, tournament, award_title):
    podium = TournamentPodiumService.calculate(tournament)
    placements = {
        team.pk: get_translation('media_place', '{number}. Platz', number=number)
        for number, team in enumerate(podium.values(), 1) if team is not None
    }
    return [
        {
            'team.name': team.name,
            'team.placement': placements.get(team.pk, ''),
            'award.title': award_title,
            'tournament.title': tournament.title,
            'event.title': tournament.event.title,
        }
        for team in teams
    ]
