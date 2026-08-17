import logging
import math
from django.db import transaction
from django.utils import timezone
from events.models import EventRegistration
from tournaments.exceptions import (
    BracketAlreadyGeneratedError,
    InsufficientTeamsError,
    InvalidScoreError,
    InvalidWinnerError,
    MatchAlreadyCompletedError,
    TournamentAlreadyRegisteredError,
    TournamentBracketError,
    TournamentError,
    TournamentFullError,
    TournamentMatchError,
    TournamentNotCheckedInError,
    TournamentNotOpenError,
    TournamentRegistrationError,
)
from tournaments.models import (
    Game, Team, TeamMember, Tournament, TournamentMatch, TournamentMatchParticipant, TournamentRegistration
)

logger = logging.getLogger(__name__)


def check_user_event_checkin(user, event):
    """
    Prüft, ob der angegebene Benutzer für das aktive Event eingecheckt ist.
    """
    if not user or not user.is_authenticated or not event:
        return False
    return EventRegistration.objects.filter(
        user=user,
        event=event,
        is_checked_in=True
    ).exists()


def archive_teams_for_event(event):
    """
    Archiviert alle Teams, die der angegebenen Veranstaltung zugeordnet sind
    oder an Turnieren dieser Veranstaltung teilgenommen haben.
    """
    if not event:
        return 0
    direct_teams = Team.objects.filter(event=event, is_archived=False)
    tournament_teams = Team.objects.filter(
        tournament_registrations__tournament__event=event,
        is_archived=False
    )
    combined_ids = set(direct_teams.values_list('id', flat=True)) | set(tournament_teams.values_list('id', flat=True))
    count = Team.objects.filter(id__in=combined_ids).update(is_archived=True, event=event)
    return count


def get_or_create_solo_team(user, game):
    """
    Erstellt oder holt ein 1v1 Solo-Team für den angegebenen Benutzer und das angegebene Spiel.
    """
    team_name = f"{user.username} (Solo)"
    team = Team.objects.filter(captain=user, game=game, is_solo=True).first()
    if not team:
        team = Team.objects.create(
            name=team_name,
            game=game,
            captain=user,
            is_solo=True,
        )
        TeamMember.objects.get_or_create(
            team=team,
            user=user,
            defaults={
                'role': TeamMember.Role.CAPTAIN,
                'status': TeamMember.Status.ACCEPTED,
            }
        )
    return team


def next_power_of_two(n):
    if n <= 1:
        return 2
    return 1 << (n - 1).bit_length()


class TournamentRegistrationService:
    @staticmethod
    def register_team(tournament_id, user, team_id=None, actor=None):
        """
        Meldet ein Team oder einen Solo-Spieler transaktionssicher für ein Turnier an.
        Prüft Zeitfenster, Vor-Ort Check-in, Kapazitätslimits und Team-Berechtigungen.
        """
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().select_related('game', 'event').get(pk=tournament_id)

            # 1. Privilegien-Check (Staff / Superuser / Turnier-Admin)
            is_privileged = actor and (
                actor.is_staff or
                actor.is_superuser or
                actor == tournament.tournament_admin or
                actor == tournament.tournament_support
            )

            # 2. Vor-Ort Check-in des anmeldenden Benutzers prüfen
            if not is_privileged and not check_user_event_checkin(user, tournament.event):
                raise TournamentNotCheckedInError(
                    "Nur vor Ort eingecheckte Gäste können sich für Turniere anmelden! Bitte checke zuerst am Einlass ein."
                )

            # 3. Team bestimmen / Solo-Team erzeugen
            if tournament.game.team_size == 1:
                team = get_or_create_solo_team(user, tournament.game)
            else:
                if not team_id:
                    raise TournamentRegistrationError("Bitte wähle ein Team für die Anmeldung aus.")
                team = Team.objects.filter(id=team_id).first()
                if not team:
                    raise TournamentRegistrationError("Das ausgewählte Team wurde nicht gefunden.")

                # 3.1 Archivierungsprüfung
                if team.is_archived:
                    raise TournamentRegistrationError(
                        f"Das Team '{team.name}' ist archiviert und kann nicht angemeldet werden. Bitte reaktiviere das Team zuerst im Teammanager."
                    )

                # 3.2 Event-Zugehörigkeit prüfen
                if team.event and tournament.event and team.event != tournament.event:
                    raise TournamentRegistrationError(
                        f"Das Team '{team.name}' gehört zur Veranstaltung '{team.event.title}' und kann nicht für '{tournament.event.title}' antreten."
                    )
                elif not team.event and tournament.event:
                    team.event = tournament.event
                    team.save(update_fields=['event'])

                # 3.3 Spiel-Passung prüfen
                if team.game and tournament.game and team.game != tournament.game:
                    raise TournamentRegistrationError(
                        f"Das Team '{team.name}' ist für das Spiel '{team.game.name}' registriert, das Turnier ist jedoch für '{tournament.game.name}'."
                    )

                # 3.4 Kapitäns-Berechtigung prüfen
                if not is_privileged and not team.is_captain(user):
                    if team.is_member(user):
                        raise TournamentRegistrationError(
                            f"Nur der Kapitän ({team.captain.username}) kann das Team '{team.name}' für ein Turnier anmelden."
                        )
                    else:
                        raise TournamentRegistrationError("Du bist kein Mitglied dieses Teams.")

                # 3.5 Roster-Vollständigkeit & Check-in aller Mitglieder prüfen
                accepted_members = list(team.get_accepted_members())
                if len(accepted_members) < tournament.game.team_size:
                    raise TournamentRegistrationError(
                        f"Das Team '{team.name}' hat nur {len(accepted_members)} von {tournament.game.team_size} erforderlichen Mitgliedern."
                    )

                if not is_privileged:
                    for m in accepted_members:
                        if not check_user_event_checkin(m.user, tournament.event):
                            raise TournamentNotCheckedInError(
                                f"Das Teammitglied '{m.user.username}' ist noch nicht am Einlass für '{tournament.event.title}' eingecheckt."
                            )

            # 4. Zeitfenster & Status & Duplikat prüfen
            can_reg, reason = tournament.can_register(user=user, team=team)
            if not can_reg:
                if tournament.status != Tournament.Status.REGISTRATION_OPEN:
                    raise TournamentNotOpenError(reason)
                now = timezone.now()
                if (tournament.registration_start and now < tournament.registration_start) or (tournament.registration_end and now > tournament.registration_end):
                    raise TournamentNotOpenError(reason)
                if tournament.registrations.filter(team=team).exists():
                    raise TournamentAlreadyRegisteredError(reason)
                if tournament.max_teams and tournament.registrations.count() >= tournament.max_teams:
                    raise TournamentFullError(reason)
                raise TournamentRegistrationError(reason)

            # 5. Kapazitätslimit unter DB-Row-Lock prüfen
            current_count = tournament.registrations.select_for_update().count()
            if tournament.max_teams and current_count >= tournament.max_teams:
                raise TournamentFullError(
                    f"Die maximale Teilnehmeranzahl ({tournament.max_teams}) für '{tournament.title}' ist bereits erreicht."
                )

            # 6. Registrierung anlegen
            reg, created = TournamentRegistration.objects.get_or_create(
                tournament=tournament,
                team=team,
            )
            return reg, created

    @staticmethod
    def unregister_team(tournament_id, user, team_id=None, actor=None):
        """
        Meldet ein Team transaktionssicher vom Turnier ab, sofern der Turnierbaum noch nicht generiert wurde.
        """
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().get(pk=tournament_id)

            if tournament.is_generated or tournament.status in [Tournament.Status.IN_PROGRESS, Tournament.Status.FINISHED]:
                raise TournamentRegistrationError(
                    "Eine Abmeldung ist nicht mehr möglich, da der Turnierbaum bereits generiert wurde oder das Turnier läuft."
                )

            query = TournamentRegistration.objects.filter(tournament=tournament)
            if team_id:
                query = query.filter(team_id=team_id)

            is_privileged = actor and (actor.is_staff or actor == tournament.tournament_admin or actor == tournament.tournament_support)

            if not is_privileged:
                query = query.filter(team__memberships__user=user, team__memberships__status=TeamMember.Status.ACCEPTED)

            reg = query.first()
            if not reg:
                raise TournamentRegistrationError("Keine aktive Turnieranmeldung gefunden.")

            team_name = reg.team.name
            reg.delete()
            return team_name


