"""Local catalog and editable player snapshots with optional game observations."""
from datetime import datetime, timezone
import json
from pathlib import Path
import math
from rules import evolution_gate, feed_candidates

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / 'runtime/tata/mainline'
DATA = ROOT / 'runtime/tata/research/data-bytecode-0.50.1'
DATASET = ROOT / 'runtime/tata/research/dataset-bytecode-0.50.1'
ELEMENTS = {1: '无', 2: '水', 3: '火', 4: '草', 5: '电', 6: '岩'}
QUALITIES = {1: '普通', 2: '稀有', 3: '史诗', 4: '传说', 5: '神话'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


class Catalog:
    def __init__(self, data=DATA, dataset=DATASET):
        if Path(data) == DATA and Path(dataset) == DATASET:
            from resources import ensure_default_resources
            ensure_default_resources()
        self.data, self.dataset = Path(data), Path(dataset)
        def table(name):
            return read_json(self.data/'Config'/f'{name}.json')[name+'Table']
        self.units = table('Unit')
        self.resources = table('UnitRes')
        self.evolutions = table('UnitEvolution')
        self.careers = table('UnitCareer')
        self.elements = table('UnitElement')
        self.qualities = table('UnitQuality')
        self.battle_resources = table('StageBattleRes')
        self.battle_mode = table('BattleMode')['1']
        self.evolution_trials = table('UnitEvolutionTrial')
        self.feed_levels = table('UnitFeedLevel')
        self.feed_limits = table('PetFeedLevel')
        self.feed_ranks = table('PetFeedAttrRank')
        self.star_resources = table('UnitStarRes')
        self.max_star = max(map(int,table('UnitStar')))
        self.star_grade = table('Config')['StarGrade']['NumberValue']
        self.pets = {k: u for k, u in self.units.items() if u.get('UnitType') == 1 and u.get('Enable')}
        self.stages = read_json(self.dataset/'stages.json')
        self.stage_index = {str(s['id']): s for s in self.stages}

    def resource(self, unit_id, evolution=1):
        options = self.resources.get(str(unit_id), {})
        return options.get(str(evolution), options.get('1', {}))

    def name(self, unit_id, evolution=1):
        return self.resource(unit_id, evolution).get('ShowName', self.units.get(str(unit_id), {}).get('Name', str(unit_id)))

    def quality(self, pet):
        return self.evolutions[str(pet['unit_id'])][str(pet['evolution'])].get(
            'UnitQuality', self.units[str(pet['unit_id'])].get('UnitQuality', 1))

    def stage(self, stage_id):
        key = str(int(stage_id))
        if key not in self.stage_index:
            raise ValueError('关卡不存在')
        stage=read_json(self.dataset/f'stage-{key}.json')
        stage['battle_mode']=self.battle_mode
        return stage


def validate_pet(pet, catalog):
    if 'level' in pet:
        raise ValueError('等级为账号共享字段，请修改共享等级')
    if any(k in pet for k in ('atk','def','hp')):
        raise ValueError('请录入字母评级，不再接受面板数值')
    result = {}
    for key, low, high, default in [('unit_id', 1, 999999, None),
                                   ('evolution', 1, 100, 1), ('skill_level', 1, 100, 1)]:
        value = pet.get(key, default)
        try:
            integer = int(value)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f'{key} 必须是整数') from None
        if isinstance(value, bool) or str(value).strip() != str(integer):
            raise ValueError(f'{key} 必须是整数')
        result[key] = integer
        if not low <= result[key] <= high:
            raise ValueError(f'{key} 超出允许范围 {low}–{high}')
    key = str(result['unit_id'])
    if key not in catalog.pets:
        raise ValueError('不是当前数据中可用的宠物编号')
    if str(result['evolution']) not in catalog.evolutions.get(key, {}):
        raise ValueError('此宠物不存在该进化阶段，请查看可用阶段')
    star = pet.get('stars',0)
    if star in ('',None): star=None
    elif isinstance(star,bool) or str(star).strip()!=str(int(star)) or not 0<=int(star)<=catalog.max_star:
        raise ValueError(f'请选择有效星级图案（0–{catalog.max_star}）')
    else: star=int(star)
    gate=evolution_gate(catalog,result['unit_id'],result['evolution'])
    if star is not None and (star<gate['minimum'] or (not gate['can_wait_for_trial'] and star>gate['normal_max'])):
        raise ValueError(f'星级与形态不符：本形态最低 {gate["minimum"]}，下次进化门槛 {gate["next_threshold"]}')
    result['stars']=star
    ratings=pet.get('attribute_ranks',{})
    allowed={r['RankName'] for r in catalog.feed_ranks.values()}
    if not isinstance(ratings,dict) or any(k not in ('ATK','DEF','HP') for k in ratings):
        raise ValueError('属性评级字段无效')
    result['attribute_ranks']={k:ratings.get(k) or None for k in ('ATK','DEF','HP')}
    if any(v is not None and v not in allowed for v in result['attribute_ranks'].values()):
        raise ValueError('请选择游戏中的 E/D/C/B/A/S/SS/SSS 评级')
    if not feed_candidates(catalog,result['unit_id'],star,result['attribute_ranks']):
        raise ValueError('评级组合不符合这只塔塔在当前星级下的养成配置；未知评级可留空')
    # Preserve legacy numeric inputs as unverified notes, never convert them to ranks.
    for legacy in ('legacy_stats','migration_notes'):
        if legacy in pet: result[legacy]=pet[legacy]
    if 'game_observed' in pet:
        # A timestamped source observation, independent of subsequent manual edits.
        observed=pet['game_observed']
        integer_keys={'tid','evoTID','starLv','level','gs','extraAmount','showEvoTID',
                      'styleID','accessoryID','backgroundID','showAuroraID','progress'}
        bool_keys={'isGet','isShinyUnlocked','showShiny','isHotSpringOwner'}
        feed_keys={'petTid','feedLevel','feedGrowth','feedCount','shinyFoodCnt'}
        if not isinstance(observed,dict) or set(observed)-integer_keys-bool_keys-{'captured_at','feed','badgeProps','hotSpringAttrIDs'}:
            raise ValueError('游戏观测字段无效')
        try:
            stamp=datetime.fromisoformat(observed['captured_at'])
            if stamp.tzinfo is None: raise ValueError()
        except (KeyError,ValueError,TypeError):
            raise ValueError('游戏观测缺少有效读取时间') from None
        if observed.get('tid')!=result['unit_id']:
            raise ValueError('游戏观测与塔塔编号不符')
        feed=observed.get('feed',{})
        if not isinstance(feed,dict) or set(feed)-feed_keys:
            raise ValueError('游戏观测喂养字段无效')
        if any(type(v) is not int or not 0<=v<2**63 for k,v in observed.items() if k in integer_keys) or any(
                type(v) is not int or not 0<=v<2**63 for v in feed.values()):
            raise ValueError('游戏观测数值无效')
        if any(type(v) is not bool for k,v in observed.items() if k in bool_keys):
            raise ValueError('游戏观测标记无效')
        badges=observed.get('badgeProps',[])
        if not isinstance(badges,list) or len(badges)>20 or any(not isinstance(b,dict) or
                set(b)-{'element','atkPct','defPct','hpPct'} or any(type(v) not in (int,float) or
                not math.isfinite(v) for v in b.values()) for b in badges):
            raise ValueError('游戏观测徽章加成无效')
        springs=observed.get('hotSpringAttrIDs',[])
        if not isinstance(springs,list) or len(springs)>100 or any(type(v) is not int or v<0 for v in springs):
            raise ValueError('游戏观测温泉加成无效')
        result['game_observed']={**observed,'feed':dict(feed)}
    result['notes'] = str(pet.get('notes', ''))[:4000]
    return result


