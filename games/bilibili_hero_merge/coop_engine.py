"""Offline-testable co-op policy. Observations must come from verified evidence.

Coordinates use 432x768. No board geometry, ranks or successful inputs are
inferred from elapsed time. The live visual observer is a separate adapter.
"""
from dataclasses import dataclass, field
from policy import price_action, merge_pair


@dataclass
class Observation:
    layer: str
    prices: dict = field(default_factory=dict)
    cells: set = field(default_factory=set)
    units: dict = field(default_factory=dict)
    occupied: set = field(default_factory=set)
    summon_count: int | None = None  # total, not the modulo-5 UI counter
    board_verified: bool = False
    token: str = ''  # stable modal identity, independent of animated background


class Engine:
    def __init__(self, config, side, max_checks=4):
        if side not in ('host', 'guest'):
            raise ValueError('Unknown side')
        self.config, self.side = config, side
        self.pending = None
        self.max_checks = max_checks
        self.stopped = False

    def stop(self, reason):
        self.stopped = True
        return {'kind': 'stop', 'reason': reason}

    def valid_board(self, obs):
        left, right = (20, 195) if self.side == 'host' else (240, 412)
        return (obs.board_verified and bool(obs.cells)
                and all(left <= x <= right and 380 <= y <= 600 for x, y in obs.cells)
                and obs.occupied <= obs.cells
                and set(obs.units) <= obs.occupied
                and all(u.get('hero') in self.config['heroes'] for u in obs.units.values()))

    def next(self, obs):
        if self.stopped:
            return {'kind': 'stop', 'reason': 'already_stopped'}
        if obs.layer == 'settled':
            self.pending = None
            self.stopped = True
            return {'kind': 'settled'}
        # Modal actions also require a subsequent changed observation. Never
        # repeat clicks indefinitely on a modal that did not close.
        if self.pending and self.pending['kind'] in ('close_reward', 'choose_buff'):
            p = self.pending
            if (obs.layer, obs.token) == p['modal']:
                return self.wait_pending()
            self.pending = p['previous']
        if obs.layer in ('reward', 'choice'):
            kind = 'close_reward' if obs.layer == 'reward' else 'choose_buff'
            self.pending = {'kind': kind, 'modal': (obs.layer, obs.token),
                            'checks': 0, 'previous': self.pending}
            return {'kind': kind}
        if obs.layer != 'battle':
            return self.stop('unrecognized_top_layer')
        if not self.valid_board(obs):
            return self.stop('board_observer_not_verified')
        if any(not isinstance(obs.prices.get(k), int) or isinstance(obs.prices[k], bool)
               or obs.prices[k] < 0 for k in ('upgrade', 'summon', 'money')):
            return self.stop('prices_unreadable')
        if self.pending:
            p = self.pending
            if p['kind'] == 'summon':
                new = obs.occupied - p['occupied']
                verified = (obs.summon_count == p['count'] + 1
                            and obs.prices['summon'] != p['price']
                            and len(new) == 1 and next(iter(new)) in obs.units
                            and obs.units[next(iter(new))].get('tier') == 1)
            elif p['kind'] == 'upgrade':
                verified = obs.prices['upgrade'] > p['price']
            else:
                result = obs.units.get(p['b'], {})
                verified = (p['a'] not in obs.occupied and p['b'] in obs.occupied
                            and result.get('hero') in self.config['heroes']
                            and result.get('tier') == p['tier'] + 1
                            and not result.get('uncertain')
                            and obs.occupied == p['occupied'] - {p['a']})
            if not verified:
                return self.wait_pending()
            self.pending = None
            return {'kind': 'verified', 'action': p['kind']}
        if obs.summon_count is None or obs.summon_count < 0:
            return self.stop('total_summon_count_unknown')
        # Reuse the same policy as StrategicBot.decide: excess support first,
        # then next-price ratio; damage merges only when summoning needs space.
        pair = merge_pair(obs.units, self.config) if obs.summon_count >= 5 else None
        if pair:
            return self.merge(obs, pair)
        e, s, money = (obs.prices[k] for k in ('upgrade', 'summon', 'money'))
        action = 'summon' if obs.summon_count < 5 else price_action(e, s, self.config)
        if action == 'summon' and obs.occupied == obs.cells:
            if money < s:
                return {'kind': 'wait'}
            pair = merge_pair(obs.units, self.config, must_free_slot=True)
            if pair:
                return self.merge(obs, pair)
            # Unknown units/ranks cannot justify a full-board upgrade fallback.
            if set(obs.units) != obs.occupied or any(u.get('tier', 0) < 1 or u.get('uncertain') for u in obs.units.values()):
                return self.stop('full_board_has_unknown_units')
            if obs.summon_count < 5:
                return self.stop('strengthen_not_unlocked')
            action = 'upgrade'
        cost = s if action == 'summon' else e
        if money < cost:
            return {'kind': 'wait'}
        self.pending = {'kind': action, 'price': cost, 'count': obs.summon_count,
                        'occupied': set(obs.occupied), 'checks': 0}
        return {'kind': action}

    def merge(self, obs, pair):
        a, b = pair
        self.pending = {'kind': 'merge', 'a': a, 'b': b,
                        'tier': obs.units[a]['tier'], 'occupied': set(obs.occupied), 'checks': 0}
        return {'kind': 'merge', 'source': a, 'target': b}

    def wait_pending(self):
        self.pending['checks'] += 1
        if self.pending['checks'] >= self.max_checks:
            return self.stop('action_not_verified')
        return {'kind': 'wait'}
