"""
Tournament Services Package.

Modularisiert nach Verantwortlichkeiten:
- registration: Anmeldung, Abmeldung, Solo-Teams, Event-Checkin
- brackets: Generierung von Turnierbäumen (Single, Double, League, Group, FFA)
- matches: Match-Ergebnisverarbeitung, Weiterschaltung, FFA
- standings: Tabellen- und Ranglistenberechnung (Liga, Gruppe)
- podium: Sieger-Podium abgeschlossener Turniere
- forfeits: Walkover & Disqualifikationen
"""

from tournaments.services.registration import (
    TournamentRegistrationService,
    check_user_event_checkin,
    archive_teams_for_event,
    get_or_create_solo_team,
)
from tournaments.services.brackets import (
    TournamentBracketService,
    generate_bracket,
    next_power_of_two,
    generate_standard_seed_order,
    _generate_single_elimination,
    _generate_double_elimination,
    _generate_league,
    _generate_group_stage,
    _generate_ffa,
)
from tournaments.services.matches import (
    TournamentMatchService,
    FFAMatchService,
    advance_match_winner,
    check_and_advance_match,
    check_and_advance_bye_in_loser_bracket,
    check_and_advance_bye_or_walkover,
)
from tournaments.services.standings import (
    LeagueStandingService,
    GroupStageStandingService,
    check_and_advance_group_stage,
)
from tournaments.services.forfeits import (
    forfeit_team_in_active_tournaments,
)
from tournaments.services.podium import TournamentPodiumService

__all__ = [
    # Registration
    'TournamentRegistrationService',
    'check_user_event_checkin',
    'archive_teams_for_event',
    'get_or_create_solo_team',
    # Brackets
    'TournamentBracketService',
    'generate_bracket',
    'next_power_of_two',
    'generate_standard_seed_order',
    '_generate_single_elimination',
    '_generate_double_elimination',
    '_generate_league',
    '_generate_group_stage',
    '_generate_ffa',
    # Matches
    'TournamentMatchService',
    'FFAMatchService',
    'advance_match_winner',
    'check_and_advance_match',
    'check_and_advance_bye_in_loser_bracket',
    'check_and_advance_bye_or_walkover',
    # Standings
    'LeagueStandingService',
    'GroupStageStandingService',
    'check_and_advance_group_stage',
    # Forfeits
    'forfeit_team_in_active_tournaments',
    'TournamentPodiumService',
]
