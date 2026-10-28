"""Explainable, bounded roster selection baseline. No battle simulation or position score."""
from rules import grid_areas, rectangle_slots


def slots_for(stage):
    return rectangle_slots(grid_areas(stage)['deploy'])


def recommend(catalog, stage, pets, top_k=3, beam_width=64):
    if not pets:
        raise ValueError('请先录入角色池')
    slots = slots_for(stage)
    limit = min(int(stage['waves']['CanDeployNum']), len(slots))
    if limit < 1:
        raise ValueError('此关卡没有可部署位置')
    allowed = set(stage['waves'].get('CanUsePetIDs', {}).values())
    enemy_counts = {}
    for event in stage['waves'].get('Frame', {}).values():
        for wave in event.get('Waves', {}).values():
            key = str(wave['EnemyID'])
            enemy_counts[key] = enemy_counts.get(key, 0) + wave['Num']
    total = max(1, sum(enemy_counts.values()))
    options = []
    for pet in pets:
        key = str(pet['unit_id'])
        unit = catalog.pets[key]
        if allowed and pet['unit_id'] not in allowed:
            continue
        if unit.get('CanDeployNum', 0) < 1:
            continue
        counters = set(unit.get('CounterElement', {}).values())
        weak = set(unit.get('WeakElement', {}).values())
        coverage = sum(n for k, n in enemy_counts.items()
                       if stage['enemy_units'][k].get('UnitElement') in counters) / total
        weakness = sum(n for k, n in enemy_counts.items()
                       if stage['enemy_units'][k].get('UnitElement') in weak) / total
        quality = catalog.quality(pet)
        # Shared account level cannot distinguish individual pets.
        score = 2*quality + 3*coverage - 2*weakness
        options.append(dict(pet=pet, score=score, element=unit.get('UnitElement'),
                            reason=f'稀有度编号 {quality}；克制覆盖 {coverage:.0%}；弱势覆盖 {weakness:.0%}'))
    options.sort(key=lambda x: (-x['score'], x['pet']['unit_id']))
    if not options:
        raise ValueError('当前角色池没有符合关卡限制的宠物')
    count = min(limit, len(options))
    beam = [((), 0.0)]
    for _ in range(count):
        expanded = []
        for selected, _ in beam:
            for i in range(selected[-1]+1 if selected else 0, len(options)):
                choice = selected+(i,)
                if len(options)-i-1 < count-len(choice):
                    continue
                # Diversity is a search preference, not a damage multiplier.
                score = sum(options[j]['score'] for j in choice) + 0.5*len({options[j]['element'] for j in choice})
                expanded.append((choice, score))
        beam = sorted(expanded, key=lambda x: (-x[1], x[0]))[:beam_width]
    results = []
    for selected, score in beam[:top_k]:
        chosen = [options[i] for i in selected]
        results.append(dict(score=round(score, 3), mode='heuristic-v1', simulated=False,
                            placements=[dict(unit_id=c['pet']['unit_id'], x=slots[i][0], y=slots[i][1])
                                        for i, c in enumerate(chosen)],
                            reasons={str(c['pet']['unit_id']): c['reason'] for c in chosen},
                            limitations=['共享等级仅记录；分数是稀有度和元素覆盖的偏好分，不是伤害或胜率',
                                         '格子按顺序放置，位置效果未优化',
                                         '进化用于稀有度；星级、属性评级、技能和装备尚未进入评分',
                                         '每种宠物最多选择一只；未模拟战斗']))
    return results
