"""Rules recovered from BattleModule, PetStarPanel and the growth configuration."""
import math


def grid_areas(stage):
    """GridY is used as X bounds by InitField/DeployGridsArea, despite its name."""
    mode=stage['battle_mode']
    grid=stage['waves']['GridY']
    xs=list(grid.values()) or [1,2,3,4,5]
    if any(isinstance(x,bool) or not isinstance(x,int) or x<1 or x>5 for x in xs):
        raise ValueError('Invalid GridY column bounds')
    result={}
    for key,source in [('field','FieldGrids'),('deploy','DeployGrids')]:
        values=mode[source]
        rect=dict(zip(('x','y','width','height'),[int(values[str(i)]) for i in range(1,5)]))
        rect.update(x=min(xs),width=max(xs)-min(xs)+1)
        if rect['width']<1 or not 1<=rect['height']<=30:
            raise ValueError('Invalid grid rectangle')
        result[key]=rect
    return result


def rectangle_slots(rect):
    return [(x,y) for y in range(rect['y'],rect['y']+rect['height'])
            for x in range(rect['x'],rect['x']+rect['width'])]


def star_icons(level, grade=6):
    """Resource IDs from PetStarPanel incl. special (73+) and special-plus (79+)."""
    if not isinstance(level,int) or not 0<=level<=84:
        raise ValueError('星级编号必须为 0–84')
    if level==0: return []
    if level>=13*grade+1: return [13+grade+level-(13*grade+1)]
    if level>=12*grade+1: return [13+level-(12*grade+1)]
    base=math.ceil(level/grade)-1
    count=level-base*grade
    if base<1: return [1]*count
    return [base+1 if i<count else base for i in range(grade)]


def rank_for_growth(ranks, attr, value):
    rows=sorted(ranks.values(),key=lambda r:r['RankID'])
    return next((row['RankName'] for row in reversed(rows) if value>=row[attr+'PRMax']),rows[0]['RankName'])


def feed_candidates(catalog, uid, stars=None, ranks=None):
    """Letter ranks identify a set of possible feed levels, never an invented exact stat."""
    rows=catalog.feed_levels.get(str(uid),{})
    results=[]
    for key,row in sorted(rows.items(),key=lambda kv:int(kv[0])):
        level=int(key)
        requirement=catalog.feed_limits.get(str(level),{}).get('Star',0)
        if stars is not None and stars<requirement: continue
        actual={attr:rank_for_growth(catalog.feed_ranks,attr,row.get(attr+'PR',0)) for attr in ('ATK','DEF','HP')}
        if ranks and any(v is not None and actual[k]!=v for k,v in ranks.items()): continue
        results.append(dict(feed_level=level,ranks=actual,growth={k:row.get(k+'PR',0) for k in ('ATK','DEF','HP')}))
    return results


def evolution_gate(catalog, uid, evolution):
    trials=catalog.evolution_trials.get(str(uid),{})
    # Current evolution's RequireStar is the trigger to advance, not its minimum.
    previous=trials.get(str(evolution-1),{})
    current=trials.get(str(evolution),{})
    minimum=previous.get('RequireStar',0)
    threshold=current.get('RequireStar')
    quest=bool(current.get('QuestList'))
    return dict(minimum=minimum,next_threshold=threshold,
                normal_max=threshold-1 if threshold is not None else catalog.max_star,
                trial_quests=current.get('QuestList',{}),can_wait_for_trial=quest)
