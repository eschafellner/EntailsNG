"""Publication and registration lifecycle actions with shared tournament locks."""
from django.core.exceptions import PermissionDenied
from django.db import transaction

from configuration.translations import get_translation
from tournaments.exceptions import TournamentError
from tournaments.models import Tournament, TournamentMatch, TournamentResultLog
from tournaments.services.locking import lock_tournament, event_is_closed


class TournamentLifecycleService:
    @staticmethod
    @transaction.atomic
    def confirm_results(tournament_id, *, actor, expected_state=None):
        from django.utils import timezone
        from .results import sync_review, tournament_version, check_version
        tournament = lock_tournament(tournament_id)
        if not tournament.is_managed_by(actor):
            raise TournamentError(get_translation('results_permission'))
        if event_is_closed(tournament) or tournament.status in (Tournament.Status.FINISHED, Tournament.Status.CANCELLED):
            raise TournamentError(get_translation('results_final_locked'))
        check_version(expected_state, tournament_version(tournament))
        sync_review(tournament)
        if tournament.status != Tournament.Status.RESULTS_REVIEW:
            raise TournamentError(get_translation('results_incomplete'))
        tournament.status = Tournament.Status.FINISHED
        tournament.results_confirmed_at = timezone.now()
        tournament.results_confirmed_by = actor
        tournament.save(update_fields=['status', 'results_confirmed_at', 'results_confirmed_by', 'updated_at'])
        TournamentResultLog.objects.create(tournament=tournament, actor=actor, action='CONFIRM',
            before={'status': Tournament.Status.RESULTS_REVIEW}, after={'status': Tournament.Status.FINISHED})
        return tournament

    @staticmethod
    @transaction.atomic
    def release_playoffs(tournament_id, *, actor, expected_state=None):
        from django.utils import timezone
        from .standings import GroupStageStandingService
        from .results import check_version, tournament_version
        tournament = lock_tournament(tournament_id)
        if not tournament.is_managed_by(actor):
            raise TournamentError(get_translation('results_permission'))
        if (event_is_closed(tournament) or tournament.status != Tournament.Status.IN_PROGRESS
                or tournament.mode != Tournament.Mode.GROUP_STAGE or tournament.playoffs_released_at):
            raise TournamentError(get_translation('results_release_unavailable'))
        groups = tournament.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP)
        if not groups.exists() or groups.exclude(status=TournamentMatch.Status.COMPLETED).exists():
            raise TournamentError(get_translation('results_groups_incomplete'))
        check_version(expected_state, tournament_version(tournament))
        GroupStageStandingService.check_and_advance_group_stage(tournament)
        tournament.playoffs_released_at = timezone.now()
        tournament.save(update_fields=['playoffs_released_at', 'updated_at'])
        TournamentResultLog.objects.create(tournament=tournament, actor=actor, action='RELEASE',
            after={'playoffs_released_at': tournament.playoffs_released_at.isoformat()})
        return tournament

    @staticmethod
    @transaction.atomic
    def start_match(match_id, *, actor, expected_state=None):
        from .results import require_editable, snapshot, log_result, check_version, match_version
        tournament_id = TournamentMatch.objects.values_list('tournament_id', flat=True).get(pk=match_id)
        tournament = lock_tournament(tournament_id)
        match = TournamentMatch.objects.select_for_update().get(pk=match_id)
        match.tournament = tournament
        if not tournament.is_managed_by(actor):
            raise TournamentError(get_translation('results_permission'))
        check_version(expected_state, match_version(match))
        require_editable(match, tournament)
        if match.status != TournamentMatch.Status.READY:
            raise TournamentError(get_translation('results_start_unavailable'))
        before = snapshot(match)
        match.status = TournamentMatch.Status.IN_PROGRESS
        match.save(update_fields=['status'])
        log_result(match, before, actor, '', action='START')
        return match

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
