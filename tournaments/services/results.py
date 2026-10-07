"""Shared result permissions, dependency repair and review lifecycle.

Writers hold Event -> Tournament before inspecting or changing these records.
"""
import hashlib
import json

from configuration.translations import get_translation as tr
from tournaments.exceptions import TournamentMatchError, MatchAlreadyCompletedError, MatchNotReadyError
from tournaments.models import Tournament, TournamentMatch, TournamentResultLog
from .locking import event_is_closed


def snapshot(match):
    result = {name: getattr(match, name) for name in (
        'team1_id', 'team2_id', 'score_team1', 'score_team2', 'winner_id', 'loser_id',
        'status', 'is_bye', 'result_type', 'decision_reason')}
    result.update(team1=match.team1.name if match.team1 else '', team2=match.team2.name if match.team2 else '',
                  winner=match.winner.name if match.winner else '')
    if match.bracket_type == TournamentMatch.BracketType.FFA:
        result['participants'] = list(match.participants.order_by('pk').values(
            'id', 'team_id', 'team__name', 'rank', 'score', 'is_disqualified', 'notes'))
    return result


def version(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def match_version(match):
    return version(snapshot(match))


def tournament_version(tournament, matches=None):
    matches = matches if matches is not None else tournament.matches.select_related('team1', 'team2', 'winner').order_by('pk')
    return version([snapshot(m) for m in sorted(matches, key=lambda m: m.pk)])


def check_version(expected, actual):
    if expected is not None and expected != actual:
        raise TournamentMatchError(tr('results_stale'))


def log_result(match, before, actor, reason, *, action='RESULT'):
    after = snapshot(match)
    if before != after:
        TournamentResultLog.objects.create(tournament=match.tournament, match=match,
            match_label=str(match), actor=actor, action=action, reason=reason or '',
            before=before, after=after)


def result_lock_reason(match, tournament, *, latest_swiss_round=None):
    if event_is_closed(tournament):
        return tr('results_event_locked')
    if tournament.status in (Tournament.Status.FINISHED, Tournament.Status.CANCELLED):
        return tr('results_final_locked')
    if tournament.status not in (Tournament.Status.IN_PROGRESS, Tournament.Status.RESULTS_REVIEW):
        return tr('results_not_running')
    if match.is_bye or match.result_type != TournamentMatch.ResultType.PLAYED:
        return tr('results_automatic_locked')
    if tournament.mode == Tournament.Mode.SWISS:
        later = latest_swiss_round > match.round_number if latest_swiss_round is not None else tournament.swiss_round_records.filter(number__gt=match.round_number).exists()
        if later:
            return tr('results_swiss_locked')
    if match.bracket_type != TournamentMatch.BracketType.FFA and (not match.team1_id or not match.team2_id):
        return tr('results_not_ready')
    if tournament.mode == Tournament.Mode.GROUP_STAGE and match.bracket_type != TournamentMatch.BracketType.GROUP and not tournament.playoffs_released_at:
        return tr('results_playoffs_unreleased')
    return ''


def require_editable(match, tournament):
    if match.bracket_type != TournamentMatch.BracketType.FFA and not match.is_bye and (not match.team1_id or not match.team2_id):
        raise MatchNotReadyError(tr('results_not_ready'))
    reason = result_lock_reason(match, tournament)
    if reason:
        raise MatchAlreadyCompletedError(reason)


def require_correction_reason(match, actor, reason):
    if actor is not None and match.status == TournamentMatch.Status.COMPLETED and not reason:
        raise TournamentMatchError(tr('results_reason_required'))


def descendants(match):
    """Includes automatic bye chains, bronze matches and the dynamic GF reset."""
    rows = {m.pk: m for m in match.tournament.matches.all()}
    found, todo = {}, [match]
    while todo:
        current = todo.pop()
        ids = [current.next_match_winner_id, current.next_match_loser_id]
        if current.bracket_type == TournamentMatch.BracketType.GRAND_FINAL:
            ids += [m.pk for m in rows.values() if m.bracket_type == TournamentMatch.BracketType.GRAND_FINAL_RESET]
        for pk in ids:
            if pk and pk not in found and pk != match.pk:
                found[pk] = rows[pk]
                todo.append(rows[pk])
    return list(found.values())


def repair_descendants(match, actor, reason):
    """Reset only dependent, unplayed matches; rebuild them from all feeders."""
    from .matches import check_and_advance_match
    affected = descendants(match)
    if any(m.status == TournamentMatch.Status.IN_PROGRESS or
           (m.status == TournamentMatch.Status.COMPLETED and not m.is_bye) for m in affected):
        raise MatchAlreadyCompletedError(tr('results_followup_locked'))
    before = {m.pk: snapshot(m) for m in affected}
    for m in affected:
        # Reset matches are dynamically created below from the corrected GF.
        if m.bracket_type == TournamentMatch.BracketType.GRAND_FINAL_RESET:
            TournamentResultLog.objects.create(tournament=match.tournament, match=m,
                match_label=str(m), actor=actor, action='DEPENDENCY', reason=reason,
                before=before[m.pk], after={'removed': True})
            m.delete()
            continue
        m.team1 = m.team2 = m.winner = m.loser = None
        m.score_team1 = m.score_team2 = None
        m.is_bye = False
        m.status = TournamentMatch.Status.PENDING
        m.decision_reason = ''
        m.save()
    # Topological order is determined by edges, not by round numbers (DE).
    pending = {m.pk: m for m in affected if m.pk and m.bracket_type != TournamentMatch.BracketType.GRAND_FINAL_RESET}
    while pending:
        ready = [m for m in pending.values() if not any(
            f.pk in pending for f in list(m.prev_matches_winner.all()) + list(m.prev_matches_loser.all()))]
        if not ready:
            raise TournamentMatchError(tr('results_dependency_invalid'))
        for m in ready:
            m.refresh_from_db()
            check_and_advance_match(m)
            pending.pop(m.pk)
    for m in affected:
        if m.pk:
            m.refresh_from_db()
            log_result(m, before[m.pk], actor, reason, action='DEPENDENCY')


def sync_review(tournament):
    """Scoring never confirms final standings or certificates."""
    if tournament.status in (Tournament.Status.FINISHED, Tournament.Status.CANCELLED):
        return
    complete = tournament.matches.exists() and not tournament.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists()
    if tournament.mode == Tournament.Mode.SWISS:
        complete = complete and tournament.swiss_round_records.filter(number=tournament.swiss_rounds).exists()
    status = Tournament.Status.RESULTS_REVIEW if complete else Tournament.Status.IN_PROGRESS
    if tournament.status != status:
        tournament.status = status
        tournament.save(update_fields=['status', 'updated_at'])


def qualification(tournament):
    from .standings import GroupStageStandingService
    count = 2 if tournament.matches.filter(bracket_type=TournamentMatch.BracketType.FINAL, round_number=2).count() == 2 else 1
    withdrawn = set(tournament.registrations.filter(is_forfeited=True).values_list('team_id', flat=True))
    return tuple(tuple(row['team'].pk for row in GroupStageStandingService.calculate_group_standings(tournament, group)
                       if row['team'].pk not in withdrawn)[:count] for group in ('Gruppe A', 'Gruppe B'))


def playoffs_locked(tournament):
    return bool(tournament.playoffs_released_at or tournament.matches.exclude(
        bracket_type=TournamentMatch.BracketType.GROUP).filter(
            status__in=(TournamentMatch.Status.IN_PROGRESS, TournamentMatch.Status.COMPLETED), is_bye=False).exists())


def reset_unreleased_playoffs(tournament, actor, reason):
    """Requalification may replace teams propagated through automatic byes."""
    rows = list(tournament.matches.exclude(bracket_type=TournamentMatch.BracketType.GROUP))
    before = {m.pk: snapshot(m) for m in rows}
    for m in rows:
        if m.status == TournamentMatch.Status.IN_PROGRESS or (m.status == TournamentMatch.Status.COMPLETED and not m.is_bye):
            raise MatchAlreadyCompletedError(tr('results_qualification_locked'))
        m.team1 = m.team2 = m.winner = m.loser = None
        m.score_team1 = m.score_team2 = None
        m.is_bye = False
        m.status = TournamentMatch.Status.PENDING
        m.decision_reason = ''
        m.save()
    from .standings import GroupStageStandingService
    GroupStageStandingService.check_and_advance_group_stage(tournament)
    for m in rows:
        m.refresh_from_db()
        log_result(m, before[m.pk], actor, reason, action='DEPENDENCY')
