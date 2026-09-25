"""Explizit freigegebene Seriendruckdaten für Medienvorlagen."""

from clans.models import ClanMembership
from configuration.translations import get_translation
from django.utils import timezone
from tournaments.models import TeamMember
from tournaments.services import TournamentPodiumService


def event_values(event):
    return {
        'event.title': event.title,
        'event.start_date': timezone.localtime(event.start_date).strftime('%d.%m.%Y %H:%M'),
        'event.end_date': timezone.localtime(event.end_date).strftime('%d.%m.%Y %H:%M'),
    }


def badge_rows(registrations, event):
    registrations = list(registrations)
    memberships = ClanMembership.objects.filter(
        user_id__in=[registration.user_id for registration in registrations],
        status=ClanMembership.Status.ACCEPTED,
    ).select_related('clan')
    clans = {membership.user_id: membership.clan.name for membership in memberships}
    event_fields = event_values(event)
    return [
        {
            'guest.username': registration.user.username,
            'guest.clan': clans.get(registration.user_id, ''),
            'guest.seat': ', '.join(
                seat.seat_label or f'{seat.x}/{seat.y}' for seat in registration.seats.all()
            ),
            **event_fields,
        }
        for registration in registrations
    ]


def certificate_rows(teams, tournament, award_title):
    teams = list(teams)
    podium = TournamentPodiumService.calculate(tournament)
    placements = {
        team.pk: get_translation('media_place', '{number}. Platz', number=number)
        for number, team in enumerate(podium.values(), 1) if team is not None
    }
    members_by_team = {team.pk: [] for team in teams}
    memberships = TeamMember.objects.filter(
        team_id__in=members_by_team, status=TeamMember.Status.ACCEPTED,
    ).select_related('user').order_by('team_id', 'joined_at', 'id')
    for membership in memberships:
        members_by_team[membership.team_id].append(membership.user.username)
    event_fields = event_values(tournament.event)
    return [
        {
            'team.name': team.name,
            'team.members': '\n'.join(members_by_team[team.pk]),
            'team.placement': placements.get(team.pk, ''),
            'award.title': award_title,
            'tournament.title': tournament.title,
            **event_fields,
        }
        for team in teams
    ]