def shared_level_value(value):
    try:
        level = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('共享等级必须是正整数') from None
    if isinstance(value, bool) or str(value).strip() != str(level) or not 1 <= level <= 100000:
        raise ValueError('共享等级必须为 1–100000 的整数')
    return level


def snapshot(pets, catalog, notes='', shared_level=1):
    validated = [validate_pet(p, catalog) for p in pets]
    if len({p['unit_id'] for p in validated}) != len(validated):
        raise ValueError('角色池不能重复录入同一宠物')
    return dict(schema_version=3, source='manual', updated_at=datetime.now(timezone.utc).isoformat(),
                data_version='apk-0.50.1', shared_level=shared_level_value(shared_level),
                notes=str(notes), pets=validated)


class SharedLevelConflict(ValueError):
    def __init__(self, levels):
        self.levels = sorted(levels)
        super().__init__('旧角色池存在不同等级，请确认实际共享等级；原文件未改动')


def load_roster(path, catalog, shared_level_override=None):
    value = read_json(path)
    if value.get('schema_version') not in (1, 2, 3) or not isinstance(value.get('pets'), list):
        raise ValueError('不支持的角色池文件格式')
    if value.get('data_version') != 'apk-0.50.1':
        raise ValueError('角色池数据版本不匹配，请先核对宠物数据')
    pets = value['pets']
    if value['schema_version'] == 1:
        levels = {shared_level_value(p.get('level', 1)) for p in pets}
        if len(levels) > 1 and shared_level_override is None:
            raise SharedLevelConflict(levels)
        level = shared_level_value(shared_level_override) if shared_level_override is not None else next(iter(levels), 1)
        pets = [{k: v for k, v in p.items() if k != 'level'} for p in pets]
    else:
        level = value['shared_level']
    if value['schema_version']<3:
        migrated=[]
        for pet in pets:
            pet=dict(pet)
            stats={k:pet.pop(k) for k in ('atk','def','hp') if k in pet}
            if any(v is not None for v in stats.values()): pet['legacy_stats']=stats
            gate=evolution_gate(catalog,pet['unit_id'],pet.get('evolution',1))
            stars=pet.get('stars',0)
            if stars is not None and (stars<gate['minimum'] or (not gate['can_wait_for_trial'] and stars>gate['normal_max'])):
                pet['migration_notes']=f'旧版星级 {stars} 与形态不符，待按图案重新录入'
                pet['stars']=None
            migrated.append(pet)
        pets=migrated
    return snapshot(pets, catalog, value.get('notes', ''), shared_level=level)


def filtered_pets(catalog, pets, query='', element=None, career=None, owned_only=False):
    owned = {str(p['unit_id']): p for p in pets}
    query = query.strip().casefold()
    results = []
    for key, unit in catalog.pets.items():
        evolution = owned.get(key, {}).get('evolution', 1)
        names = ' '.join(catalog.name(key, int(e)) for e in catalog.resources.get(key, {'1': {}}))
        if query and query not in f'{key} {unit["Name"]} {names}'.casefold():
            continue
        if element is not None and unit.get('UnitElement') != element:
            continue
        if career is not None and unit.get('UnitCareer') != career:
            continue
        if owned_only and key not in owned:
            continue
        results.append(int(key))
    return sorted(results, key=lambda k: (str(k) not in owned, -catalog.quality(
        owned.get(str(k), {'unit_id': k, 'evolution': 1})), k))
