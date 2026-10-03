"""Resolve personal invitations when existing membership/lifecycle actions run."""
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from events.models import Event
from .models import Team, TeamInvitation, TeamMember, Tournament


def expire_invitations(queryset):
    queryset.filter(status=TeamInvitation.Status.PENDING).update(
        status=TeamInvitation.Status.EXPIRED, resolved_at=timezone.now())


@receiver(post_save, sender=TeamMember)
def resolve_membership_invitations(sender, instance, raw=False, **kwargs):
    if raw or instance.status != TeamMember.Status.ACCEPTED or instance.team.is_archived:
        return
    TeamInvitation.objects.filter(team_id=instance.team_id, user_id=instance.user_id,
        status=TeamInvitation.Status.PENDING).update(
        status=TeamInvitation.Status.ACCEPTED, resolved_at=timezone.now())
    if instance.team.game_id:
        expire_invitations(TeamInvitation.objects.filter(user_id=instance.user_id,
            team__game_id=instance.team.game_id).exclude(team_id=instance.team_id))


@receiver(post_save, sender=Team)
def expire_archived_team_invitations(sender, instance, raw=False, **kwargs):
    if raw:
        return
    invitations = TeamInvitation.objects.filter(team_id=instance.pk)
    if instance.is_archived:
        expire_invitations(invitations)
    elif instance.event_id:
        expire_invitations(invitations.exclude(event_id=instance.event_id))


@receiver(post_save, sender=Event)
def expire_closed_event_invitations(sender, instance, raw=False, **kwargs):
    if not raw and instance.effective_status in (Event.Status.FINISHED, Event.Status.CANCELLED):
        expire_invitations(TeamInvitation.objects.filter(Q(event=instance) | Q(team__event=instance)))


@receiver(post_save, sender=Tournament)
def expire_started_tournament_invitations(sender, instance, raw=False, **kwargs):
    if not raw and (instance.is_generated or instance.status == Tournament.Status.IN_PROGRESS):
        if instance.status not in (Tournament.Status.FINISHED, Tournament.Status.CANCELLED):
            expire_invitations(TeamInvitation.objects.filter(
                team_id__in=instance.registrations.values('team_id')))


@receiver(post_save, sender=get_user_model())
def expire_unavailable_player_invitations(sender, instance, raw=False, **kwargs):
    if not raw and (instance.deleted_at or not instance.is_active):
        expire_invitations(TeamInvitation.objects.filter(Q(user=instance) | Q(team__captain=instance)))
