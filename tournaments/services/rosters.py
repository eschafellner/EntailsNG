from configuration.translations import get_translation
"""Serialize frontend roster changes with registration, starts and account deletion."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect

from events.models import Event
from configuration.cache import get_request_cache
from tournaments.models import Team, TeamMember


def roster_action(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method != 'POST':
            return view(request, *args, **kwargs)
        with transaction.atomic():
            team = None
            if 'slug' in kwargs:
                team = Team.objects.filter(slug=kwargs['slug']).first()
            elif view.__name__ == 'team_join_by_code':
                team = Team.objects.filter(invite_code=request.POST.get('invite_code', '').strip().upper()).first()
            user_ids = {request.user.pk}
            if team:
                user_ids.update(team.memberships.values_list('user_id', flat=True))
                user_ids.add(team.captain_id)
            users = {u.pk: u for u in get_user_model().objects.select_for_update(no_key=True).filter(pk__in=user_ids).order_by('pk')}
            actor = users[request.user.pk]
            if actor.deleted_at or not actor.is_active:
                return redirect('team_list')
            request.user = actor
            active = Event.objects.get_active()
            event_ids = {active.pk} if active else set()
            if team and team.event_id:
                event_ids.add(team.event_id)
            events = {e.pk: e for e in Event.objects.select_for_update().filter(pk__in=event_ids).order_by('pk')}
            if active:
                active = events[active.pk]
                if not active.is_active:
                    messages.error(request, get_translation('audit_team_event_changed', 'Die aktive Veranstaltung hat sich geändert. Bitte lade die Seite neu.'))
                    return redirect('team_list')
                request_cache = get_request_cache()
                if request_cache is not None:
                    request_cache['active_event'] = active
            if team:
                team = Team.objects.select_for_update().get(pk=team.pk)
            new_members = view.__name__ in ('team_join_by_code', 'team_apply', 'team_accept_membership')
            error = None
            if new_members and team and (team.is_archived or active and team.event_id not in (None, active.pk)):
                error = get_translation('audit_team_requires_reactivation', 'Dieses Team ist archiviert oder gehört zu einer anderen Veranstaltung. Bitte zuerst reaktivieren.')
            elif view.__name__ not in ('team_leave', 'team_kick_member') and active and active.effective_status in (Event.Status.FINISHED, Event.Status.CANCELLED):
                error = get_translation('audit_team_event_closed', 'Die Veranstaltung ist beendet oder abgesagt. Das Team kann nicht verändert werden.')
            elif new_members and team and team.event_id and events[team.event_id].effective_status in (Event.Status.FINISHED, Event.Status.CANCELLED):
                error = get_translation('audit_team_previous_event_closed', 'Die Veranstaltung dieses Teams ist beendet oder abgesagt.')
            elif view.__name__ == 'team_accept_membership' and team:
                applicant = TeamMember.objects.filter(team=team, pk=kwargs['membership_id']).values_list('user_id', flat=True).first()
                if applicant and (applicant not in users or users[applicant].deleted_at or not users[applicant].is_active):
                    error = get_translation('audit_team_applicant_unavailable', 'Dieser Gast kann nicht in das Team aufgenommen werden.')
            if error:
                messages.error(request, error)
                return redirect('team_detail', slug=team.slug) if team else redirect('team_list')
            return view(request, *args, **kwargs)
    return wrapped
