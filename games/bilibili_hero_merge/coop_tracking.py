"""Verified action history, independent of screenshots and ADB."""
from copy import deepcopy


class Tracker:
    def __init__(self):
        self.units={}
        self.summons=None
        self.cells=set()
        self.prices={}
        self.wave=None

    def initialize(self, obs, first_wave=False):
        # An empty board alone does NOT mean a fresh run: the saved screenshot
        # has an empty host board but a summon price of 190.
        initial_price = obs.prices.get('summon') == 0 or (first_wave and len(obs.cells)==7 and obs.prices.get('summon')==10)
        if not obs.board_verified or obs.occupied or not initial_price:
            raise ValueError('Fresh start requires a verified empty board and free summon, or wave 1 with seven empty cells and summon price 10; otherwise use a same-battle checkpoint')
        self.summons=0
        self.cells=set(obs.cells)

    def reconcile(self, obs, pending, identify):
        """Identify unknown/new pieces; infer ranks only from verified deltas.

        identify(pos) returns a configured hero or None. Its implementation
        must stop if an unrelated modal appears while opening unit details.
        """
        if not obs.board_verified:
            return obs
        if not self.cells <= obs.cells:
            raise ValueError('Previously verified wall cells disappeared')
        units=deepcopy(self.units)
        if pending and pending['kind']=='summon':
            new=obs.occupied-pending['occupied']
            if (len(new)==1 and obs.prices.get('summon') is not None
                    and obs.prices['summon']>pending['price']
                    and pending['occupied']<=obs.occupied):
                pos=next(iter(new))
                hero=identify(pos)
                if hero:
                    units[pos]={'hero':hero,'tier':1}
                    obs.summon_count=pending['count']+1
        elif pending and pending['kind']=='merge':
            a,b=pending['a'],pending['b']
            if a not in obs.occupied and b in obs.occupied:
                hero=identify(b)
                if hero:
                    units.pop(a,None)
                    units[b]={'hero':hero,'tier':pending['tier']+1}
        else:
            if set(units)!=obs.occupied:
                raise ValueError('Board changed without a recorded action')
        obs.units={p:u for p,u in units.items() if p in obs.occupied}
        if obs.summon_count is None:
            obs.summon_count=self.summons
        return obs

    def commit(self, obs):
        self.units=deepcopy(obs.units)
        self.summons=obs.summon_count
        self.cells=set(obs.cells)
        self.prices=dict(obs.prices)

    def state(self):
        return {'units':[dict(pos=list(p),**u) for p,u in sorted(self.units.items())],
                'summons':self.summons,'cells':sorted(self.cells),'prices':self.prices,'wave':self.wave}

    def restore(self, data, obs, identify):
        if not obs.board_verified or data['prices']!=obs.prices:
            raise ValueError('Checkpoint prices or board no longer match')
        cells={tuple(p) for p in data['cells']}
        units={tuple(u['pos']):{k:v for k,v in u.items() if k!='pos'} for u in data['units']}
        if cells!=obs.cells or set(units)!=obs.occupied:
            raise ValueError('Checkpoint wall/occupancy no longer matches')
        # Re-identify all heroes. Rank inheritance is disabled on reload:
        # identical heroes can have changed rank while the script was stopped.
        for pos,u in units.items():
            if identify(pos)!=u['hero']:
                raise ValueError('Checkpoint hero no longer matches')
            u['tier']=0
        self.units=units
        self.summons=data['summons']
        self.cells=cells
        self.prices=dict(data['prices'])
        self.wave=data.get('wave')
