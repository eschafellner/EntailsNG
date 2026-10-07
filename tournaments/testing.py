"""Fixture helpers for tests that need confirmed final standings."""
from django.contrib.auth import get_user_model
from .models import Tournament, TournamentMatch
from .services import TournamentLifecycleService


def confirm_results(tournament, actor=None):
    tournament.refresh_from_db()
    if tournament.status == Tournament.Status.RESULTS_REVIEW:
        actor = actor or get_user_model().objects.filter(is_staff=True).first()
        if actor is None:
            actor = get_user_model().objects.create_user('result-fixture-orga', is_staff=True)
        TournamentLifecycleService.confirm_results(tournament.pk, actor=actor)
        tournament.refresh_from_db()


def release_for_match(match, actor=None):
    tournament = match.tournament
    tournament.refresh_from_db()
    if tournament.mode == Tournament.Mode.GROUP_STAGE and match.bracket_type != TournamentMatch.BracketType.GROUP and not tournament.playoffs_released_at:
        actor = actor or get_user_model().objects.filter(is_staff=True).first()
        if actor is None:
            actor = get_user_model().objects.create_user('result-fixture-orga', is_staff=True)
        TournamentLifecycleService.release_playoffs(tournament.pk, actor=actor)
