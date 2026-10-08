"""Read-only draw drafts and atomic publication of the exact approved positions."""
import hashlib
import json
import random
import secrets
import uuid
from itertools import combinations

import networkx as nx
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction

from clans.models import Clan, ClanMembership
from configuration.translations import get_translation
from tournaments.exceptions import TournamentBracketError, TournamentError
from tournaments.models import Team, TeamMember, Tournament, TournamentDraw
from .brackets import TournamentBracketService, _generate_bracket, generate_standard_seed_order, next_power_of_two
from .locking import event_is_closed, lock_tournament
from .registration import validate_start_roster
from .standings import LeagueStandingService
from .validation import identifier

TOKEN_SALT = 'tournaments.draw.v1'
TOKEN_MAX_AGE = 1800
SUPPORTED_MODES = set(Tournament.Mode.values)


def _error(key, **values):
    return TournamentBracketError(get_translation(key, **values))


def _authorize(tournament, actor):
    fresh_actor = get_user_model().objects.filter(pk=actor.pk).first() if actor and actor.is_authenticated else None
    if not tournament.is_managed_by(fresh_actor) or fresh_actor.is_banned:
        raise PermissionDenied(get_translation('draw_permission'))


def _editable(tournament):
    if (tournament.mode not in SUPPORTED_MODES or event_is_closed(tournament) or tournament.is_generated
            or tournament.status not in (Tournament.Status.REGISTRATION_OPEN, Tournament.Status.REGISTRATION_CLOSED)):
        raise _error('draw_unavailable')


def _source(tournament):
    """Snapshot under Event -> Tournament -> Registration/Team locks, without nullable joins."""
    registrations = list(tournament.registrations.select_for_update().order_by('pk'))
    teams = {team.pk: team for team in Team.objects.select_for_update().filter(
        pk__in=[r.team_id for r in registrations]).order_by('pk')}
    members = list(TeamMember.objects.filter(team_id__in=teams).select_related('user').order_by('team_id', 'pk'))
    roster = {team_id: [] for team_id in teams}
    for member in members:
        roster[member.team_id].append((member.user_id, member.status, member.role,
            member.user.is_active, member.user.is_banned, str(member.user.deleted_at)))
    for registration in registrations:
        registration.team = teams[registration.team_id]
    data = {
        'tournament': [tournament.pk, tournament.mode, tournament.status, tournament.is_generated,
            tournament.event_id, tournament.game_id, tournament.game.team_size, tournament.roster_rule,
            tournament.play_third_place, tournament.group_qualifiers_per_group, tournament.standings_tiebreak,
            tournament.swiss_rounds, tournament.swiss_allow_draws, tournament.updated_at.isoformat()],
        'event': [tournament.event.status, tournament.event.end_date.isoformat(), event_is_closed(tournament)],
        'registrations': [(r.pk, r.team_id, r.seed, r.is_forfeited, r.draw_clan_id,
            r.team.name, r.team.tag, r.team.captain_id, r.team.game_id, r.team.event_id,
            r.team.is_archived, r.team.updated_at.isoformat(), roster[r.team_id]) for r in registrations],
    }
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return [r for r in registrations if not r.is_forfeited], digest, roster


def _base_order(registrations):
    seeded = [r.seed for r in registrations if r.seed is not None]
    if len(set(seeded)) != len(seeded):
        raise _error('draw_duplicate_seeds')
    return [r.pk for r in sorted(registrations, key=lambda r: (r.seed is None, r.seed or 0, r.registered_at, r.pk))]