class TournamentBracketService:
    @staticmethod
    def generate_bracket(tournament_id, actor=None):
        """
        Atomare Generierung des Turnierbaums.
        Prüft Vorbedingungen, generiert Matches und setzt den Status erst bei absolutem Erfolg auf IN_PROGRESS.
        """
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().get(pk=tournament_id)

            # 1. Prüfe ob bereits generiert
            if tournament.is_generated or tournament.status in [Tournament.Status.IN_PROGRESS, Tournament.Status.FINISHED]:
                raise BracketAlreadyGeneratedError(
                    f"Der Turnierbaum für '{tournament.title}' wurde bereits generiert und kann nicht erneut generiert werden."
                )

            # 2. Mindestanzahl Teams prüfen
            teams = list(tournament.registrations.select_related('team').order_by('registered_at'))
            num_teams = len(teams)
            if num_teams < 2:
                raise InsufficientTeamsError(
                    f"Für die Generierung des Turnierbaums sind mindestens 2 angemeldete Teams erforderlich (aktuell: {num_teams})."
                )

            # 3. Generierung der Matches
            success = generate_bracket(tournament, preview=False)
            if not success:
                raise TournamentBracketError("Die Generierung der Matches ist fehlgeschlagen.")

            # 4. Status auf IN_PROGRESS setzen
            tournament.is_generated = True
            tournament.status = Tournament.Status.IN_PROGRESS
            tournament.save(update_fields=['is_generated', 'status'])
            return True

    @staticmethod
    def reset_bracket(tournament_id, actor=None, force=False):
        """
        Setzt einen generierten Turnierbaum zurück und öffnet die Anmeldung wieder.
        Sicherheit: Nur möglich, wenn noch keine Matches mit Ergebnissen gespielt wurden (außer mit force=True).
        """
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().get(pk=tournament_id)

            if not tournament.is_generated:
                raise TournamentBracketError(f"Für das Turnier '{tournament.title}' existiert noch kein generierter Turnierbaum.")

            completed_matches = TournamentMatch.objects.filter(
                tournament=tournament,
                status=TournamentMatch.Status.COMPLETED
            ).exclude(is_bye=True)

            if completed_matches.exists() and not force:
                raise TournamentBracketError(
                    "Der Turnierbaum kann nicht zurückgesetzt werden, da bereits Matches gespielt und gewertet wurden. "
                    "Ein Reset würde alle Spielergebnisse unwiderruflich löschen."
                )

            # Matches löschen und Status zurücksetzen
            TournamentMatch.objects.filter(tournament=tournament).delete()
            tournament.is_generated = False
            tournament.status = Tournament.Status.REGISTRATION_OPEN
            tournament.save(update_fields=['is_generated', 'status'])
            return True

    @staticmethod
    def get_bracket_preview(tournament_id):
        """
        Liefert eine unverbindliche Vorschau der Turnierbaum-Struktur ohne Datenbankmutation.
        """
        tournament = Tournament.objects.get(pk=tournament_id)
        return generate_bracket(tournament, preview=True)


def generate_standard_seed_order(n):
    """
    Erzeugt die Standard-Seeding-Paarungsreihenfolge für eine Zweierpotenz n.
    Beispiel n=4: [1, 4, 2, 3] -> Paarungen (1, 4) und (2, 3)
    Beispiel n=8: [1, 8, 4, 5, 2, 7, 3, 6]
    """
    if n <= 1:
        return [1]
    rounds = int(math.log2(n))
    seeds = [1, 2]
    for _ in range(1, rounds):
        next_seeds = []
        next_sum = len(seeds) * 2 + 1
        for s in seeds:
            next_seeds.extend([s, next_sum - s])
        seeds = next_seeds
    return seeds


def check_and_advance_bye_in_loser_bracket(lb_match):
    """
    Prüft, ob ein Loser-Bracket-Match ein Freilos ist, weil ein oder beide Zubringer-Matches
    aus dem Winner Bracket Freilose waren und keinen realen Verlierer senden.
    """
    if lb_match.status == TournamentMatch.Status.COMPLETED or lb_match.is_bye:
        return

    # Finde alle direkten Zubringer-Matches, die Verlierer in dieses LB-Match schicken
    prev_wb_loser_matches = list(TournamentMatch.objects.filter(
        tournament=lb_match.tournament,
        next_match_loser=lb_match
    ))

    # Wenn alle Vorgänger-Matches aus dem WB bereits COMPLETED sind:
    if prev_wb_loser_matches and all(m.status == TournamentMatch.Status.COMPLETED for m in prev_wb_loser_matches):
        if (lb_match.team1 and not lb_match.team2) or (lb_match.team2 and not lb_match.team1):
            active_team = lb_match.team1 or lb_match.team2
            lb_match.is_bye = True
            lb_match.winner = active_team
            lb_match.status = TournamentMatch.Status.COMPLETED
            lb_match.save(update_fields=['is_bye', 'winner', 'status'])

            # Weiterreichen in nächste LB-Runde
            if lb_match.next_match_winner:
                next_w = TournamentMatch.objects.select_for_update().get(pk=lb_match.next_match_winner_id)
                if lb_match.next_match_winner_slot == 1:
                    next_w.team1 = active_team
                elif lb_match.next_match_winner_slot == 2:
                    next_w.team2 = active_team
                if next_w.team1 and next_w.team2 and next_w.status == TournamentMatch.Status.PENDING:
                    next_w.status = TournamentMatch.Status.READY
                next_w.save()


