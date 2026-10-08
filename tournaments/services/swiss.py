"""Round-by-round Swiss tournaments: deterministic pairings and explicit publication.

All mutations lock Event -> Tournament -> Registration/Match. A preview token binds
publication to the exact results, roster and random seed shown to the organiser.
"""
import hashlib
import json
import random
import secrets

import networkx as nx
from django.core import signing
from django.db import transaction

from events.models import Event
from tournaments.exceptions import TournamentBracketError, MatchAlreadyCompletedError, SwissPairingError
from configuration.translations import get_translation
from tournaments.models import Tournament, TournamentRegistration, TournamentMatch, SwissRound, SwissRoundEntry

TOKEN_SALT = 'tournaments.swiss.publish.v1'


def _locked_tournament(tournament_id, actor=None):
    from .locking import lock_tournament
    tournament = lock_tournament(tournament_id)
    event = tournament.event
    if tournament.mode != Tournament.Mode.SWISS:
        raise TournamentBracketError('Diese Aktion ist nur für das Schweizer System verfügbar.')
    if actor is not None and not tournament.is_managed_by(actor):
        raise TournamentBracketError('Nur die Turnierleitung darf Schweizer Runden freigeben.')
    if event.effective_status in (Event.Status.FINISHED, Event.Status.CANCELLED):
        raise TournamentBracketError('Die Veranstaltung ist beendet oder abgesagt.')
    if tournament.status in (Tournament.Status.FINISHED, Tournament.Status.CANCELLED):
        raise TournamentBracketError('Das Turnier ist bereits beendet oder abgesagt.')
    if actor is not None and not tournament.is_generated:
        from .registration import validate_start_roster
        validate_start_roster(tournament)
    return tournament


class SwissStandingService:
    @staticmethod
    def calculate(tournament):
        registrations = list(tournament.registrations.select_related('team').order_by('seed', 'pk'))
        rows = {r.team_id: {
            'registration': r, 'team': r.team, 'seed': r.seed or r.pk, 'points': 0,
            'played': 0, 'won': 0, 'drawn': 0, 'lost': 0, 'byes': 0, 'walkovers': 0,
            'buchholz': 0, 'sonneborn_berger': 0, 'withdrawn': r.is_forfeited,
            'rounds': 0, 'rank': None,
        } for r in registrations}
        matches = list(tournament.matches.filter(bracket_type=TournamentMatch.BracketType.SWISS,
                          status=TournamentMatch.Status.COMPLETED).select_related('team1', 'team2'))
        contributions = []
        for match in matches:
            for team_id, opponent_id in ((match.team1_id, match.team2_id), (match.team2_id, match.team1_id)):
                if team_id not in rows:
                    continue
                row = rows[team_id]
                row['rounds'] += 1
                if match.result_type == TournamentMatch.ResultType.DOUBLE_FORFEIT:
                    earned = 0
                    row['lost'] += 1
                elif match.winner_id == team_id:
                    earned = 3
                    row['won'] += 1
                elif match.winner_id is None and not match.is_bye:
                    earned = 1
                    row['drawn'] += 1
                else:
                    earned = 0
                    row['lost'] += 1
                row['points'] += earned
                if match.result_type == TournamentMatch.ResultType.BYE:
                    row['byes'] += 1
                elif match.result_type == TournamentMatch.ResultType.WALKOVER and earned:
                    row['walkovers'] += 1
                elif match.result_type == TournamentMatch.ResultType.PLAYED:
                    row['played'] += 1
                contributions.append((team_id, opponent_id, earned, match.result_type))

        published = tournament.swiss_round_records.count()
        # Subsequent absent rounds after withdrawal contribute neutral draw points
        # to opponents' strength, never to the withdrawn participant's own points.
        adjusted = {team_id: row['points'] + (max(0, published - row['rounds']) if row['withdrawn'] else 0)
                    for team_id, row in rows.items()}
        for team_id, opponent_id, earned, kind in contributions:
            row = rows[team_id]
            if kind == TournamentMatch.ResultType.PLAYED:
                strength = adjusted.get(opponent_id, 0)
            else:
                # Dummy opponent: own score, capped by R draw points for a bye,
                # or the scheduled opponent's adjusted score for a forfeit.
                cap = adjusted.get(opponent_id, 0) if opponent_id else tournament.swiss_rounds
                strength = min(row['points'], cap)
            row['buchholz'] += strength
            row['sonneborn_berger'] += strength * earned

        standings = sorted(rows.values(), key=lambda r: (r['withdrawn'], -r['points'], -r['buchholz'],
                                                        -r['sonneborn_berger'], r['seed'], r['team'].pk))
        last_key = None
        rank = 0
        for index, row in enumerate((r for r in standings if not r['withdrawn']), 1):
            key = (row['points'], row['buchholz'], row['sonneborn_berger'])
            if key != last_key:
                rank, last_key = index, key
            row['rank'] = rank
        return standings


