"""Pure strategy: no pixels, coordinates, named line-up or accumulated spend."""
from collections import Counter

def price_action(upgrade_cost, summon_cost, config):
    r=config['next_price_ratio']
    left=upgrade_cost*r['summon']; right=summon_cost*r['upgrade']
    if left==right:return config['price_tie_action']
    return 'upgrade' if left<right else 'summon'

def merge_pair(units, config, must_free_slot=False, blocked_pairs=()):
    counts=Counter(u['hero'] for u in units.values())
    rank={h:i for i,h in enumerate(config['buff_priority'])}
    pairs=[]
    items=list(units.items())
    for i,(a,ua) in enumerate(items):
        if ua.get('hero') not in config['heroes'] or not 1<=ua.get('tier',0)<config['max_tier'] or ua.get('uncertain'):continue
        for b,ub in items[i+1:]:
            if (a,b) in blocked_pairs or (b,a) in blocked_pairs:continue
            if ua['hero']!=ub['hero'] or ua['tier']!=ub['tier'] or ub.get('uncertain'):continue
            h=config['heroes'][ua['hero']]
            if counts[ua['hero']]-2 < h.get('min_remaining',0):continue
            excess=not h['keep_if_space'] and counts[ua['hero']]>h['reserve']
            if not excess and not (must_free_slot and h['keep_if_space']):continue
            pairs.append(((0 if excess else 1,ua['tier'],-rank.get(ua['hero'],99)),a,b))
    if not pairs:return None
    _,a,b=min(pairs,key=lambda p:p[0]);return a,b