class TournamentMatchService:
    @staticmethod
    def update_match_score(match_id, score1, score2, winner_id=None, decision_reason=None, actor=None):
        """
        Trägt das Spielergebnis für ein Match ein, validiert Scores & Sieger,
        und rückt Sieger/Verlierer atomar unter Row-Locks in die Folgematches vor.
        """
        try:
            score1 = int(score1)
            score2 = int(score2)
        except (ValueError, TypeError):
            raise InvalidScoreError("Ungültiges Punkteformat übergeben.")

        if score1 < 0 or score2 < 0:
            raise InvalidScoreError("Punkte müssen nicht-negative Ganzzahlen (>= 0) sein.")

        with transaction.atomic():
            match = TournamentMatch.objects.select_for_update().select_related(
                'tournament', 'team1', 'team2', 'next_match_winner', 'next_match_loser'
            ).get(pk=match_id)

            # 1. Folgematch-Schutz bei nachträglicher Änderung
            if match.status == TournamentMatch.Status.COMPLETED:
                if match.next_match_winner:
                    next_w = TournamentMatch.objects.select_for_update().get(pk=match.next_match_winner_id)
                    if next_w.status == TournamentMatch.Status.COMPLETED:
                        raise MatchAlreadyCompletedError(
                            "Das Folgematch wurde bereits gespielt und gewertet. Das Ergebnis kann nicht mehr geändert werden."
                        )
                if match.next_match_loser:
                    next_l = TournamentMatch.objects.select_for_update().get(pk=match.next_match_loser_id)
                    if next_l.status == TournamentMatch.Status.COMPLETED:
                        raise MatchAlreadyCompletedError(
                            "Das Folgematch im Loser-Bracket wurde bereits gespielt. Das Ergebnis kann nicht mehr geändert werden."
                        )

            # 2. Sieger bestimmen und plausibilisieren
            winner_team = None
            if winner_id:
                try:
                    winner_id_int = int(winner_id)
                except (ValueError, TypeError):
                    raise InvalidWinnerError("Ungültige Sieger-ID übergeben.")

                if match.team1 and match.team1.id == winner_id_int:
                    winner_team = match.team1
                elif match.team2 and match.team2.id == winner_id_int:
                    winner_team = match.team2
                else:
                    raise InvalidWinnerError("Das ausgewählte Sieger-Team nimmt nicht an diesem Match teil.")
            else:
                if score1 > score2:
                    winner_team = match.team1
                elif score2 > score1:
                    winner_team = match.team2
                else:
                    raise InvalidWinnerError("Unentschieden ist in KO-Matches nicht erlaubt. Bitte Sieger auswählen.")

            if not winner_team:
                raise InvalidWinnerError("Es konnte kein gültiger Sieger ermittelt werden.")

            # Plausibilität: Widerspruch zwischen Score und gewähltem Sieger verlangt Begründung
            score_discrepancy = False
            if score1 > score2 and winner_team == match.team2:
                score_discrepancy = True
            elif score2 > score1 and winner_team == match.team1:
                score_discrepancy = True

            if score_discrepancy:
                if not decision_reason or not str(decision_reason).strip():
                    raise InvalidWinnerError(
                        "Der gewählte Sieger widerspricht dem Punktestand. "
                        "Bitte gib einen Entscheidungsgrund an (z. B. Disqualifikation, Forfeit oder Admin-Entscheidung)."
                    )

            # 3. Match aktualisieren
            match.score_team1 = score1
            match.score_team2 = score2
            match.winner = winner_team
            match.loser = match.team2 if winner_team == match.team1 else match.team1
            match.decision_reason = str(decision_reason).strip() if decision_reason else ""
            match.status = TournamentMatch.Status.COMPLETED
            match.save()

            # 4. Sieger ins Folgematch vorrücken (unter Lock)
            if match.next_match_winner:
                next_w = TournamentMatch.objects.select_for_update().get(pk=match.next_match_winner_id)
                if match.next_match_winner_slot == 1:
                    next_w.team1 = winner_team
                elif match.next_match_winner_slot == 2:
                    next_w.team2 = winner_team
                else:
                    if not next_w.team1:
                        next_w.team1 = winner_team
                    elif not next_w.team2 and next_w.team1 != winner_team:
                        next_w.team2 = winner_team
                    elif next_w.team1 != winner_team and next_w.team2 != winner_team:
                        next_w.team1 = winner_team

                if next_w.team1 and next_w.team2 and not next_w.is_bye and next_w.status == TournamentMatch.Status.PENDING:
                    next_w.status = TournamentMatch.Status.READY
                next_w.save()

            # 5. Verlierer ins Folgematch (unter Lock)
            if match.next_match_loser and match.loser:
                next_l = TournamentMatch.objects.select_for_update().get(pk=match.next_match_loser_id)
                if match.next_match_loser_slot == 1:
                    next_l.team1 = match.loser
                elif match.next_match_loser_slot == 2:
                    next_l.team2 = match.loser
                else:
                    if not next_l.team1:
                        next_l.team1 = match.loser
                    elif not next_l.team2 and next_l.team1 != match.loser:
                        next_l.team2 = match.loser
                    elif next_l.team1 != match.loser and next_l.team2 != match.loser:
                        next_l.team1 = match.loser

                if next_l.team1 and next_l.team2 and not next_l.is_bye and next_l.status == TournamentMatch.Status.PENDING:
                    next_l.status = TournamentMatch.Status.READY
                next_l.save()

                # Prüfen, ob durch BYEs im WB der andere Slot des LB-Matches frei bleibt
                check_and_advance_bye_in_loser_bracket(next_l)

            # 6. Grand Final, Final & Modus-spezifische Abschlusslogik
            tournament = match.tournament
            if match.bracket_type == TournamentMatch.BracketType.GRAND_FINAL:
                if match.winner == match.team1:
                    tournament.status = Tournament.Status.FINISHED
                    tournament.save(update_fields=['status'])
                else:
                    reset_match, _ = TournamentMatch.objects.get_or_create(
                        tournament=tournament,
                        bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET,
                        defaults={
                            'round_number': match.round_number + 1,
                            'match_number': 1,
                            'team1': match.team1,
                            'team2': match.team2,
                            'status': TournamentMatch.Status.READY,
                        }
                    )
            elif match.bracket_type == TournamentMatch.BracketType.GRAND_FINAL_RESET:
                tournament.status = Tournament.Status.FINISHED
                tournament.save(update_fields=['status'])
            elif match.bracket_type == TournamentMatch.BracketType.FINAL:
                if match.next_match_winner is None:
                    tournament.status = Tournament.Status.FINISHED
                    tournament.save(update_fields=['status'])
            elif match.bracket_type == TournamentMatch.BracketType.GROUP:
                if tournament.mode == Tournament.Mode.GROUP_STAGE:
                    GroupStageStandingService.check_and_advance_group_stage(tournament)
                elif tournament.mode == Tournament.Mode.LEAGUE:
                    remaining_matches = tournament.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists()
                    if not remaining_matches:
                        tournament.status = Tournament.Status.FINISHED
                        tournament.save(update_fields=['status'])

            return match, winner_team


