"""Public rules exported from 0.50.1 original bytecode, never player state."""
import json
from hunt_paths import ASSETS

TARGET_TID=2008
LOCK_ITEM=30
RAGE_ITEM=31
BULLET_ASSET=110008001


def rules():
    return json.loads((ASSETS/'rules.json').read_text(encoding='utf-8'))


def room_for(multiplier):
    matches=[r for r in rules()['rooms'] if r['multiplier']==multiplier]
    if len(matches)!=1:raise ValueError('原配置没有唯一的目标倍率场地')
    return matches[0]
