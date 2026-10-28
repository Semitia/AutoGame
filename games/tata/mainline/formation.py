"""Atomic edits to a formation; UI drag/drop and tests share the same constraints."""
from policy import slots_for


def move_unit(stage, pets, placements, unit_id, target):
    owned = {p['unit_id'] for p in pets}
    if unit_id not in owned:
        raise ValueError('请先将这只塔塔收入角色池')
    result = dict(placements)
    source = next((k for k, v in result.items() if v == unit_id), None)
    if target is None:
        if source is not None:
            result.pop(source)
        return result
    if target not in slots_for(stage):
        raise ValueError('这里不是可上阵格子')
    allowed = set(stage['waves'].get('CanUsePetIDs', {}).values())
    if allowed and unit_id not in allowed:
        raise ValueError('本关不能使用这只塔塔')
    occupant = result.get(target)
    if occupant == unit_id:
        return result
    if source is not None:
        result.pop(source)
        if occupant is not None:
            result[source] = occupant
    result[target] = unit_id
    if len(result) > int(stage['waves']['CanDeployNum']):
        raise ValueError('已达到本关上阵数量上限')
    return result
