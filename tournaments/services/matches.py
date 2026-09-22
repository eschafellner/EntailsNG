import math
from django.db import transaction

from tournaments.models import (
    Tournament,
    TournamentMatch,
    TournamentRegistration,
    TournamentMatchParticipant,
)
from tournaments.exceptions import (
    TournamentError,
    TournamentMatchError,
    MatchAlreadyCompletedError,
    InvalidScoreError,
    InvalidWinnerError,
    MatchPermissionDeniedError,
    MatchNotReadyError,
)


def check_and_advance_match(match, visited=None):
    """
    Universelle Prüfung und Weiterschaltung für ein Match im Turnierbaum.

    Berücksichtigt alle Zuflüsse (sowohl aus prev_matches_winner als auch prev_matches_loser)
    und unterscheidet präzise zwischen:
    - 'FILLED': Ein Team ist für diesen Slot bereits gesetzt oder verfügbar.
    - 'PENDING': Der Zubringer für diesen Slot ist noch nicht COMPLETED (Teilnehmer steht noch aus).
    - 'EMPTY': Der Slot bleibt endgültig leer (kein Zubringer vorhanden oder Zubringer COMPLETED ohne Teilnehmer).
    """
    if visited is None:
        visited = set()
    if not match or match.id in visited:
        return
    visited.add(match.id)

    # Wenn Match bereits beendet ist, nichts tun
    if match.status == TournamentMatch.Status.COMPLETED or match.is_bye:
        return

    # Ermittle alle aufgegebenen Teams in diesem Turnier
    forfeited_team_ids = set(
        TournamentRegistration.objects.filter(
            tournament_id=match.tournament_id,
            is_forfeited=True,
        ).values_list('team_id', flat=True)
    )

    def is_forfeited(t):
        return t is not None and t.id in forfeited_team_ids

    def evaluate_slot(slot_num):
        team = match.team1 if slot_num == 1 else match.team2
        if team is not None:
            if is_forfeited(team):
                if slot_num == 1:
                    match.team1 = None
                else:
                    match.team2 = None
                return 'EMPTY', None
            return 'FILLED', team

        prev_w = list(match.prev_matches_winner.filter(next_match_winner_slot=slot_num))
        prev_l = list(match.prev_matches_loser.filter(next_match_loser_slot=slot_num))
        feeders = prev_w + prev_l

        if not feeders:
            return 'EMPTY', None

        # Wenn mindestens ein Zubringer noch nicht beendet ist -> PENDING
        if any(f.status != TournamentMatch.Status.COMPLETED for f in feeders):
            return 'PENDING', None

        # Alle Zubringer sind COMPLETED. Prüfen, ob ein Teilnehmer bereitsteht
        for f in prev_w:
            if f.winner and not is_forfeited(f.winner):
                return 'FILLED', f.winner
        for f in prev_l:
            if f.loser and not is_forfeited(f.loser):
                return 'FILLED', f.loser

        return 'EMPTY', None

    orig_team1 = match.team1
    orig_team2 = match.team2

    state1, team1 = evaluate_slot(1)
    state2, team2 = evaluate_slot(2)

    updated_teams = (match.team1 != orig_team1) or (match.team2 != orig_team2)
    if state1 == 'FILLED' and match.team1 != team1:
        match.team1 = team1
        updated_teams = True
    if state2 == 'FILLED' and match.team2 != team2:
        match.team2 = team2
        updated_teams = True

    # Fall 1: Beide Slots besetzt -> Match ist spielbereit
    if state1 == 'FILLED' and state2 == 'FILLED':
        if match.status == TournamentMatch.Status.PENDING or updated_teams:
            match.status = TournamentMatch.Status.READY
            match.save(update_fields=['team1', 'team2', 'status'])
        return

    # Fall 2: Mindestens ein Slot steht noch aus -> Match muss warten
    if state1 == 'PENDING' or state2 == 'PENDING':
        if updated_teams:
            match.save(update_fields=['team1', 'team2'])
        return

    # Fall 3: Genau ein Slot besetzt, der andere endgültig leer -> FREILOS (BYE)
    if (state1 == 'FILLED' and state2 == 'EMPTY') or (state1 == 'EMPTY' and state2 == 'FILLED'):
        active_team = team1 if state1 == 'FILLED' else team2
        match.is_bye = True
        match.winner = active_team
        match.loser = None
        match.score_team1 = 0
        match.score_team2 = 0
        match.status = TournamentMatch.Status.COMPLETED
        if not match.decision_reason:
            match.decision_reason = "Freilos (BYE)"
        match.save(update_fields=['team1', 'team2', 'is_bye', 'winner', 'loser', 'score_team1', 'score_team2', 'status', 'decision_reason'])

        # Sieger ins Folgematch weiterreichen
        if match.next_match_winner:
            next_w = TournamentMatch.objects.select_for_update().get(pk=match.next_match_winner_id)
            if match.next_match_winner_slot == 1:
                next_w.team1 = active_team
            elif match.next_match_winner_slot == 2:
                next_w.team2 = active_team
            else:
                if not next_w.team1:
                    next_w.team1 = active_team
                elif not next_w.team2:
                    next_w.team2 = active_team
            next_w.save()
            check_and_advance_match(next_w, visited)

        # Falls ein Verlierer-Folgematch existiert (wobei Loser=None ist)
        if match.next_match_loser:
            next_l = TournamentMatch.objects.select_for_update().get(pk=match.next_match_loser_id)
            check_and_advance_match(next_l, visited)

        return

    # Fall 4: Beide Slots endgültig leer -> leeres Match abschließen
    if state1 == 'EMPTY' and state2 == 'EMPTY':
        match.is_bye = True
        match.winner = None
        match.loser = None
        match.status = TournamentMatch.Status.COMPLETED
        match.save(update_fields=['team1', 'team2', 'is_bye', 'winner', 'loser', 'status'])

        if match.next_match_winner:
            next_w = TournamentMatch.objects.select_for_update().get(pk=match.next_match_winner_id)
            check_and_advance_match(next_w, visited)
        if match.next_match_loser:
            next_l = TournamentMatch.objects.select_for_update().get(pk=match.next_match_loser_id)
            check_and_advance_match(next_l, visited)
        return


