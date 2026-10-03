"""HTTP actions for captain recruitment and personal invitations."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from clans.models import ClanMembership
from configuration.translations import get_translation
from tournaments.exceptions import TournamentError
from tournaments.models import Team, TeamInvitation, TeamMember
from tournaments.services import recruitment


def recruitment_context(team, user, active_event, query):
    context = {'can_recruit': False, 'recruitment_query': query.strip()[:150]}
    if not team.is_captain(user):
        return context
    context['sent_invitations'] = team.invitations.filter(status=TeamInvitation.Status.PENDING,
        user__is_active=True, user__deleted_at__isnull=True).select_related('user', 'invited_by')
    try:
        recruitment.validate_recruitment(team, active_event)
        recruitment.validate_capacity(team, 1)
    except TournamentError as error:
        context['recruitment_disabled_reason'] = str(error)
        return context
    context['can_recruit'] = True
    membership = ClanMembership.get_user_active_membership(user)
    context['recruitment_clan'] = membership.clan if membership else None
    players = recruitment.eligible_players(team)
    clan_ids = set(ClanMembership.objects.filter(clan=membership.clan,
        status=ClanMembership.Status.ACCEPTED).values_list('user_id', flat=True)) if membership else set()
    context['available_clan_members'] = players.filter(pk__in=clan_ids)
    if len(context['recruitment_query']) >= 2:
        matches = players.filter(username__icontains=context['recruitment_query']).exclude(
            pk__in=team.invitations.filter(status=TeamInvitation.Status.PENDING).values('user_id'))
        matches = matches.exclude(pk__in=team.memberships.filter(status=TeamMember.Status.PENDING).values('user_id'))
        context['recruitment_results'] = [{'user': player, 'same_clan': player.pk in clan_ids}
            for player in matches[:20]]
        context['recruitment_searched'] = True
    return context


@login_required
@require_POST
def team_add_clan_members(request, slug):
    team = get_object_or_404(Team, slug=slug)
    try:
        count = recruitment.add_clan_members(team.pk, request.user, request.POST.getlist('user_ids'))
    except TournamentError as error:
        messages.error(request, str(error))
    except Team.DoesNotExist:
        raise Http404
    else:
        messages.success(request, get_translation('team_recruit_added', count=count))
    return redirect('team_detail', slug=slug)


@login_required
@require_POST
def team_recruit_player(request, slug):
    team = get_object_or_404(Team, slug=slug)
    try:
        result, user = recruitment.recruit_player(team.pk, request.user, request.POST.get('user_id'))
    except TournamentError as error:
        messages.error(request, str(error))
    except Team.DoesNotExist:
        raise Http404
    else:
        messages.success(request, get_translation('team_recruit_added', count=1) if result == 'added'
            else get_translation('team_recruit_invited', username=user.display_name))
    return redirect('team_detail', slug=slug)


def invitation_response(request, slug, invitation_id, action):
    team = get_object_or_404(Team, slug=slug)
    try:
        recruitment.respond_to_invitation(team.pk, request.user, invitation_id, action)
    except TournamentError as error:
        messages.error(request, str(error))
    except (Team.DoesNotExist, TeamInvitation.DoesNotExist):
        raise Http404
    else:
        key = {'accept': 'team_invitation_accepted', 'decline': 'team_invitation_declined',
            'withdraw': 'team_invitation_withdrawn'}[action]
        messages.success(request, get_translation(key, team_name=team.name))
    return redirect('team_detail', slug=slug) if action == 'withdraw' else redirect('team_list')


@login_required
@require_POST
def team_accept_invitation(request, slug, invitation_id):
    return invitation_response(request, slug, invitation_id, 'accept')


@login_required
@require_POST
def team_decline_invitation(request, slug, invitation_id):
    return invitation_response(request, slug, invitation_id, 'decline')


@login_required
@require_POST
def team_withdraw_invitation(request, slug, invitation_id):
    return invitation_response(request, slug, invitation_id, 'withdraw')


@login_required
@require_POST
def team_reject_application(request, slug, membership_id):
    team = get_object_or_404(Team, slug=slug)
    try:
        recruitment.reject_application(team.pk, request.user, membership_id)
    except TournamentError as error:
        messages.error(request, str(error))
    except (Team.DoesNotExist, TeamMember.DoesNotExist):
        raise Http404
    else:
        messages.success(request, get_translation('team_application_declined'))
    return redirect('team_detail', slug=slug)