class LeagueStandingService:
    @staticmethod
    def generate_round_robin_schedule(teams):
        """
        Erzeugt einen rundenbasierten Spielplan nach dem Berger-System (Circle-Methode).
        Rückgabe: Dict {round_num: [(team1, team2), ...]}
        """
        teams_list = list(teams)
        num_teams = len(teams_list)
        if num_teams < 2:
            return {}

        has_bye = (num_teams % 2 != 0)
        if has_bye:
            teams_list.append(None)

        n = len(teams_list)
        rounds_count = n - 1
        schedule = {}

        current_teams = list(teams_list)
        for r in range(1, rounds_count + 1):
            pairings = []
            for i in range(n // 2):
                t1 = current_teams[i]
                t2 = current_teams[n - 1 - i]
                if t1 is not None and t2 is not None:
                    if r % 2 == 1:
                        pairings.append((t1, t2))
                    else:
                        pairings.append((t2, t1))
            schedule[r] = pairings
            current_teams = [current_teams[0]] + [current_teams[-1]] + current_teams[1:-1]

        return schedule

    @staticmethod
    def calculate_league_standings(tournament):
        """
        Berechnet die dynamische Ligatabelle aus allen bisher gespielten Matches.
        Wertung: Sieg = 3 Pkt, Unentschieden = 1 Pkt, Niederlage = 0 Pkt.
        Tiebreak: 1. Punkte, 2. Direkter Vergleich, 3. Tordifferenz / Score-Diff, 4. Erzielte Scores.
        """
        registrations = tournament.registrations.select_related('team').all()
        teams = [r.team for r in registrations]
        if not teams:
            return []

        stats = {
            team.id: {
                'team': team,
                'played': 0,
                'won': 0,
                'drawn': 0,
                'lost': 0,
                'points': 0,
                'score_for': 0,
                'score_against': 0,
                'score_diff': 0,
                'head_to_head_points': {},
            }
            for team in teams
        }

        matches = tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.GROUP,
            status=TournamentMatch.Status.COMPLETED
        ).select_related('team1', 'team2', 'winner')

        for m in matches:
            if not m.team1 or not m.team2:
                continue
            if m.team1.id not in stats or m.team2.id not in stats:
                continue

            s1 = m.score_team1 if m.score_team1 is not None else 0
            s2 = m.score_team2 if m.score_team2 is not None else 0

            stats[m.team1.id]['played'] += 1
            stats[m.team2.id]['played'] += 1
            stats[m.team1.id]['score_for'] += s1
            stats[m.team1.id]['score_against'] += s2
            stats[m.team2.id]['score_for'] += s2
            stats[m.team2.id]['score_against'] += s1

            if m.winner == m.team1:
                stats[m.team1.id]['won'] += 1
                stats[m.team1.id]['points'] += 3
                stats[m.team2.id]['lost'] += 1
                stats[m.team1.id]['head_to_head_points'][m.team2.id] = 3
                stats[m.team2.id]['head_to_head_points'][m.team1.id] = 0
            elif m.winner == m.team2:
                stats[m.team2.id]['won'] += 1
                stats[m.team2.id]['points'] += 3
                stats[m.team1.id]['lost'] += 1
                stats[m.team2.id]['head_to_head_points'][m.team1.id] = 3
                stats[m.team1.id]['head_to_head_points'][m.team2.id] = 0
            else:
                stats[m.team1.id]['drawn'] += 1
                stats[m.team2.id]['drawn'] += 1
                stats[m.team1.id]['points'] += 1
                stats[m.team2.id]['points'] += 1
                stats[m.team1.id]['head_to_head_points'][m.team2.id] = 1
                stats[m.team2.id]['head_to_head_points'][m.team1.id] = 1

        for s in stats.values():
            s['score_diff'] = s['score_for'] - s['score_against']

        sorted_list = sorted(
            stats.values(),
            key=lambda item: (-item['points'], -item['score_diff'], -item['score_for'], item['team'].name.lower())
        )

        for i in range(len(sorted_list) - 1):
            t_curr = sorted_list[i]
            t_next = sorted_list[i + 1]
            if t_curr['points'] == t_next['points']:
                h2h_curr = t_curr['head_to_head_points'].get(t_next['team'].id, None)
                h2h_next = t_next['head_to_head_points'].get(t_curr['team'].id, None)
                if h2h_curr is not None and h2h_next is not None and h2h_next > h2h_curr:
                    sorted_list[i], sorted_list[i + 1] = sorted_list[i + 1], sorted_list[i]

        for idx, item in enumerate(sorted_list, 1):
            item['rank'] = idx

        return sorted_list


