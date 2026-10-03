"""Captain recruitment with the same User -> Event -> Team lock order as roster actions."""
from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone

from clans.models import ClanMembership
from configuration.translations import get_translation
from events.models import Event
from tournaments.exceptions import TournamentError
from tournaments.models import Team, TeamInvitation, TeamMember, Tournament, TournamentRegistration
from .validation import identifier


def current_recruitment_teams(active_event):
    teams = Team.objects.filter(is_archived=False, is_solo=False,
        captain__is_active=True, captain__deleted_at__isnull=True)
    if active_event and active_event.effective_status in (Event.Status.FINISHED, Event.Status.CANCELLED):
        return teams.none()
    if active_event:
        teams = teams.filter(Q(event=active_event) | Q(event__isnull=True))
    teams = teams.exclude(event__status__in=(Event.Status.FINISHED, Event.Status.CANCELLED))
    teams = teams.exclude(event__end_date__lte=timezone.now())
    locked = TournamentRegistration.objects.filter(team_id=OuterRef('pk')).filter(
        Q(tournament__is_generated=True) | Q(tournament__status=Tournament.Status.IN_PROGRESS)
    ).exclude(tournament__status__in=(Tournament.Status.FINISHED, Tournament.Status.CANCELLED))
    return teams.alias(roster_locked=Exists(locked)).filter(roster_locked=False)


def pending_invitations(active_event):
    return TeamInvitation.objects.filter(status=TeamInvitation.Status.PENDING,
        event=active_event, team__in=current_recruitment_teams(active_event),
        user__is_active=True, user__deleted_at__isnull=True)


def received_invitations(user, active_event):
    if not user.is_authenticated:
        return TeamInvitation.objects.none()
    return pending_invitations(active_event).filter(user=user).select_related(
        'team', 'team__game', 'invited_by')


@contextmanager
def locked_recruitment(team_id, actor, target_ids=()):
    """Lock recipients even when they have no membership yet; re-read after waits."""
    team_id = identifier(team_id)
    target_ids = {identifier(pk) for pk in target_ids}
    with transaction.atomic():
        snapshot = Team.objects.get(pk=team_id)
        user_ids = target_ids | {actor.pk, snapshot.captain_id}
        user_ids.update(snapshot.memberships.values_list('user_id', flat=True))
        users = {user.pk: user for user in get_user_model().objects.select_for_update(no_key=True)
            .filter(pk__in=user_ids).order_by('pk')}
        current_actor = users.get(actor.pk)
        if not current_actor or not current_actor.is_active or current_actor.deleted_at:
            raise PermissionDenied(get_translation('team_recruit_player_unavailable'))
        active = Event.objects.get_active()
        event_ids = {active.pk} if active else set()
        if snapshot.event_id:
            event_ids.add(snapshot.event_id)
        event_ids.update(snapshot.tournament_registrations.exclude(
            tournament__status__in=(Tournament.Status.FINISHED, Tournament.Status.CANCELLED)
        ).values_list('tournament__event_id', flat=True))
        events = {event.pk: event for event in Event.objects.select_for_update()
            .filter(pk__in=event_ids).order_by('pk')}
        if active:
            active = events[active.pk]
            if not active.is_active:
                raise TournamentError(get_translation('audit_team_event_changed'))
        team = Team.objects.select_for_update().get(pk=team_id)
        if team.event_id not in events and team.event_id is not None:
            raise TournamentError(get_translation('audit_team_event_changed'))
        if team.event_id:
            team.event = events[team.event_id]
        yield team, current_actor, users, active


def require_captain(team, actor):
    if team.captain_id != actor.pk:
        raise PermissionDenied(get_translation('team_recruit_forbidden'))


def validate_recruitment(team, active):
    if not team.captain.is_active or team.captain.deleted_at:
        raise TournamentError(get_translation('team_recruit_unavailable'))
    if team.is_solo:
        raise TournamentError(get_translation('team_recruit_solo'))
    closed = (Event.Status.FINISHED, Event.Status.CANCELLED)
    if (team.is_archived or active and team.event_id not in (None, active.pk)
        or active and active.effective_status in closed
        or team.event_id and team.event.effective_status in closed):
        raise TournamentError(get_translation('team_recruit_unavailable'))
    if team.is_in_active_tournament():
        raise TournamentError(get_translation('team_recruit_locked'))


def validate_players(team, users, target_ids):
    for pk in target_ids:
        user = users.get(pk)
        if not user or not user.is_active or user.deleted_at:
            raise TournamentError(get_translation('team_recruit_player_unavailable'))
        if team.is_member(user):
            raise TournamentError(get_translation('team_recruit_already_member', username=user.display_name))
        if team.game_id and TeamMember.objects.filter(user=user, status=TeamMember.Status.ACCEPTED,
            team__game_id=team.game_id, team__is_archived=False).exclude(team=team).exists():
            raise TournamentError(get_translation('team_recruit_other_team', username=user.display_name))