def check_and_advance_bye_in_loser_bracket(lb_match):
    """Abwärtskompatibler Wrapper zur Prüfung und Weiterleitung im Loser Bracket."""
    return check_and_advance_match(lb_match)


def check_and_advance_bye_or_walkover(match):
    """
    Abwärtskompatibler Wrapper zur Prüfung und Weiterleitung von Freilosen/Walkovers.
    Delegiert an die universelle check_and_advance_match Funktion.
    """
    return check_and_advance_match(match)


class TournamentMatchService:
    @staticmethod
    def update_match_score(match_id, score1, score2, winner_id=None, decision_reason=None, actor=None):
        """
        Trägt das Spielergebnis für ein Match ein, validiert Berechtigungen, Scores & Sieger
        atomar unter Row-Locks, und rückt Sieger/Verlierer in die Folgematches vor.
        """
        from tournaments.services.standings import GroupStageStandingService

        try:
            score1 = int(score1)
            score2 = int(score2)
        except (ValueError, TypeError):
            raise InvalidScoreError("Ungültiges Punkteformat übergeben.")

        if score1 < 0 or score2 < 0:
            raise InvalidScoreError("Punkte müssen nicht-negative Ganzzahlen (>= 0) sein.")

        with transaction.atomic():
            match = TournamentMatch.objects.select_for_update(of=('self',)).select_related('tournament', 'team1', 'team2').get(pk=match_id)
            tournament = match.tournament

            allows_draw = (
                match.bracket_type == TournamentMatch.BracketType.GROUP
                or tournament.mode == Tournament.Mode.LEAGUE
            )

            # 0. Berechtigungen und Match-Vollständigkeit prüfen (unter Lock)
            is_admin = tournament.is_managed_by(actor) if actor else True

            if actor is not None and not is_admin:
                is_team1_member = bool(match.team1 and match.team1.is_member(actor))
                is_team2_member = bool(match.team2 and match.team2.is_member(actor))

                if not is_team1_member and not is_team2_member:
                    raise MatchPermissionDeniedError("Keine Berechtigung zur Ergebniseingabe für dieses Match.")

                if match.status == TournamentMatch.Status.COMPLETED:
                    raise MatchPermissionDeniedError(
                        "Dieses Match wurde bereits gewertet und kann nur von einem Turnier-Admin bearbeitet werden."
                    )

                if not match.team1 or not match.team2:
                    raise MatchNotReadyError("Das Match ist noch nicht vollständig mit Teams besetzt.")

                # Fairplay-Schutz: Teilnehmer können nur die eigene Niederlage bestätigen (Gegner als Sieger)
                # Bei erlaubten Unentschieden (Liga/Gruppe) wird bei Punktgleichheit kein Sieger forciert
                if is_team1_member and not is_team2_member:
                    if allows_draw and score1 == score2:
                        winner_id = None
                        if not decision_reason:
                            decision_reason = f"Unentschieden bestätigt durch {actor.username} ({match.team1.name})"
                    else:
                        if winner_id and int(winner_id) != match.team2.id:
                            raise InvalidWinnerError(
                                "Teilnehmer können nur die eigene Niederlage bestätigen. Um einen Sieg für dein Team einzutragen, muss der Gegner das Ergebnis bestätigen oder ein Admin kontaktiert werden."
                            )
                        winner_id = match.team2.id
                        if not decision_reason:
                            decision_reason = f"Niederlage bestätigt durch {actor.username} ({match.team1.name})"

                elif is_team2_member and not is_team1_member:
                    if allows_draw and score1 == score2:
                        winner_id = None
                        if not decision_reason:
                            decision_reason = f"Unentschieden bestätigt durch {actor.username} ({match.team2.name})"
                    else:
                        if winner_id and int(winner_id) != match.team1.id:
                            raise InvalidWinnerError(
                                "Teilnehmer können nur die eigene Niederlage bestätigen. Um einen Sieg für dein Team einzutragen, muss der Gegner das Ergebnis bestätigen oder ein Admin kontaktiert werden."
                            )
                        winner_id = match.team1.id
                        if not decision_reason:
                            decision_reason = f"Niederlage bestätigt durch {actor.username} ({match.team2.name})"

            if not match.is_bye and (not match.team1 or not match.team2):
                raise MatchNotReadyError("Das Match ist noch nicht vollständig mit Teams besetzt.")

            # 1. Schutz für bereits abgeschlossene Turniere
            if tournament.status == Tournament.Status.FINISHED:
                raise MatchAlreadyCompletedError(
                    "Das Turnier ist bereits abgeschlossen. Ergebnisse können nicht mehr geändert werden."
                )

            # 2. Folgematch-Schutz bei nachträglicher Änderung
            if match.status == TournamentMatch.Status.COMPLETED:
                if match.next_match_winner:
                    next_w = TournamentMatch.objects.select_for_update().get(pk=match.next_match_winner_id)
                    if next_w.status in [TournamentMatch.Status.IN_PROGRESS, TournamentMatch.Status.COMPLETED]:
                        raise MatchAlreadyCompletedError(
                            "Das Folgematch wurde bereits gespielt und gewertet. Das Ergebnis kann nicht mehr geändert werden."
                        )
                if match.next_match_loser:
                    next_l = TournamentMatch.objects.select_for_update().get(pk=match.next_match_loser_id)
                    if next_l.status in [TournamentMatch.Status.IN_PROGRESS, TournamentMatch.Status.COMPLETED]:
                        raise MatchAlreadyCompletedError(
                            "Das Folgematch im Loser-Bracket wurde bereits gespielt. Das Ergebnis kann nicht mehr geändert werden."
                        )
                # Schutz für Gruppenphase: wenn Finalphase bereits begonnen hat
                if match.bracket_type == TournamentMatch.BracketType.GROUP:
                    if tournament.matches.filter(
                        bracket_type=TournamentMatch.BracketType.FINAL,
                        status__in=[TournamentMatch.Status.IN_PROGRESS, TournamentMatch.Status.COMPLETED]
                    ).exists():
                        raise MatchAlreadyCompletedError(
                            "Die Finalspiele wurden bereits begonnen oder beendet. Das Gruppenergebnis kann nicht mehr geändert werden."
                        )
                # Schutz für Grand Final: wenn Grand Final Reset bereits begonnen hat
                if match.bracket_type == TournamentMatch.BracketType.GRAND_FINAL:
                    if tournament.matches.filter(
                        bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET,
                        status__in=[TournamentMatch.Status.IN_PROGRESS, TournamentMatch.Status.COMPLETED]
                    ).exists():
                        raise MatchAlreadyCompletedError(
                            "Das Grand Final Reset Match wurde bereits begonnen oder beendet. Das Grand Final Ergebnis kann nicht mehr geändert werden."
                        )

            # 3. Sieger bestimmen und plausibilisieren
            allows_draw = (
                match.bracket_type == TournamentMatch.BracketType.GROUP
                or tournament.mode == Tournament.Mode.LEAGUE
            )

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
                    if not allows_draw:
                        raise InvalidWinnerError("Unentschieden ist in KO-Matches nicht erlaubt. Bitte Sieger auswählen.")

            if not winner_team and not (allows_draw and score1 == score2 and not winner_id):
                raise InvalidWinnerError("Es konnte kein gültiger Sieger ermittelt werden.")

            # Plausibilität: Widerspruch zwischen Score und gewähltem Sieger verlangt Begründung
            score_discrepancy = False
            if winner_team:
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

            # 4. Match aktualisieren
            match.score_team1 = score1
            match.score_team2 = score2
            match.winner = winner_team
            if winner_team:
                match.loser = match.team2 if winner_team == match.team1 else match.team1
            else:
                match.loser = None
            match.decision_reason = str(decision_reason).strip() if decision_reason else ""
            match.status = TournamentMatch.Status.COMPLETED
            match.save()

            # 5. Sieger ins Folgematch vorrücken (unter Lock)
            if match.next_match_winner:
                next_w = TournamentMatch.objects.select_for_update().get(pk=match.next_match_winner_id)
                if winner_team and not TournamentRegistration.objects.filter(tournament=tournament, team=winner_team, is_forfeited=True).exists():
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
                check_and_advance_match(next_w)

            # 6. Verlierer ins Folgematch (unter Lock)
            if match.next_match_loser:
                next_l = TournamentMatch.objects.select_for_update().get(pk=match.next_match_loser_id)
                loser = match.loser
                if loser and not TournamentRegistration.objects.filter(tournament=tournament, team=loser, is_forfeited=True).exists():
                    if match.next_match_loser_slot == 1:
                        next_l.team1 = loser
                    elif match.next_match_loser_slot == 2:
                        next_l.team2 = loser
                    else:
                        if not next_l.team1:
                            next_l.team1 = loser
                        elif not next_l.team2 and next_l.team1 != loser:
                            next_l.team2 = loser
                        elif next_l.team1 != loser and next_l.team2 != loser:
                            next_l.team1 = loser

                    if next_l.team1 and next_l.team2 and not next_l.is_bye and next_l.status == TournamentMatch.Status.PENDING:
                        next_l.status = TournamentMatch.Status.READY
                    next_l.save()

                check_and_advance_match(next_l)

            # 7. Grand Final, Final & Modus-spezifische Abschlusslogik
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

            # Globale Abschlussprüfung: Wenn keine offenen Spiele mehr existieren, ist das Turnier beendet
            if tournament.status != Tournament.Status.FINISHED:
                has_open_matches = tournament.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists()
                if not has_open_matches and tournament.matches.exists():
                    tournament.status = Tournament.Status.FINISHED
                    tournament.save(update_fields=['status'])

            return match, winner_team