def _position_pairs(tournament, count):
    if tournament.mode == Tournament.Mode.FFA:
        return []
    if tournament.mode == Tournament.Mode.LEAGUE:
        if count % 2:
            return [(index, count - index) for index in range(1, count // 2 + 1)] + [(0, None)]
        return [(index, count - 1 - index) for index in range(count // 2)]
    if tournament.mode == Tournament.Mode.SWISS:
        pairs = [(index, index + count // 2) for index in range(count // 2)]
        return pairs + ([(count - 1, None)] if count % 2 else [])
    if tournament.mode == Tournament.Mode.GROUP_STAGE:
        groups = _group_positions(count)
        return [pair for positions in groups for pair in LeagueStandingService.generate_round_robin_schedule(positions).get(1, [])]
    slots = [seed - 1 if seed <= count else None for seed in generate_standard_seed_order(next_power_of_two(count))]
    return list(zip(slots[::2], slots[1::2]))


def _group_positions(count):
    return [[index for index in range(count) if index % 4 in remainder] for remainder in ((0, 3), (1, 2))]


def _validate_plan(plan, tournament, actor, registrations, digest):
    if (plan.get('version') != 1 or plan.get('tournament') != tournament.pk or plan.get('actor') != actor.pk
            or plan.get('mode') != tournament.mode):
        raise _error('draw_invalid')
    if plan.get('digest') != digest:
        raise _error('draw_stale')
    order = plan.get('order')
    active = {r.pk for r in registrations}
    if (not isinstance(order, list) or any(type(value) is not int for value in order)
            or len(order) != len(active) or set(order) != active):
        raise _error('draw_invalid_teams')
    if (type(plan.get('respect_seeds')) is not bool or type(plan.get('avoid_clans')) is not bool
            or type(plan.get('random_seed')) is not int or not 0 <= plan['random_seed'] < 2**31
            or plan.get('method') not in ('standard', 'random', 'manual')):
        raise _error('draw_invalid_options')
    if tournament.mode == Tournament.Mode.FFA and (plan['avoid_clans'] or not plan['respect_seeds']):
        raise _error('draw_invalid_options')
    try:
        uuid.UUID(plan['request'])
    except (KeyError, TypeError, ValueError, AttributeError):
        raise _error('draw_invalid')
    clans = plan.get('clans')
    if not isinstance(clans, dict) or set(clans) != {str(value) for value in active}:
        raise _error('draw_invalid_clans')
    if any(value is not None and type(value) is not int for value in clans.values()):
        raise _error('draw_invalid_clans')
    clan_ids = {value for value in clans.values() if value is not None}
    if set(Clan.objects.filter(pk__in=clan_ids).values_list('pk', flat=True)) != clan_ids:
        raise _error('draw_invalid_clans')
    base = _base_order(registrations)
    by_id = {r.pk: r for r in registrations}
    if plan['respect_seeds'] and any(by_id[value].seed is not None and order[index] != value
                                      for index, value in enumerate(base)):
        raise _error('draw_seed_locked')


def _read_token(token, tournament, actor):
    try:
        if not isinstance(token, str) or len(token) > 100000:
            raise ValueError()
        plan = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
        if not isinstance(plan, dict) or plan['tournament'] != tournament.pk or plan['actor'] != actor.pk:
            raise ValueError()
        uuid.UUID(plan['request'])
        return plan
    except (signing.BadSignature, KeyError, TypeError, ValueError, AttributeError):
        raise _error('draw_invalid')


def _shuffle_pairs(plan, tournament, registrations):
    """Minimum-conflict matching with fixed seeds and canonical, legal bye positions."""
    rng = random.Random(plan['random_seed'])
    base = _base_order(registrations)
    by_id = {r.pk: r for r in registrations}
    locked = {index: value for index, value in enumerate(base)
              if plan['respect_seeds'] and by_id[value].seed is not None}
    free = [value for value in base if value not in locked.values()]
    order = [locked.get(index) for index in range(len(base))]
    anchors, pair_positions = [], []
    for left, right in _position_pairs(tournament, len(base)):
        free_positions = [pos for pos in (left, right) if pos is not None and pos not in locked]
        if len(free_positions) == 2:
            pair_positions.append(tuple(free_positions))
        elif len(free_positions) == 1:
            opponent = next((locked[pos] for pos in (left, right) if pos in locked), None)
            anchors.append((free_positions[0], opponent))
    graph = nx.Graph()
    players = [('team', value) for value in free]
    slots = [('slot', pos) for pos, _ in anchors]
    graph.add_nodes_from(players + slots)
    penalty = (len(players) + len(slots) + 1) * 65536

    def weight(left, right):
        clan = plan['clans'].get(str(left))
        conflict = plan['avoid_clans'] and clan is not None and clan == plan['clans'].get(str(right))
        return int(conflict) * penalty + rng.randrange(65536)

    for index, left in enumerate(free):
        for right in free[index + 1:]:
            graph.add_edge(('team', left), ('team', right), weight=weight(left, right))
        for pos, opponent in anchors:
            graph.add_edge(('team', left), ('slot', pos), weight=weight(left, opponent))
    matching = nx.min_weight_matching(graph)
    if len(matching) * 2 != len(graph):
        raise _error('draw_invalid_teams')
    pairs = []
    for a, b in sorted(tuple(sorted(pair)) for pair in matching):
        if a[0] == 'slot' or b[0] == 'slot':
            slot, team = (a, b) if a[0] == 'slot' else (b, a)
            order[slot[1]] = team[1]
        else:
            pair = [a[1], b[1]]
            rng.shuffle(pair)
            pairs.append(pair)
    rng.shuffle(pairs)
    for positions, pair in zip(pair_positions, pairs):
        for pos, value in zip(positions, pair):
            order[pos] = value
    return order


def _shuffle_groups(plan, registrations):
    """Min-cost flow minimizes clan encounters inside balanced groups, keeping seeded slots."""
    rng = random.Random(plan['random_seed'])
    base = _base_order(registrations)
    by_id = {r.pk: r for r in registrations}
    locked = {index: value for index, value in enumerate(base)
              if plan['respect_seeds'] and by_id[value].seed is not None}
    free = [value for value in base if value not in locked.values()]
    order = [locked.get(index) for index in range(len(base))]
    if not plan['avoid_clans']:
        rng.shuffle(free)
        iterator = iter(free)
        return [value if value is not None else next(iterator) for value in order]
    positions = _group_positions(len(base))
    free_positions = [[pos for pos in group if pos not in locked] for group in positions]
    buckets = {}
    for value in free:
        buckets.setdefault(plan['clans'][str(value)], []).append(value)
    graph = nx.DiGraph()
    source, sink = ('source',), ('sink',)
    penalty = (len(free) + 1) * 65536
    for group_index, slots in enumerate(free_positions):
        graph.add_edge(('group', group_index), sink, capacity=len(slots), weight=0)
    for bucket_index, (clan, values) in enumerate(sorted(buckets.items(), key=lambda pair: pair[0] or 0)):
        bucket = ('clan', bucket_index)
        graph.add_edge(source, bucket, capacity=len(values), weight=0)
        for group_index, group in enumerate(positions):
            fixed_count = sum(plan['clans'][str(locked[pos])] == clan for pos in group if pos in locked) if clan is not None else 0
            for step in range(min(len(values), len(free_positions[group_index]))):
                unit = ('unit', bucket_index, group_index, step)
                cost = (fixed_count + step) * penalty if clan is not None else 0
                graph.add_edge(bucket, unit, capacity=1, weight=cost + rng.randrange(65536))
                graph.add_edge(unit, ('group', group_index), capacity=1, weight=0)
    if not free:
        return base
    flow = nx.max_flow_min_cost(graph, source, sink)
    allocated = [[], []]
    for bucket_index, (clan, values) in enumerate(sorted(buckets.items(), key=lambda pair: pair[0] or 0)):
        rng.shuffle(values)
        cursor = 0
        for group_index in range(2):
            count = sum(flow[('clan', bucket_index)].get(('unit', bucket_index, group_index, step), 0)
                        for step in range(min(len(values), len(free_positions[group_index]))))
            allocated[group_index].extend(values[cursor:cursor + count])
            cursor += count
        if cursor != len(values):
            raise _error('draw_invalid_teams')
    for slots, values in zip(free_positions, allocated):
        rng.shuffle(values)
        for pos, value in zip(slots, values):
            order[pos] = value
    return order


def _describe(plan, tournament, registrations, roster):
    by_id = {r.pk: r for r in registrations}
    clans = {clan.pk: clan for clan in Clan.objects.order_by('name', 'pk')}
    suggestions = {m.user_id: m.clan_id for m in ClanMembership.objects.filter(
        user_id__in=[r.team.captain_id for r in registrations], status=ClanMembership.Status.ACCEPTED)}
    rows = []
    for position, value in enumerate(plan['order']):
        registration = by_id[value]
        clan_id = plan['clans'][str(value)]
        rows.append({'id': value, 'position': position + 1, 'team': registration.team, 'seed': registration.seed,
            'locked': plan['respect_seeds'] and registration.seed is not None,
            'clan_id': clan_id, 'clan': clans.get(clan_id),
            'suggested_clan': clans.get(suggestions.get(registration.team.captain_id)),
            'roster_count': sum(member[1] == TeamMember.Status.ACCEPTED for member in roster[registration.team_id])})
    by_position = {index: row for index, row in enumerate(rows)}
    conflicts, pairs = [], []
    for number, (left, right) in enumerate(_position_pairs(tournament, len(rows)), 1):
        first, second = by_position.get(left), by_position.get(right)
        conflict = bool(first and second and first['clan_id'] is not None and first['clan_id'] == second['clan_id'])
        pair = {'number': number, 'team1': first, 'team2': second, 'conflict': conflict}
        pairs.append(pair)
        if conflict:
            conflicts.append({'team1': first['team'].name, 'team2': second['team'].name, 'clan': first['clan'].name})
    if tournament.mode == Tournament.Mode.SWISS:
        from .swiss import SwissTournamentService
        preview = SwissTournamentService._plan(tournament, plan['random_seed'], initial_order=plan['order'],
            initial_pairs=[(pair['team1']['team'].pk, pair['team2']['team'].pk if pair['team2'] else None) for pair in pairs])
    else:
        preview = _generate_bracket(tournament, preview=True, registration_order=plan['order'])
    groups = []
    if tournament.mode == Tournament.Mode.GROUP_STAGE:
        conflicts = []
        for index, positions in enumerate(_group_positions(len(rows))):
            group_rows = [rows[pos] for pos in positions]
            groups.append({'name': get_translation('draw_group_a' if index == 0 else 'draw_group_b'), 'rows': group_rows})
            for first, second in combinations(group_rows, 2):
                if first['clan_id'] is not None and first['clan_id'] == second['clan_id']:
                    conflicts.append({'team1': first['team'].name, 'team2': second['team'].name, 'clan': first['clan'].name})
    return {'tournament': tournament, 'token': signing.dumps(plan, salt=TOKEN_SALT, compress=True),
        'rows': rows, 'clans': list(clans.values()), 'pairs': pairs, 'conflicts': conflicts,
        'conflict_count': len(conflicts), 'needs_approval': plan['avoid_clans'] and bool(conflicts),
        'respect_seeds': plan['respect_seeds'], 'avoid_clans': plan['avoid_clans'],
        'preview': preview, 'method': get_translation(f"draw_method_{plan['method']}"),
        'editable_positions': tournament.mode != Tournament.Mode.FFA, 'groups': groups,
        'is_group': tournament.mode == Tournament.Mode.GROUP_STAGE,
        'is_ffa': tournament.mode == Tournament.Mode.FFA, 'is_swiss': tournament.mode == Tournament.Mode.SWISS}


class TournamentDrawService:
    @staticmethod
    @transaction.atomic
    def preview(tournament_id, *, actor, token=None):
        tournament = lock_tournament(tournament_id)
        _authorize(tournament, actor)
        _editable(tournament)
        registrations, digest, roster = _source(tournament)
        minimum = 4 if tournament.mode == Tournament.Mode.GROUP_STAGE else 2
        if len(registrations) < minimum:
            raise _error('draw_minimum', count=minimum)
        if token is not None:
            plan = _read_token(token, tournament, actor)
            _validate_plan(plan, tournament, actor, registrations, digest)
            return _describe(plan, tournament, registrations, roster)
        plan = {'version': 1, 'tournament': tournament.pk, 'actor': actor.pk, 'mode': tournament.mode,
            'digest': digest, 'request': str(uuid.uuid4()), 'random_seed': secrets.randbits(31),
            'order': _base_order(registrations), 'clans': {str(r.pk): r.draw_clan_id for r in registrations},
            'respect_seeds': True, 'avoid_clans': tournament.mode != Tournament.Mode.FFA, 'method': 'standard'}
        return _describe(plan, tournament, registrations, roster)

    @staticmethod
    @transaction.atomic
    def revise(tournament_id, *, actor, token, action, clans, respect_seeds, avoid_clans,
               swap_first=None, swap_second=None):
        tournament = lock_tournament(tournament_id)
        _authorize(tournament, actor)
        _editable(tournament)
        registrations, digest, roster = _source(tournament)
        plan = _read_token(token, tournament, actor)
        _validate_plan(plan, tournament, actor, registrations, digest)
        if type(respect_seeds) is not bool or type(avoid_clans) is not bool:
            raise _error('draw_invalid_options')
        if not isinstance(clans, dict):
            raise _error('draw_invalid_clans')
        try:
            normalized = {str(identifier(key)): identifier(value) if value not in ('', None) else None
                          for key, value in clans.items()}
        except TournamentError:
            raise _error('draw_invalid_clans')
        if len(normalized) != len(clans):
            raise _error('draw_invalid_clans')
        if respect_seeds and not plan['respect_seeds']:
            plan['order'] = _base_order(registrations)
        plan.update(clans=normalized, respect_seeds=respect_seeds, avoid_clans=avoid_clans)
        _validate_plan(plan, tournament, actor, registrations, digest)
        if tournament.mode == Tournament.Mode.FFA and action not in ('apply', 'suggest'):
            raise _error('draw_invalid_options')
        if action == 'shuffle':
            plan['random_seed'] = secrets.randbits(31)
            plan['order'] = (_shuffle_groups(plan, registrations) if tournament.mode == Tournament.Mode.GROUP_STAGE
                             else _shuffle_pairs(plan, tournament, registrations))
            plan['method'] = 'random'
        elif action == 'swap':
            try:
                first, second = identifier(swap_first), identifier(swap_second)
                if first == second or first not in plan['order'] or second not in plan['order']:
                    raise ValueError()
            except (TournamentError, ValueError):
                raise _error('draw_invalid_swap')
            a, b = plan['order'].index(first), plan['order'].index(second)
            plan['order'][a], plan['order'][b] = plan['order'][b], plan['order'][a]
            plan['method'] = 'manual'
        elif action == 'suggest':
            suggestions = {m.user_id: m.clan_id for m in ClanMembership.objects.filter(
                user_id__in=[r.team.captain_id for r in registrations], status=ClanMembership.Status.ACCEPTED)}
            for registration in registrations:
                key = str(registration.pk)
                if plan['clans'][key] is None:
                    plan['clans'][key] = suggestions.get(registration.team.captain_id)
        elif action != 'apply':
            raise _error('draw_invalid_options')
        plan['request'] = str(uuid.uuid4())
        _validate_plan(plan, tournament, actor, registrations, digest)
        return _describe(plan, tournament, registrations, roster)

    @staticmethod
    @transaction.atomic
    def publish(tournament_id, *, actor, token, approve_conflicts=False, reason=''):
        tournament = lock_tournament(tournament_id)
        _authorize(tournament, actor)
        plan = _read_token(token, tournament, actor)
        existing = TournamentDraw.objects.filter(request_id=plan.get('request'), tournament=tournament).first()
        if existing:
            return existing, False
        _editable(tournament)
        registrations, digest, roster = _source(tournament)
        _validate_plan(plan, tournament, actor, registrations, digest)
        clan_ids = {value for value in plan['clans'].values() if value is not None}
        if set(Clan.objects.select_for_update().filter(pk__in=clan_ids).order_by('pk').values_list('pk', flat=True)) != clan_ids:
            raise _error('draw_invalid_clans')
        described = _describe(plan, tournament, registrations, roster)
        if not isinstance(reason, str) or len(reason.strip()) > 1000:
            raise _error('draw_approval_required')
        if described['needs_approval'] and (approve_conflicts is not True or not reason.strip()):
            raise _error('draw_approval_required')
        validate_start_roster(tournament)
        for registration in registrations:
            registration.draw_clan_id = plan['clans'][str(registration.pk)]
        tournament.registrations.model.objects.bulk_update(registrations, ['draw_clan'])
        if tournament.mode == Tournament.Mode.SWISS:
            from .swiss import SwissTournamentService
            SwissTournamentService.publish(tournament.pk, actor=actor,
                initial_draw={'random_seed': plan['random_seed'], 'order': plan['order'],
                    'pairs': described['preview']['pairs']})
        else:
            TournamentBracketService.generate_bracket(tournament.pk, actor=actor, registration_order=plan['order'])
        log = TournamentDraw.objects.create(tournament=tournament, actor=actor, request_id=plan['request'],
            mode=tournament.mode, method=plan['method'], random_seed=plan['random_seed'],
            respect_seeds=plan['respect_seeds'], avoid_clans=plan['avoid_clans'], input_digest=digest,
            conflict_count=described['conflict_count'], reason=reason.strip(),
            snapshot={'order': plan['order'], 'groups': [{'name': group['name'],
                'team_ids': [row['team'].pk for row in group['rows']]} for group in described['groups']],
                'participants': [{'registration_id': row['id'], 'position': row['position'],
                'team_id': row['team'].pk, 'team': row['team'].name, 'seed': row['seed'],
                'clan_id': row['clan_id'], 'clan': row['clan'].name if row['clan'] else ''} for row in described['rows']],
                'pairs': [{'team1_id': pair['team1']['team'].pk if pair['team1'] else None,
                           'team2_id': pair['team2']['team'].pk if pair['team2'] else None} for pair in described['pairs']]})
        return log, True