def validate_capacity(team, count):
    if team.game_id and team.get_accepted_members().count() + count > team.game.team_size:
        raise TournamentError(get_translation('team_recruit_full'))


def locked_clans(user_ids):
    return {membership.user_id: membership.clan_id for membership in
        ClanMembership.objects.select_for_update().filter(user_id__in=user_ids,
            status=ClanMembership.Status.ACCEPTED).order_by('user_id')}


def add_members(team, actor, target_ids):
    for pk in sorted(target_ids):
        membership, _ = TeamMember.objects.get_or_create(team=team, user_id=pk)
        membership.status = TeamMember.Status.ACCEPTED
        membership.role = TeamMember.Role.MEMBER
        membership.added_by = actor
        membership.save(update_fields=['status', 'role', 'added_by'])


def add_clan_members(team_id, actor, target_ids):
    target_ids = {identifier(pk) for pk in target_ids}
    if not target_ids:
        raise TournamentError(get_translation('team_recruit_select'))
    with locked_recruitment(team_id, actor, target_ids) as (team, actor, users, active):
        require_captain(team, actor)
        validate_recruitment(team, active)
        validate_players(team, users, target_ids)
        validate_capacity(team, len(target_ids))
        clans = locked_clans(target_ids | {actor.pk})
        if not clans.get(actor.pk) or any(clans.get(pk) != clans[actor.pk] for pk in target_ids):
            raise TournamentError(get_translation('team_recruit_clan_changed'))
        add_members(team, actor, target_ids)
    return len(target_ids)


def recruit_player(team_id, actor, user_id):
    user_id = identifier(user_id)
    with locked_recruitment(team_id, actor, [user_id]) as (team, actor, users, active):
        require_captain(team, actor)
        validate_recruitment(team, active)
        validate_players(team, users, [user_id])
        validate_capacity(team, 1)
        clans = locked_clans({actor.pk, user_id})
        if clans.get(actor.pk) and clans.get(actor.pk) == clans.get(user_id):
            add_members(team, actor, {user_id})
            return 'added', users[user_id]
        if team.memberships.filter(user_id=user_id, status=TeamMember.Status.PENDING).exists():
            raise TournamentError(get_translation('team_recruit_pending_application', username=users[user_id].display_name))
        from tournaments.recruitment_signals import expire_invitations
        expire_invitations(team.invitations.filter(user_id=user_id).exclude(event=active))
        if team.invitations.filter(user_id=user_id, status=TeamInvitation.Status.PENDING).exists():
            raise TournamentError(get_translation('team_recruit_pending_invitation', username=users[user_id].display_name))
        TeamInvitation.objects.create(team=team, user_id=user_id, invited_by=actor, event=active)
        return 'invited', users[user_id]


def respond_to_invitation(team_id, actor, invitation_id, action):
    with locked_recruitment(team_id, actor) as (team, actor, users, active):
        invitation = TeamInvitation.objects.select_for_update().get(pk=identifier(invitation_id), team=team)
        if action == 'withdraw':
            require_captain(team, actor)
        elif invitation.user_id != actor.pk:
            raise PermissionDenied(get_translation('team_invitation_recipient_only'))
        if invitation.status != TeamInvitation.Status.PENDING:
            raise TournamentError(get_translation('team_invitation_not_open'))
        if action == 'accept':
            validate_recruitment(team, active)
            if invitation.event_id != (active.pk if active else None):
                raise TournamentError(get_translation('team_invitation_not_open'))
            validate_players(team, users, [actor.pk])
            validate_capacity(team, 1)
            member, _ = TeamMember.objects.get_or_create(team=team, user=actor,
                defaults={'status': TeamMember.Status.ACCEPTED})
            member.status = TeamMember.Status.ACCEPTED
            member.save(update_fields=['status'])
            invitation.status = TeamInvitation.Status.ACCEPTED
        elif action == 'decline':
            invitation.status = TeamInvitation.Status.DECLINED
        elif action == 'withdraw':
            invitation.status = TeamInvitation.Status.WITHDRAWN
        else:
            raise ValueError('Unknown invitation response')
        invitation.resolved_at = timezone.now()
        invitation.save(update_fields=['status', 'resolved_at'])
        return team


def reject_application(team_id, actor, membership_id):
    with locked_recruitment(team_id, actor) as (team, actor, users, active):
        require_captain(team, actor)
        member = TeamMember.objects.get(pk=identifier(membership_id), team=team)
        if member.status != TeamMember.Status.PENDING:
            raise TournamentError(get_translation('team_application_not_pending'))
        member.delete()


def eligible_players(team):
    """Only public nicknames are exposed; never email or personal profile data."""
    users = get_user_model().objects.filter(is_active=True, deleted_at__isnull=True)
    users = users.exclude(pk__in=team.memberships.filter(status=TeamMember.Status.ACCEPTED).values('user_id'))
    if team.game_id:
        users = users.exclude(pk__in=TeamMember.objects.filter(status=TeamMember.Status.ACCEPTED,
            team__game_id=team.game_id, team__is_archived=False).values('user_id'))
    return users.order_by('username', 'pk')