class GroupStageStandingService:
    @staticmethod
    def calculate_group_standings(tournament, group_name):
        """
        Berechnet die Tabelle für eine spezifische Gruppe (z. B. 'Gruppe A' oder 'Gruppe B').
        """
        registrations = tournament.registrations.filter(group_name=group_name).select_related('team')
        teams = [r.team for r in registrations]
        if not teams:
            group_matches = tournament.matches.filter(group_name=group_name)
            team_ids = set()
            for m in group_matches:
                if m.team1:
                    team_ids.add(m.team1.id)
                if m.team2:
                    team_ids.add(m.team2.id)
            teams = list(Team.objects.filter(id__in=team_ids))

        if not teams:
            return []

        stats = {
            team.id: {
                'team': team,
                'played': 0,
                'won': 0,
                'drawn': 0,
                'lost': 0,
                'points': 0,
                'score_for': 0,
                'score_against': 0,
                'score_diff': 0,
                'head_to_head_points': {},
            }
            for team in teams
        }

        matches = tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.GROUP,
            group_name=group_name,
            status=TournamentMatch.Status.COMPLETED
        ).select_related('team1', 'team2', 'winner')

        for m in matches:
            if not m.team1 or not m.team2:
                continue
            if m.team1.id not in stats or m.team2.id not in stats:
                continue

            s1 = m.score_team1 if m.score_team1 is not None else 0
            s2 = m.score_team2 if m.score_team2 is not None else 0

            stats[m.team1.id]['played'] += 1
            stats[m.team2.id]['played'] += 1
            stats[m.team1.id]['score_for'] += s1
            stats[m.team1.id]['score_against'] += s2
            stats[m.team2.id]['score_for'] += s2
            stats[m.team2.id]['score_against'] += s1

            if m.winner == m.team1:
                stats[m.team1.id]['won'] += 1
                stats[m.team1.id]['points'] += 3
                stats[m.team2.id]['lost'] += 1
                stats[m.team1.id]['head_to_head_points'][m.team2.id] = 3
                stats[m.team2.id]['head_to_head_points'][m.team1.id] = 0
            elif m.winner == m.team2:
                stats[m.team2.id]['won'] += 1
                stats[m.team2.id]['points'] += 3
                stats[m.team1.id]['lost'] += 1
                stats[m.team2.id]['head_to_head_points'][m.team1.id] = 3
                stats[m.team1.id]['head_to_head_points'][m.team2.id] = 0
            else:
                stats[m.team1.id]['drawn'] += 1
                stats[m.team2.id]['drawn'] += 1
                stats[m.team1.id]['points'] += 1
                stats[m.team2.id]['points'] += 1
                stats[m.team1.id]['head_to_head_points'][m.team2.id] = 1
                stats[m.team2.id]['head_to_head_points'][m.team1.id] = 1

        for s in stats.values():
            s['score_diff'] = s['score_for'] - s['score_against']

        sorted_list = sorted(
            stats.values(),
            key=lambda item: (-item['points'], -item['score_diff'], -item['score_for'], item['team'].name.lower())
        )

        for i in range(len(sorted_list) - 1):
            t_curr = sorted_list[i]
            t_next = sorted_list[i + 1]
            if t_curr['points'] == t_next['points']:
                h2h_curr = t_curr['head_to_head_points'].get(t_next['team'].id, None)
                h2h_next = t_next['head_to_head_points'].get(t_curr['team'].id, None)
                if h2h_curr is not None and h2h_next is not None and h2h_next > h2h_curr:
                    sorted_list[i], sorted_list[i + 1] = sorted_list[i + 1], sorted_list[i]

        for idx, item in enumerate(sorted_list, 1):
            item['rank'] = idx

        return sorted_list

    @staticmethod
    def check_and_advance_group_stage(tournament):
        """
        Prüft nach jedem Match, ob alle Gruppenspiele beendet sind.
        Falls ja, werden die Gruppenstände ermittelt und die qualifizierten Teams
        automatisch in die Halbfinals / das Finale eingetragen und auf READY gesetzt.
        """
        group_matches = tournament.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP)
        if not group_matches.exists():
            return False

        if group_matches.exclude(status=TournamentMatch.Status.COMPLETED).exists():
            return False

        standings_a = GroupStageStandingService.calculate_group_standings(tournament, 'Gruppe A')
        standings_b = GroupStageStandingService.calculate_group_standings(tournament, 'Gruppe B')

        if not standings_a or not standings_b:
            return False

        team_a1 = standings_a[0]['team'] if len(standings_a) > 0 else None
        team_a2 = standings_a[1]['team'] if len(standings_a) > 1 else None
        team_b1 = standings_b[0]['team'] if len(standings_b) > 0 else None
        team_b2 = standings_b[1]['team'] if len(standings_b) > 1 else None

        semi_matches = list(tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.FINAL,
            round_number=2
        ).order_by('match_number'))

        final_matches = list(tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.FINAL,
            round_number=3
        ).order_by('match_number'))

        if len(semi_matches) == 2 and len(final_matches) == 1:
            hf1 = semi_matches[0]
            hf2 = semi_matches[1]

            hf1.team1 = team_a1
            hf1.team2 = team_b2
            if hf1.team1 and hf1.team2:
                hf1.status = TournamentMatch.Status.READY
            hf1.save(update_fields=['team1', 'team2', 'status'])

            hf2.team1 = team_b1
            hf2.team2 = team_a2
            if hf2.team1 and hf2.team2:
                hf2.status = TournamentMatch.Status.READY
            hf2.save(update_fields=['team1', 'team2', 'status'])
            return True

        if len(semi_matches) == 1:
            final_match = semi_matches[0]
            final_match.team1 = team_a1
            final_match.team2 = team_b1
            if final_match.team1 and final_match.team2:
                final_match.status = TournamentMatch.Status.READY
            final_match.save(update_fields=['team1', 'team2', 'status'])
            return True

        return False


class FFAMatchService:
    @staticmethod
    def update_ffa_scores(match_id, participant_scores, decision_reason=None, actor=None):
        """
        Trägt Ränge und Scores für alle Teilnehmer eines FFA-Matches ein.
        participant_scores: List of dicts, z.B.:
        [{'participant_id': 12, 'rank': 1, 'score': 1500, 'is_disqualified': False, 'notes': ''}, ...]
        """
        with transaction.atomic():
            match = TournamentMatch.objects.select_for_update().select_related('tournament').get(pk=match_id)
            if match.bracket_type != TournamentMatch.BracketType.FFA:
                raise TournamentMatchError("Dieses Match ist kein Free-For-All (FFA) Match.")

            participants = {p.id: p for p in match.participants.select_for_update().select_related('team')}

            winner_participant = None

            for item in participant_scores:
                p_id = item.get('participant_id')
                if not p_id:
                    t_id = item.get('team_id')
                    for p in participants.values():
                        if p.team_id == t_id:
                            p_id = p.id
                            break

                if p_id not in participants:
                    continue

                p = participants[p_id]
                try:
                    rank = int(item['rank']) if item.get('rank') is not None and str(item.get('rank')).strip() != '' else None
                except (ValueError, TypeError):
                    rank = None

                try:
                    score = int(item['score']) if item.get('score') is not None and str(item.get('score')).strip() != '' else 0
                except (ValueError, TypeError):
                    score = 0

                p.rank = rank
                p.score = score
                p.is_disqualified = bool(item.get('is_disqualified', False))
                p.notes = str(item.get('notes', '')).strip()
                p.save(update_fields=['rank', 'score', 'is_disqualified', 'notes'])

                if rank == 1 and not p.is_disqualified:
                    winner_participant = p

            match.status = TournamentMatch.Status.COMPLETED
            if winner_participant:
                match.winner = winner_participant.team
            if decision_reason:
                match.decision_reason = str(decision_reason).strip()
            match.save(update_fields=['status', 'winner', 'decision_reason'])

            tournament = match.tournament
            tournament.status = Tournament.Status.FINISHED
            tournament.save(update_fields=['status'])

            return match, winner_participant.team if winner_participant else None


def advance_match_winner(match, winner_team, score1, score2, decision_reason=None):
    """
    Rückwärtskompatible Wrapper-Funktion, delegiert an TournamentMatchService.
    """
    winner_id = winner_team.id if winner_team else None
    return TournamentMatchService.update_match_score(
        match_id=match.id,
        score1=score1,
        score2=score2,
        winner_id=winner_id,
        decision_reason=decision_reason,
    )


def generate_bracket(tournament, preview=False):
    """
    Hauptfunktion zur Generierung und Vorschau von Turnierbäumen für alle 5 Turniermodi.
    Wenn preview=True, werden keine Daten in die DB geschrieben, sondern ein Dict mit der Vorschau-Struktur geliefert.
    """
    teams = list(tournament.registrations.select_related('team').order_by('registered_at'))
    num_teams = len(teams)

    if tournament.mode == Tournament.Mode.FFA:
        return _generate_ffa(tournament, teams, preview)
    elif tournament.mode == Tournament.Mode.LEAGUE:
        return _generate_league(tournament, teams, preview)
    elif tournament.mode == Tournament.Mode.GROUP_STAGE:
        return _generate_group_stage(tournament, teams, preview)
    elif tournament.mode == Tournament.Mode.DOUBLE_ELIMINATION:
        return _generate_double_elimination(tournament, teams, preview)
    else:
        # Standard: SINGLE_ELIMINATION
        return _generate_single_elimination(tournament, teams, preview)


