"""Publication and registration lifecycle actions with shared tournament locks."""
from django.core.exceptions import PermissionDenied
from django.db import transaction

from configuration.translations import get_translation
from tournaments.exceptions import TournamentError
from tournaments.models import Tournament
from tournaments.services.locking import lock_tournament, event_is_closed


class TournamentLifecycleService:
    @staticmethod
    @transaction.atomic
    def close_registration(tournament_id, *, actor):
        tournament = lock_tournament(tournament_id)
        if not tournament.is_managed_by(actor):
            raise PermissionDenied(get_translation('msg_tournament_close_permission'))
        if tournament.status != Tournament.Status.REGISTRATION_OPEN or tournament.is_generated:
            raise TournamentError(get_translation('msg_tournament_close_requires_open'))
        if event_is_closed(tournament):
            raise TournamentError(get_translation('msg_tournament_close_event_closed'))
        tournament.status = Tournament.Status.REGISTRATION_CLOSED
        tournament.save(update_fields=['status', 'updated_at'])
        return tournament

    @staticmethod
    @transaction.atomic
    def open_registration(tournament_id, *, actor):
        if not Tournament.can_view_drafts(actor):
            raise PermissionDenied(get_translation('msg_tournament_open_permission'))
        tournament = lock_tournament(tournament_id)
        if tournament.status != Tournament.Status.DRAFT or tournament.is_generated:
            raise TournamentError(get_translation('msg_tournament_open_requires_draft'))
        if event_is_closed(tournament):
            raise TournamentError(get_translation('msg_tournament_open_event_closed'))
        tournament.status = Tournament.Status.REGISTRATION_OPEN
        tournament.save(update_fields=['status', 'updated_at'])
        return tournament
