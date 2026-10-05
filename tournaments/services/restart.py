"""Prepare independent tournament editions while preserving the original history."""
import hashlib
import json
import uuid

from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.text import slugify

from configuration.translations import get_translation
from tournaments.exceptions import TournamentError
from tournaments.models import Team, Tournament, TournamentRegistration
from .locking import lock_tournament, event_is_closed
from .validation import identifier

TOKEN_SALT = 'tournaments.restart.v1'
COPY_FIELDS = ('event_id', 'game_id', 'description', 'mode', 'max_teams', 'swiss_rounds',
    'swiss_allow_draws', 'play_third_place', 'group_qualifiers_per_group', 'standings_tiebreak',
    'tournament_admin_id', 'tournament_support_id', 'roster_rule')
CANCELLABLE = (Tournament.Status.DRAFT, Tournament.Status.REGISTRATION_OPEN,
               Tournament.Status.REGISTRATION_CLOSED, Tournament.Status.IN_PROGRESS)


def _authorize(actor):
    if not Tournament.can_view_drafts(actor) or not actor.has_perms((
        'tournaments.add_tournament', 'tournaments.change_tournament', 'tournaments.add_tournamentregistration',
    )):
        raise PermissionDenied(get_translation('restart_permission'))


def _snapshot(source):
    # No nullable joins in SELECT FOR UPDATE: PostgreSQL must lock base rows.
    registrations = list(source.registrations.select_for_update().order_by('registered_at', 'pk'))
    teams = {team.pk: team for team in Team.objects.select_for_update().filter(
        pk__in=[r.team_id for r in registrations]).order_by('pk')}
    rows = [{'id': r.pk, 'team_id': r.team_id, 'name': teams[r.team_id].name, 'seed': r.seed,
             'withdrawn': r.is_forfeited, 'archived': teams[r.team_id].is_archived,
             'group': r.group_name, 'score': r.score,
             'team_event': teams[r.team_id].event_id, 'team_game': teams[r.team_id].game_id}
            for r in registrations]
    data = {field: getattr(source, field) for field in COPY_FIELDS}
    data.update(title=source.title, status=source.status, is_generated=source.is_generated,
        updated_at=source.updated_at.isoformat(), event_closed=event_is_closed(source),
        dates=[source.registration_start.isoformat(), source.registration_end.isoformat(),
               source.tournament_start.isoformat() if source.tournament_start else None], registrations=rows)
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return rows, digest


class TournamentRestartService:
    @staticmethod
    @transaction.atomic
    def preview(tournament_id, *, actor):
        _authorize(actor)
        source = lock_tournament(tournament_id)
        rows, digest = _snapshot(source)
        token = signing.dumps({'source': source.pk, 'actor': actor.pk, 'digest': digest,
                               'request': str(uuid.uuid4())}, salt=TOKEN_SALT)
        return {'source': source, 'registrations': rows, 'token': token,
                'event_closed': event_is_closed(source), 'can_cancel': source.status in CANCELLABLE}

    @staticmethod
    @transaction.atomic
    def create(tournament_id, *, actor, preview_token, title, registration_start,
               registration_end, tournament_start=None, registration_ids=(),
               copy_seeds=True, cancel_source=False, reason):
        _authorize(actor)
        source = lock_tournament(tournament_id)
        try:
            claim = signing.loads(preview_token, salt=TOKEN_SALT, max_age=1800)
            request_id = uuid.UUID(claim['request'])
            if claim['source'] != source.pk or claim['actor'] != actor.pk:
                raise ValueError()
        except (signing.BadSignature, KeyError, TypeError, ValueError, AttributeError):
            raise TournamentError(get_translation('restart_invalid_preview'))
        # Source lock serializes two publications of the same preview. Retrying
        # a successful POST returns its edition even if the source was cancelled.
        existing = Tournament.objects.filter(restart_request_id=request_id).first()
        if existing:
            return existing, False
        rows, digest = _snapshot(source)
        if digest != claim.get('digest'):
            raise TournamentError(get_translation('restart_stale_preview'))
        ids = [identifier(value) for value in registration_ids]
        selected_ids = set(ids)
        if len(selected_ids) != len(ids) or not selected_ids.issubset({r['id'] for r in rows}):
            raise TournamentError(get_translation('restart_invalid_teams'))
        selected = [r for r in rows if r['id'] in selected_ids]
        if source.max_teams and len(selected) > source.max_teams:
            raise TournamentError(get_translation('restart_capacity'))
        if not isinstance(copy_seeds, bool) or not isinstance(cancel_source, bool):
            raise TournamentError(get_translation('restart_invalid_options'))
        if cancel_source and source.status not in CANCELLABLE:
            raise TournamentError(get_translation('restart_terminal_source'))
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 1000:
            raise TournamentError(get_translation('restart_reason_required'))
        if not isinstance(title, str) or not title.strip():
            raise TournamentError(get_translation('restart_title_required'))
        new = Tournament(**{field: getattr(source, field) for field in COPY_FIELDS},
            title=title.strip(), slug=f"{(slugify(title) or 'turnier')[:117]}-{request_id.hex}",
            status=Tournament.Status.DRAFT, registration_start=registration_start,
            registration_end=registration_end, tournament_start=tournament_start,
            restarted_from=source, restart_source_title=source.title, restarted_by=actor,
            restart_reason=reason.strip(), restart_request_id=request_id,
            restart_cancelled_source=cancel_source,
            restart_team_snapshot=[{'team_id': r['team_id'], 'name': r['name'],
                'seed': r['seed'] if copy_seeds else None, 'previously_withdrawn': r['withdrawn']}
                for r in selected])
        new.full_clean()
        if new.registration_end < new.registration_start:
            raise TournamentError(get_translation('restart_dates_invalid'))
        new.save()
        for row in selected:
            TournamentRegistration.objects.create(tournament=new, team_id=row['team_id'],
                seed=row['seed'] if copy_seeds else None)
        if cancel_source:
            source.status = Tournament.Status.CANCELLED
            source.save(update_fields=['status', 'updated_at'])
        return new, True