def _generate_single_elimination(tournament, registered_teams, preview=False):
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 2:
        if preview:
            return {'error': 'Mindestens 2 Teams erforderlich für Turnierbaum-Generierung.'}
        return False

    bracket_size = next_power_of_two(num_teams)
    num_rounds = int(math.log2(bracket_size))
    num_byes = bracket_size - num_teams

    seed_order = generate_standard_seed_order(bracket_size)
    seeded_slots = [teams[s - 1] if s <= num_teams else None for s in seed_order]

    if preview:
        preview_rounds = []
        r1_matches = []
        for i in range(0, bracket_size, 2):
            t1 = seeded_slots[i]
            t2 = seeded_slots[i + 1]
            is_bye = (t2 is None)
            r1_matches.append({
                'match_number': (i // 2) + 1,
                'team1': t1.name if t1 else 'TBD',
                'team2': t2.name if t2 else ('BYE' if is_bye else 'TBD'),
                'is_bye': is_bye,
                'status': 'COMPLETED' if is_bye else 'READY'
            })
        preview_rounds.append({'round': 1, 'name': 'Runde 1', 'matches': r1_matches})

        current_count = len(r1_matches)
        r_num = 2
        while current_count > 1:
            current_count = current_count // 2
            round_name = 'Finale' if current_count == 1 else ('Halbfinale' if current_count == 2 else f'Runde {r_num}')
            m_list = []
            for m_idx in range(1, current_count + 1):
                m_list.append({
                    'match_number': m_idx,
                    'team1': 'Sieger M' + str((m_idx * 2) - 1),
                    'team2': 'Sieger M' + str(m_idx * 2),
                    'is_bye': False,
                    'status': 'PENDING'
                })
            preview_rounds.append({'round': r_num, 'name': round_name, 'matches': m_list})
            r_num += 1

        return {'mode': 'SINGLE_ELIMINATION', 'rounds': preview_rounds, 'total_teams': num_teams, 'byes': num_byes}

    # Echtes Speichern in DB
    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()

        round_matches_db = {}  # round_num -> list of match objects

        for r in range(num_rounds, 0, -1):
            matches_in_round = 2 ** (num_rounds - r)
            round_matches_db[r] = []

            for m in range(matches_in_round):
                match_obj = TournamentMatch(
                    tournament=tournament,
                    round_number=r,
                    match_number=m + 1,
                    bracket_type=TournamentMatch.BracketType.FINAL if r == num_rounds else TournamentMatch.BracketType.WINNERS,
                    status=TournamentMatch.Status.PENDING,
                )
                if r < num_rounds:
                    match_obj.next_match_winner = round_matches_db[r + 1][m // 2]
                    match_obj.next_match_winner_slot = 1 if (m % 2 == 0) else 2
                match_obj.save()
                round_matches_db[r].append(match_obj)

        r1_matches = round_matches_db[1]
        for i in range(0, bracket_size, 2):
            match_idx = i // 2
            m = r1_matches[match_idx]
            t1 = seeded_slots[i]
            t2 = seeded_slots[i + 1]

            m.team1 = t1
            m.team2 = t2

            if t2 is None:
                m.is_bye = True
                m.winner = t1
                m.status = TournamentMatch.Status.COMPLETED
                m.save()

                if m.next_match_winner:
                    nm = m.next_match_winner
                    if m.next_match_winner_slot == 1:
                        nm.team1 = t1
                    else:
                        nm.team2 = t1
                    nm.save()
            else:
                m.status = TournamentMatch.Status.READY
                m.save()

        tournament.is_generated = True
        tournament.status = Tournament.Status.IN_PROGRESS
        tournament.save(update_fields=['is_generated', 'status'])

    return True


def _generate_double_elimination(tournament, registered_teams, preview=False):
    """
    Vollständige, mathematisch hergeleitete Double-Elimination-Baumerzeugung
    für beliebige Teilnehmerzahlen N >= 2 inkl. Nicht-Zweierpotenzen, BYE-Handling,
    deterministischer Slot-Verkettung und Grand Final / Reset.
    """
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 2:
        if preview:
            return {'error': 'Mindestens 2 Teams erforderlich für Double Elimination.'}
        return False

    bracket_size = next_power_of_two(num_teams)
    k = int(math.log2(bracket_size))
    num_byes = bracket_size - num_teams

    seed_order = generate_standard_seed_order(bracket_size)
    seeded_slots = [teams[s - 1] if s <= num_teams else None for s in seed_order]

    if preview:
        wb_rounds_preview = []
        for r in range(1, k + 1):
            m_count = 2 ** (k - r)
            m_list = []
            for m in range(1, m_count + 1):
                if r == 1:
                    t1 = seeded_slots[(m - 1) * 2]
                    t2 = seeded_slots[(m - 1) * 2 + 1]
                    is_bye = (t2 is None and t1 is not None)
                    m_list.append({
                        'match_number': m,
                        'team1': t1.name if t1 else 'TBD',
                        'team2': t2.name if t2 else ('BYE' if is_bye else 'TBD'),
                        'is_bye': is_bye,
                        'status': 'COMPLETED' if is_bye else 'READY'
                    })
                else:
                    m_list.append({
                        'match_number': m,
                        'team1': f"Sieger WB R{r-1} M{m*2-1}",
                        'team2': f"Sieger WB R{r-1} M{m*2}",
                        'is_bye': False,
                        'status': 'PENDING'
                    })
            r_name = "WB Finale" if r == k else f"WB Runde {r}"
            wb_rounds_preview.append({'round': r, 'name': r_name, 'matches': m_list})

        lb_rounds_preview = []
        if k >= 2:
            num_lb_rounds = 2 * (k - 1)
            for r in range(1, num_lb_rounds + 1):
                if r % 2 == 1:
                    m_count = 2 ** (k - 1 - (r + 1) // 2)
                    m_list = []
                    for m in range(1, m_count + 1):
                        if r == 1:
                            t1_desc = f"Verlierer WB R1 M{m*2-1}"
                            t2_desc = f"Verlierer WB R1 M{m*2}"
                        else:
                            t1_desc = f"Sieger LB R{r-1} M{m*2-1}"
                            t2_desc = f"Sieger LB R{r-1} M{m*2}"
                        m_list.append({
                            'match_number': m,
                            'team1': t1_desc,
                            'team2': t2_desc,
                            'is_bye': False,
                            'status': 'PENDING'
                        })
                else:
                    m_count = 2 ** (k - 1 - r // 2)
                    wb_feed_round = (r // 2) + 1
                    m_list = []
                    for m in range(1, m_count + 1):
                        m_list.append({
                            'match_number': m,
                            'team1': f"Sieger LB R{r-1} M{m}",
                            'team2': f"Verlierer WB R{wb_feed_round} M{m}",
                            'is_bye': False,
                            'status': 'PENDING'
                        })
                r_name = "LB Finale" if r == num_lb_rounds else f"LB Runde {r}"
                lb_rounds_preview.append({'round': r, 'name': r_name, 'matches': m_list})

        gf_matches = [{
            'match_number': 1,
            'team1': "Sieger Winner Bracket",
            'team2': "Sieger Loser Bracket" if k >= 2 else "Verlierer WB R1",
            'is_bye': False,
            'status': 'PENDING'
        }]

        return {
            'mode': 'DOUBLE_ELIMINATION',
            'wb_rounds': wb_rounds_preview,
            'lb_rounds': lb_rounds_preview,
            'grand_final': gf_matches,
            'total_teams': num_teams,
            'byes': num_byes,
        }

    # DB Erzeugung
    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()

        # 1. Grand Final Match initialisieren
        grand_final = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.GRAND_FINAL,
            status=TournamentMatch.Status.PENDING,
        )

        # Sonderfall N = 2
        if k == 1:
            wb_final = TournamentMatch.objects.create(
                tournament=tournament,
                round_number=1,
                match_number=1,
                bracket_type=TournamentMatch.BracketType.WINNERS,
                team1=teams[0],
                team2=teams[1],
                status=TournamentMatch.Status.READY,
                next_match_winner=grand_final,
                next_match_winner_slot=1,
                next_match_loser=grand_final,
                next_match_loser_slot=2,
            )
            tournament.is_generated = True
            tournament.status = Tournament.Status.IN_PROGRESS
            tournament.save(update_fields=['is_generated', 'status'])
            return True

        # Für N >= 4 (k >= 2):
        # 2. Winner Bracket Matches (r = 1 .. k)
        wb_matches = {}
        for r in range(1, k + 1):
            m_count = 2 ** (k - r)
            wb_matches[r] = {}
            for m in range(1, m_count + 1):
                match_obj = TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=r,
                    match_number=m,
                    bracket_type=TournamentMatch.BracketType.WINNERS,
                    status=TournamentMatch.Status.PENDING,
                )
                wb_matches[r][m] = match_obj

        # 3. Loser Bracket Matches (r = 1 .. 2(k - 1))
        num_lb_rounds = 2 * (k - 1)
        lb_matches = {}
        for r in range(1, num_lb_rounds + 1):
            if r % 2 == 1:
                m_count = 2 ** (k - 1 - (r + 1) // 2)
            else:
                m_count = 2 ** (k - 1 - r // 2)
            lb_matches[r] = {}
            for m in range(1, m_count + 1):
                match_obj = TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=r,
                    match_number=m,
                    bracket_type=TournamentMatch.BracketType.LOSERS,
                    status=TournamentMatch.Status.PENDING,
                )
                lb_matches[r][m] = match_obj

        # 4. Verknüpfungen für Winner Bracket (Sieger -> nächstes WB Match / Grand Final)
        for r in range(1, k + 1):
            m_count = 2 ** (k - r)
            for m in range(1, m_count + 1):
                match_obj = wb_matches[r][m]
                if r < k:
                    match_obj.next_match_winner = wb_matches[r + 1][(m + 1) // 2]
                    match_obj.next_match_winner_slot = 1 if (m % 2 == 1) else 2
                else:
                    match_obj.next_match_winner = grand_final
                    match_obj.next_match_winner_slot = 1

        # 5. Verknüpfungen für Loser Bracket (Sieger -> nächstes LB Match / Grand Final)
        for r in range(1, num_lb_rounds + 1):
            m_count = len(lb_matches[r])
            for m in range(1, m_count + 1):
                match_obj = lb_matches[r][m]
                if r < num_lb_rounds:
                    if r % 2 == 1:
                        match_obj.next_match_winner = lb_matches[r + 1][m]
                        match_obj.next_match_winner_slot = 1
                    else:
                        match_obj.next_match_winner = lb_matches[r + 1][(m + 1) // 2]
                        match_obj.next_match_winner_slot = 1 if (m % 2 == 1) else 2
                else:
                    match_obj.next_match_winner = grand_final
                    match_obj.next_match_winner_slot = 2

        # 6. Einspeisung aus Winner Bracket ins Loser Bracket (Verlierer -> LB)
        # 6.1 WB Runde 1 -> LB Runde 1
        for m in range(1, (2 ** (k - 1)) + 1):
            wb_m = wb_matches[1][m]
            wb_m.next_match_loser = lb_matches[1][(m + 1) // 2]
            wb_m.next_match_loser_slot = 1 if (m % 2 == 1) else 2

        # 6.2 WB Runde 2 .. k-1 -> LB Major Runden (LB Runde 2, 4, 6, ...)
        for i in range(1, k - 1):
            wb_round = i + 1
            lb_round = 2 * i
            m_count = 2 ** (k - wb_round)
            for m in range(1, m_count + 1):
                wb_m = wb_matches[wb_round][m]
                wb_m.next_match_loser = lb_matches[lb_round][m]
                wb_m.next_match_loser_slot = 2

        # 6.3 WB Finale (WB Runde k, Match 1) -> LB Finale (LB Runde 2(k-1), Match 1)
        wb_final = wb_matches[k][1]
        lb_final = lb_matches[num_lb_rounds][1]
        wb_final.next_match_loser = lb_final
        wb_final.next_match_loser_slot = 2

        # Alle Matches speichern
        for r_dict in wb_matches.values():
            for m_obj in r_dict.values():
                m_obj.save()
        for r_dict in lb_matches.values():
            for m_obj in r_dict.values():
                m_obj.save()

        # 7. Teams und Freilose in WB Runde 1 setzen
        for m in range(1, (bracket_size // 2) + 1):
            match_obj = wb_matches[1][m]
            t1 = seeded_slots[(m - 1) * 2]
            t2 = seeded_slots[(m - 1) * 2 + 1]

            match_obj.team1 = t1
            match_obj.team2 = t2

            if t1 and t2:
                match_obj.status = TournamentMatch.Status.READY
                match_obj.save(update_fields=['team1', 'team2', 'status'])
            elif t1 and not t2:
                match_obj.is_bye = True
                match_obj.winner = t1
                match_obj.loser = None
                match_obj.score_team1 = 0
                match_obj.score_team2 = 0
                match_obj.status = TournamentMatch.Status.COMPLETED
                match_obj.save(update_fields=['team1', 'team2', 'is_bye', 'winner', 'loser', 'score_team1', 'score_team2', 'status'])

                # t1 direkt ins WB Folgematch rücken
                target_wb = match_obj.next_match_winner
                if target_wb:
                    if match_obj.next_match_winner_slot == 1:
                        target_wb.team1 = t1
                    else:
                        target_wb.team2 = t1
                    if target_wb.team1 and target_wb.team2:
                        target_wb.status = TournamentMatch.Status.READY
                    target_wb.save()

                # Prüfen, ob das Ziel-LB-Match von diesem BYE betroffen ist
                if match_obj.next_match_loser:
                    check_and_advance_bye_in_loser_bracket(match_obj.next_match_loser)
            elif not t1 and not t2:
                match_obj.is_bye = True
                match_obj.status = TournamentMatch.Status.COMPLETED
                match_obj.save(update_fields=['team1', 'team2', 'is_bye', 'status'])

        tournament.is_generated = True
        tournament.status = Tournament.Status.IN_PROGRESS
        tournament.save(update_fields=['is_generated', 'status'])

    return True


def _generate_league(tournament, registered_teams, preview=False):
    """
    Erzeugt einen vollständigen rundenbasierten Liga-Spielplan nach dem Berger-System (Round Robin).
    """
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 2:
        if preview:
            return {'error': 'Mindestens 2 Teams erforderlich für Liga.'}
        return False

    schedule = LeagueStandingService.generate_round_robin_schedule(teams)

    if preview:
        rounds_preview = []
        for r_num, pairings in schedule.items():
            matches_list = []
            for m_idx, (t1, t2) in enumerate(pairings, 1):
                matches_list.append({
                    'match_number': m_idx,
                    'team1': t1.name if t1 else 'BYE',
                    'team2': t2.name if t2 else 'BYE',
                    'status': 'READY'
                })
            rounds_preview.append({
                'round': r_num,
                'name': f"Spieltag {r_num}",
                'matches': matches_list
            })
        return {
            'mode': 'LEAGUE',
            'rounds': rounds_preview,
            'total_teams': num_teams
        }

    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()

        for r_num, pairings in schedule.items():
            for m_idx, (t1, t2) in enumerate(pairings, 1):
                TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=r_num,
                    match_number=m_idx,
                    bracket_type=TournamentMatch.BracketType.GROUP,
                    team1=t1,
                    team2=t2,
                    status=TournamentMatch.Status.READY,
                )

        tournament.is_generated = True
        tournament.status = Tournament.Status.IN_PROGRESS
        tournament.save(update_fields=['is_generated', 'status'])

    return True


def _generate_group_stage(tournament, registered_teams, preview=False):
    """
    Erzeugt eine Gruppenphase (Gruppe A & B) mit anschließendem KO-Baum (Halbfinale/Finale).
    """
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 4:
        if preview:
            return {'error': 'Mindestens 4 Teams erforderlich für Gruppenphase.'}
        return False

    # Snake-Verteilung in Gruppe A und B
    group_a = [teams[i] for i in range(len(teams)) if i % 2 == 0]
    group_b = [teams[i] for i in range(len(teams)) if i % 2 == 1]

    schedule_a = LeagueStandingService.generate_round_robin_schedule(group_a)
    schedule_b = LeagueStandingService.generate_round_robin_schedule(group_b)

    has_semifinals = (num_teams >= 8)

    if preview:
        groups_preview = {
            'Gruppe A': [t.name for t in group_a],
            'Gruppe B': [t.name for t in group_b],
        }
        ko_preview = []
        if has_semifinals:
            ko_preview.append({
                'round': 2,
                'name': 'Halbfinale',
                'matches': [
                    {'match_number': 1, 'team1': '1. Gruppe A', 'team2': '2. Gruppe B', 'status': 'PENDING'},
                    {'match_number': 2, 'team1': '1. Gruppe B', 'team2': '2. Gruppe A', 'status': 'PENDING'},
                ]
            })
            ko_preview.append({
                'round': 3,
                'name': 'Finale',
                'matches': [
                    {'match_number': 1, 'team1': 'Sieger Halbfinale 1', 'team2': 'Sieger Halbfinale 2', 'status': 'PENDING'}
                ]
            })
        else:
            ko_preview.append({
                'round': 2,
                'name': 'Finale',
                'matches': [
                    {'match_number': 1, 'team1': '1. Gruppe A', 'team2': '1. Gruppe B', 'status': 'PENDING'}
                ]
            })

        return {
            'mode': 'GROUP_STAGE',
            'groups': groups_preview,
            'ko_stage': ko_preview,
            'total_teams': num_teams,
        }

    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()

        # 1. Gruppen-Zugehörigkeit in Registrierungen hinterlegen
        for reg in registered_teams:
            if reg.team in group_a:
                reg.group_name = 'Gruppe A'
            else:
                reg.group_name = 'Gruppe B'
            reg.save(update_fields=['group_name'])

        # 2. Gruppe A Matches erstellen
        for r_num, pairings in schedule_a.items():
            for m_idx, (t1, t2) in enumerate(pairings, 1):
                TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=r_num,
                    match_number=m_idx,
                    bracket_type=TournamentMatch.BracketType.GROUP,
                    group_name='Gruppe A',
                    team1=t1,
                    team2=t2,
                    status=TournamentMatch.Status.READY,
                )

        # 3. Gruppe B Matches erstellen
        for r_num, pairings in schedule_b.items():
            for m_idx, (t1, t2) in enumerate(pairings, 1):
                TournamentMatch.objects.create(
                    tournament=tournament,
                    round_number=r_num,
                    match_number=m_idx,
                    bracket_type=TournamentMatch.BracketType.GROUP,
                    group_name='Gruppe B',
                    team1=t1,
                    team2=t2,
                    status=TournamentMatch.Status.READY,
                )

        # 4. KO-Phase erstellen
        if has_semifinals:
            # Finale anlegen (Runde 3)
            final_match = TournamentMatch.objects.create(
                tournament=tournament,
                round_number=3,
                match_number=1,
                bracket_type=TournamentMatch.BracketType.FINAL,
                status=TournamentMatch.Status.PENDING,
            )
            # Halbfinale 1 & 2 anlegen (Runde 2)
            TournamentMatch.objects.create(
                tournament=tournament,
                round_number=2,
                match_number=1,
                bracket_type=TournamentMatch.BracketType.FINAL,
                status=TournamentMatch.Status.PENDING,
                next_match_winner=final_match,
                next_match_winner_slot=1,
            )
            TournamentMatch.objects.create(
                tournament=tournament,
                round_number=2,
                match_number=2,
                bracket_type=TournamentMatch.BracketType.FINAL,
                status=TournamentMatch.Status.PENDING,
                next_match_winner=final_match,
                next_match_winner_slot=2,
            )
        else:
            # Direktes Finale (Runde 2)
            TournamentMatch.objects.create(
                tournament=tournament,
                round_number=2,
                match_number=1,
                bracket_type=TournamentMatch.BracketType.FINAL,
                status=TournamentMatch.Status.PENDING,
            )

        tournament.is_generated = True
        tournament.status = Tournament.Status.IN_PROGRESS
        tournament.save(update_fields=['is_generated', 'status'])

    return True


def _generate_ffa(tournament, registered_teams, preview=False):
    """
    Erzeugt ein Free For All (FFA) Match mit n Teilnehmern via TournamentMatchParticipant.
    """
    teams = [r.team for r in registered_teams]
    num_teams = len(teams)

    if num_teams < 2:
        if preview:
            return {'error': 'Mindestens 2 Teilnehmer erforderlich für FFA.'}
        return False

    if preview:
        return {
            'mode': 'FFA',
            'participants': [t.name for t in teams],
            'total_teams': num_teams,
        }

    with transaction.atomic():
        TournamentMatch.objects.filter(tournament=tournament).delete()

        ffa_match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.FFA,
            status=TournamentMatch.Status.READY,
        )

        for team in teams:
            TournamentMatchParticipant.objects.create(
                match=ffa_match,
                team=team,
            )

        tournament.is_generated = True
        tournament.status = Tournament.Status.IN_PROGRESS
        tournament.save(update_fields=['is_generated', 'status'])

    return True