class SwissPairingService:
    @staticmethod
    def pair(standings, previous_pairs, bye_winners, seed, number, *, allow_repeats=False):
        if allow_repeats:
            try:
                return SwissPairingService.pair(standings, previous_pairs, bye_winners, seed, number)
            except SwissPairingError:
                pass
        active = [row for row in standings if not row['withdrawn']]
        if len(active) < 2:
            raise TournamentBracketError('Für eine weitere Runde sind mindestens zwei aktive Teilnehmer erforderlich.')
        active_ids = {row['team'].pk for row in active}
        candidates = [None]
        if len(active) % 2:
            candidates = [r for r in reversed(active) if allow_repeats or r['team'].pk not in bye_winners]
            if not candidates:
                raise SwissPairingError('Kein Teilnehmer ist mehr für ein Freilos berechtigt. Die Runde kann nicht ausgelost werden.')
        n = len(active)
        # Integer weights make score-group proximity dominate all secondary preferences.
        tie_scale = n * 65536 + 1
        score_scale = (n * max(row['seed'] for row in active) + 1) * tie_scale
        max_weight = max(row['points'] for row in active) * score_scale + (max(row['seed'] for row in active) + n) * tie_scale + 65536
        repeat_penalty = n * max_weight + 1
        best = None
        for bye in candidates:
            players = [r for r in active if bye is None or r['team'].pk != bye['team'].pk]
            graph = nx.Graph()
            graph.add_nodes_from(sorted(r['team'].pk for r in players))
            for i, left in enumerate(players):
                for right in players[i + 1:]:
                    a, b = sorted((left['team'].pk, right['team'].pk))
                    repeated = (a, b) in previous_pairs
                    if repeated and not allow_repeats:
                        continue
                    tie = int(hashlib.sha256(f'{seed}:{number}:{a}:{b}'.encode()).hexdigest()[:4], 16)
                    distance = abs(abs(left['seed'] - right['seed']) - max(1, len(players) // 2))
                    weight = abs(left['points'] - right['points']) * score_scale + distance * tie_scale + tie
                    if repeated:
                        weight += repeat_penalty
                    graph.add_edge(a, b, weight=weight)
            matching = nx.min_weight_matching(graph)
            if len(matching) * 2 != len(players):
                continue
            by_id = {r['team'].pk: r for r in players}
            pairs = [tuple(sorted(pair, key=lambda team_id: by_id[team_id]['seed'])) for pair in matching]
            pairs.sort(key=lambda pair: (-by_id[pair[0]]['points'], by_id[pair[0]]['seed']))
            if bye is not None:
                pairs.append((bye['team'].pk, None))
            assert {team for pair in pairs for team in pair if team is not None} == active_ids
            if not allow_repeats:
                return pairs
            cost = (bool(bye and bye['team'].pk in bye_winners),
                    sum(tuple(sorted((a, b))) in previous_pairs for a, b in pairs if b is not None),
                    sum(graph[a][b]['weight'] for a, b in pairs if b is not None))
            if best is None or cost < best[0]:
                best = (cost, pairs)
        if best:
            return best[1]
        raise SwissPairingError('Keine vollständige Paarung ohne Wiederholungen möglich. Bitte Rundenanzahl und Rückzüge prüfen.')


class SwissTournamentService:
    @staticmethod
    def _plan(tournament, seed, *, allow_repeats=False, initial_order=None, initial_pairs=None):
        if tournament.is_generated and (initial_order is not None or initial_pairs is not None):
            raise TournamentBracketError(get_translation('draw_unavailable'))
        if tournament.is_generated:
            if tournament.status != Tournament.Status.IN_PROGRESS:
                raise TournamentBracketError('Das Turnier läuft nicht.')
            last = tournament.swiss_round_records.order_by('-number').first()
            if last is None or last.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists():
                raise TournamentBracketError('Zuerst müssen alle Ergebnisse der aktuellen Runde vorliegen.')
            number = last.number + 1
            if number > tournament.swiss_rounds:
                raise TournamentBracketError('Alle vorgesehenen Runden sind bereits abgeschlossen.')
        else:
            if tournament.status not in (Tournament.Status.REGISTRATION_OPEN, Tournament.Status.REGISTRATION_CLOSED):
                raise TournamentBracketError('Bitte zuerst die Turnieranmeldung öffnen oder schließen.')
            number = 1
        registrations = list(tournament.registrations.select_related('team').order_by('pk'))
        count = sum(not r.is_forfeited for r in registrations)
        if number == 1 and (count < 2 or tournament.swiss_rounds > count - (count % 2 == 0)):
            raise TournamentBracketError('Die Rundenzahl passt nicht zur Teilnehmerzahl: bei gerader Zahl höchstens N−1, bei ungerader höchstens N Runden.')
        standings = SwissStandingService.calculate(tournament)
        if number == 1:
            seeded = sorted((r for r in registrations if not r.is_forfeited and r.seed is not None), key=lambda r: (r.seed, r.pk))
            if len({r.seed for r in seeded}) != len(seeded):
                raise TournamentBracketError('Die vorhandenen Seeds müssen eindeutig sein.')
            unseeded = [r for r in registrations if not r.is_forfeited and r.seed is None]
            random.Random(seed).shuffle(unseeded)
            ordered_ids = [r.pk for r in seeded + unseeded]
            if initial_order is not None:
                if (not isinstance(initial_order, list) or len(initial_order) != len(ordered_ids)
                        or set(initial_order) != set(ordered_ids)):
                    raise TournamentBracketError(get_translation('draw_invalid_teams'))
                ordered_ids = initial_order
            order = {registration_id: index for index, registration_id in enumerate(ordered_ids, 1)}
            for row in standings:
                row['seed'] = order.get(row['registration'].pk, len(registrations) + row['registration'].pk)
            standings.sort(key=lambda r: (r['withdrawn'], r['seed']))
        history = list(tournament.matches.filter(bracket_type=TournamentMatch.BracketType.SWISS).values(
            'id', 'round_number', 'team1_id', 'team2_id', 'winner_id', 'score_team1', 'score_team2', 'status', 'result_type'))
        previous_pairs = {tuple(sorted((m['team1_id'], m['team2_id']))) for m in history if m['team1_id'] and m['team2_id']}
        bye_winners = {m['winner_id'] for m in history if m['status'] == TournamentMatch.Status.COMPLETED
                       and m['result_type'] in (TournamentMatch.ResultType.BYE, TournamentMatch.ResultType.WALKOVER)}
        if initial_pairs is None:
            pairs = SwissPairingService.pair(standings, previous_pairs, bye_winners, seed, number, allow_repeats=allow_repeats)
        else:
            active_ids = {r['team'].pk for r in standings if not r['withdrawn']}
            paired_ids = [value for pair in initial_pairs for value in pair if value is not None]
            if (len(paired_ids) != len(active_ids) or set(paired_ids) != active_ids
                    or sum(b is None for a, b in initial_pairs) != len(active_ids) % 2
                    or any(a is None for a, b in initial_pairs)):
                raise TournamentBracketError(get_translation('draw_invalid_teams'))
            pairs = initial_pairs
        snapshot = [{'registration_id': r['registration'].pk, 'team_id': r['team'].pk, 'seed': r['seed'],
                     'points': r['points'], 'buchholz': r['buchholz'], 'sonneborn_berger': r['sonneborn_berger'],
                     'withdrawn': r['withdrawn']} for r in standings]
        repeated = [(a, b) for a, b in pairs if (b is None and a in bye_winners)
                    or (b is not None and tuple(sorted((a, b))) in previous_pairs)]
        digest_data = {'round': number, 'seed': seed, 'allow_repeats': allow_repeats,
                       'rules': [tournament.swiss_rounds, tournament.swiss_allow_draws, tournament.roster_rule],
                       'registrations': [(r.pk, r.team_id, r.team.name, r.seed, r.is_forfeited) for r in registrations],
                       'history': history}
        digest = hashlib.sha256(json.dumps(digest_data, sort_keys=True).encode()).hexdigest()
        by_id = {r['team'].pk: r for r in standings}
        return {'number': number, 'seed': seed, 'digest': digest, 'snapshot': snapshot, 'pairs': pairs,
                'allow_repeats': allow_repeats, 'has_repeats': bool(repeated), 'repeated_pairs': repeated,
                'pairings': [{'team1': by_id[a]['team'], 'team2': by_id[b]['team'] if b else None,
                              'seed1': by_id[a]['seed'], 'seed2': by_id[b]['seed'] if b else None,
                              'repeated': (a, b) in repeated}
                             for a, b in pairs]}

    @staticmethod
    @transaction.atomic
    def preview(tournament_id, actor=None, *, allow_repeats=False):
        tournament = _locked_tournament(tournament_id, actor)
        seed = tournament.swiss_pairing_seed if tournament.is_generated else secrets.randbits(31)
        plan = SwissTournamentService._plan(tournament, seed, allow_repeats=allow_repeats)
        plan['token'] = signing.dumps({'tournament': tournament.pk, 'number': plan['number'],
                                      'seed': seed, 'digest': plan['digest'], 'allow_repeats': allow_repeats}, salt=TOKEN_SALT)
        return plan

    @staticmethod
    @transaction.atomic
    def publish(tournament_id, actor=None, token=None, *, approve_repeats=False, initial_draw=None):
        tournament = _locked_tournament(tournament_id, actor)
        if initial_draw is not None and (tournament.is_generated or token is not None):
            raise TournamentBracketError(get_translation('draw_unavailable'))
        if token:
            try:
                claim = signing.loads(token, salt=TOKEN_SALT, max_age=600)
                if claim['tournament'] != tournament.pk:
                    raise signing.BadSignature()
            except (signing.BadSignature, KeyError, TypeError):
                raise TournamentBracketError('Die Vorschau ist ungültig oder abgelaufen. Bitte erneut aufrufen.')
            seed = claim['seed']
            allow_repeats = claim.get('allow_repeats', False)
            if not isinstance(allow_repeats, bool):
                raise TournamentBracketError(get_translation('format_swiss_invalid_approval'))
        else:
            if tournament.is_generated:
                raise TournamentBracketError('Bitte zuerst die nächste Runde in der Vorschau prüfen.')
            seed = initial_draw['random_seed'] if initial_draw is not None else secrets.randbits(31)
            allow_repeats = False
        plan = SwissTournamentService._plan(tournament, seed, allow_repeats=allow_repeats,
            initial_order=initial_draw['order'] if initial_draw is not None else None,
            initial_pairs=initial_draw['pairs'] if initial_draw is not None else None)
        if plan['has_repeats'] and approve_repeats is not True:
            raise TournamentBracketError(get_translation('format_swiss_approval_required'))
        if token and (claim['number'] != plan['number'] or claim['digest'] != plan['digest']):
            raise TournamentBracketError('Ergebnisse oder Teilnehmer haben sich seit der Vorschau geändert. Bitte erneut prüfen.')
        if plan['number'] == 1:
            for row in plan['snapshot']:
                TournamentRegistration.objects.filter(pk=row['registration_id']).update(seed=row['seed'])
            tournament.swiss_pairing_seed = seed
            tournament.is_generated = True
            tournament.status = Tournament.Status.IN_PROGRESS
            tournament.save(update_fields=['swiss_pairing_seed', 'is_generated', 'status'])
        round_record = SwissRound.objects.create(tournament=tournament, number=plan['number'],
            published_by=actor, input_digest=plan['digest'], standings_snapshot=plan['snapshot'],
            repeat_pairings_approved=plan['has_repeats'])
        rows = {r['team_id']: r for r in plan['snapshot']}
        for index, (a, b) in enumerate(plan['pairs'], 1):
            match = TournamentMatch.objects.create(tournament=tournament, swiss_round=round_record,
                bracket_type=TournamentMatch.BracketType.SWISS, round_number=plan['number'], match_number=index,
                team1_id=a, team2_id=b, is_bye=b is None, winner_id=a if b is None else None,
                result_type=TournamentMatch.ResultType.BYE if b is None else TournamentMatch.ResultType.PLAYED,
                status=TournamentMatch.Status.COMPLETED if b is None else TournamentMatch.Status.READY,
                decision_reason=get_translation('format_swiss_repeat') if (a, b) in plan['repeated_pairs']
                    else ('Freilos (3 Punkte)' if b is None else ''))
            for team_id in (a, b):
                if team_id is not None:
                    SwissRoundEntry.objects.create(round=round_record, match=match, team_id=team_id,
                        registration_id=rows[team_id]['registration_id'], seed=rows[team_id]['seed'])
        return round_record

    @staticmethod
    def validate_score_change(match, tournament):
        if match.result_type != TournamentMatch.ResultType.PLAYED:
            raise MatchAlreadyCompletedError('Freilose und kampflose Ergebnisse können nicht als gespieltes Match geändert werden.')
        if tournament.status not in (Tournament.Status.IN_PROGRESS, Tournament.Status.RESULTS_REVIEW):
            raise MatchAlreadyCompletedError('Das Schweizer Turnier läuft nicht.')
        if tournament.swiss_round_records.filter(number__gt=match.round_number).exists():
            raise MatchAlreadyCompletedError('Die nächste Runde ist bereits veröffentlicht. Das frühere Ergebnis ist gesperrt.')

    @staticmethod
    def sync_completion(tournament):
        from .results import sync_review
        sync_review(tournament)

    @staticmethod
    @transaction.atomic
    def withdraw(tournament_id, team_id, reason='Aufgabe', actor=None):
        tournament = _locked_tournament(tournament_id, actor)
        reason = str(reason).strip() or 'Aufgabe'
        if len(reason) > 255:
            raise TournamentBracketError('Der Rückzugsgrund darf höchstens 255 Zeichen enthalten.')
        if not tournament.is_generated:
            raise TournamentBracketError('Vor dem Start bitte die reguläre Abmeldung verwenden.')
        registration = TournamentRegistration.objects.select_for_update().get(tournament=tournament, team_id=team_id)
        registration.is_forfeited = True
        registration.save(update_fields=['is_forfeited'])
        matches = tournament.matches.select_for_update().filter(bracket_type=TournamentMatch.BracketType.SWISS)
        from django.db.models import Q
        for match in matches.filter(Q(team1_id=team_id) | Q(team2_id=team_id)).exclude(status=TournamentMatch.Status.COMPLETED):
            opponent_id = match.team2_id if match.team1_id == team_id else match.team1_id
            opponent_active = opponent_id and not tournament.registrations.filter(team_id=opponent_id, is_forfeited=True).exists()
            match.winner_id = opponent_id if opponent_active else None
            match.loser_id = team_id if opponent_active else None
            match.result_type = TournamentMatch.ResultType.WALKOVER if opponent_active else TournamentMatch.ResultType.DOUBLE_FORFEIT
            match.score_team1 = match.score_team2 = None
            match.decision_reason = reason
            match.status = TournamentMatch.Status.COMPLETED
            match.save()
        SwissTournamentService.sync_completion(tournament)
