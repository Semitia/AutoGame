"""Local catalog and versioned, manually entered player snapshots."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path

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
        self.data, self.dataset = Path(data), Path(dataset)
        def table(name):
            return read_json(self.data/'Config'/f'{name}.json')[name+'Table']
        self.units = table('Unit')
        self.resources = table('UnitRes')
        self.evolutions = table('UnitEvolution')
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
        return read_json(self.dataset/f'stage-{key}.json')


def validate_pet(pet, catalog):
    result = {}
    for key, low, high, default in [('unit_id', 1, 999999, None), ('level', 1, 100000, 1),
                                   ('evolution', 1, 100, 1), ('stars', 0, 100, 0), ('skill_level', 1, 100, 1)]:
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
    for key in ('atk', 'def', 'hp'):
        value = pet.get(key)
        if value in ('', None):
            result[key] = None
        else:
            value = float(value)
            if not math.isfinite(value) or value < 0:
                raise ValueError('面板属性必须为非负有限数值')
            result[key] = value
    result['notes'] = str(pet.get('notes', ''))[:4000]
    return result


def snapshot(pets, catalog, notes=''):
    validated = [validate_pet(p, catalog) for p in pets]
    if len({p['unit_id'] for p in validated}) != len(validated):
        raise ValueError('角色池不能重复录入同一宠物')
    return dict(schema_version=1, source='manual', updated_at=datetime.now(timezone.utc).isoformat(),
                data_version='apk-0.50.1', notes=str(notes), pets=validated)


def load_roster(path, catalog):
    value = read_json(path)
    if value.get('schema_version') != 1 or not isinstance(value.get('pets'), list):
        raise ValueError('不支持的角色池文件格式')
    if value.get('data_version') != 'apk-0.50.1':
        raise ValueError('角色池数据版本不匹配，请先核对宠物数据')
    return snapshot(value['pets'], catalog, value.get('notes', ''))
