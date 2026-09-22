"""Player-facing tactics compiled to the existing battle policy."""
import hashlib
import json
from pathlib import Path

ROLE_DEFAULTS = {
    'damage': {'keep_if_space': True, 'reserve': 0},
    'control': {'keep_if_space': False, 'reserve': 2},
    'support': {'keep_if_space': False, 'reserve': 2},
}

def compile_tactics(profile, catalog):
    slots = profile.get('slots', [])
    if len(slots) != 4:
        raise ValueError('Exactly four ordered hero slots are required')
    heroes = {}
    for slot in slots:
        key, role = slot['hero'], slot['role']
        if key in heroes or key not in catalog or role not in ROLE_DEFAULTS:
            raise ValueError(f'Invalid or duplicate slot: {slot}')
        hero = dict(catalog[key], **ROLE_DEFAULTS[role], role=role)
        for option in ('reserve', 'min_remaining'):
            value = slot.get(option, hero.get(option, 0))
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f'{option} must be a nonnegative integer')
            hero[option] = value
        hero['buff_order'] = slot.get('buff_order', [])
        if not isinstance(hero['buff_order'], list) or any(not isinstance(v,str) or not v for v in hero['buff_order']):
            raise ValueError('buff_order must be a list of nonempty names')
        heroes[key] = hero
    ratio = profile.get('price_ratio', {'upgrade': 2, 'summon': 1})
    if any(not isinstance(ratio.get(k), (int,float)) or ratio[k] <= 0 for k in ('upgrade','summon')):
        raise ValueError('Price ratios must be positive')
    priority = profile.get('buff_priority', list(heroes))
    if len(priority)!=4 or set(priority)!=set(heroes):
        raise ValueError('buff_priority must contain each selected hero once')
    return {'stage': profile.get('stage'), 'heroes':heroes, 'buff_priority':priority,
            'next_price_ratio':ratio, 'price_tie_action':'summon', 'max_tier':4,
            'same_role_buff_default_index':1}

def load_tactics(path):
    path=Path(path)
    profile=json.loads(path.read_text(encoding='utf-8-sig'))
    catalog=json.loads((Path(__file__).parent/'heroes.json').read_text(encoding='utf-8-sig'))
    cfg=compile_tactics(profile,catalog)
    fingerprint=hashlib.sha256(json.dumps(cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return cfg,fingerprint

def choose_card(cards,cfg):
    def score(text):
        text=''.join(text.split())
        for rank,key in enumerate(cfg['buff_priority']):
            hero=cfg['heroes'][key]
            if hero['name'] in text or any(word in text for word in hero['buff_keywords']):
                preferences=hero.get('buff_order',[])
                preferred=next((len(preferences)-i for i,name in enumerate(preferences) if name in text),0)
                return (len(cfg['buff_priority'])-rank,preferred)
        return (0,0)
    scored=[score(text) for text in cards]
    if not any(s[0] for s in scored):return cfg['same_role_buff_default_index']
    return max(range(len(cards)),key=lambda i:(scored[i],-i))