class FFAMatchService:
    @staticmethod
    def update_ffa_scores(match_id, participant_scores, decision_reason=None, actor=None):
        """
        Trägt Ränge und Scores für alle Teilnehmer eines FFA-Matches ein.
        participant_scores: List of dicts, z.B.:
        [{'participant_id': 12, 'rank': 1, 'score': 1500, 'is_disqualified': False, 'notes': ''}, ...]
        """
        if not participant_scores:
            raise TournamentMatchError("Es wurden keine Teilnehmer-Ergebnisse übergeben.")

        with transaction.atomic():
            match = TournamentMatch.objects.select_for_update().get(pk=match_id)
            if actor is not None and not match.tournament.is_managed_by(actor):
                raise MatchPermissionDeniedError("FFA-Ergebnisse können nur von einem Turnier-Admin eingetragen werden.")

            if match.bracket_type != TournamentMatch.BracketType.FFA:
                raise TournamentMatchError("Dieses Match ist kein Free-For-All (FFA) Match.")

            participants = {p.id: p for p in match.participants.select_for_update()}
            if not participants:
                raise TournamentMatchError("Das Match hat keine registrierten Teilnehmer.")

            winner_participant = None
            rank_1_count = 0
            valid_entries = []

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

                try:
                    rank = int(item['rank']) if item.get('rank') is not None and str(item.get('rank')).strip() != '' else None
                except (ValueError, TypeError):
                    rank = None

                try:
                    score = int(item['score']) if item.get('score') is not None and str(item.get('score')).strip() != '' else 0
                except (ValueError, TypeError):
                    score = 0

                is_disqualified = bool(item.get('is_disqualified', False))
                notes = str(item.get('notes', '')).strip()

                if rank == 1 and not is_disqualified:
                    rank_1_count += 1

                valid_entries.append((participants[p_id], rank, score, is_disqualified, notes))

            if not valid_entries:
                raise TournamentMatchError("Es wurden keine gültigen Teilnehmer-Ergebnisse übergeben.")

            if rank_1_count > 1:
                raise TournamentMatchError("Mehrere Teilnehmer können nicht gleichzeitig Rang 1 belegen.")

            for p, rank, score, is_disqualified, notes in valid_entries:
                p.rank = rank
                p.score = score
                p.is_disqualified = is_disqualified
                p.notes = notes
                p.save(update_fields=['rank', 'score', 'is_disqualified', 'notes'])

                if rank == 1 and not is_disqualified:
                    winner_participant = p

            match.status = TournamentMatch.Status.COMPLETED
            match.winner = winner_participant.team if winner_participant else None
            if decision_reason:
                match.decision_reason = str(decision_reason).strip()
            match.save(update_fields=['status', 'winner', 'decision_reason'])

            tournament = match.tournament
            if winner_participant:
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
