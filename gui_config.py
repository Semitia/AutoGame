"""GUI persistence and runner command construction (no desktop/device side effects)."""
import copy
import json
import math
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent
GAME = ROOT / 'games/bilibili_hero_merge'
CACHE = ROOT / 'config/gui.json'
sys.path.insert(0, str(GAME))
from tactics import compile_tactics, load_tactics


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def defaults():
    local = read_json(ROOT / 'config/local.json') if (ROOT / 'config/local.json').exists() else {}
    mumu = local.get('mumu', {})
    install = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'NetEase/MuMu/nx_main'
    profile = dict(mode='单人战术', device='', index=str(mumu.get('index', 0)), stage='1',
                   minutes='20', runs='1', until_stamina=False, stop_on_loss=False,
                   entry='从首页开始', state='', hide=False, resume=False,
                   runtime=str(ROOT / 'runtime/gui/default'), host_device='', guest_device='',
                   host_name='', guest_name='', host_state='', guest_state='',
                   battle_only=False, only_side='双方',
                   tactics=str(GAME / 'tactics/beginner.json'),
                   host_tactics='', guest_tactics='')
    return dict(version=1, selected='默认方案', profiles={'默认方案': profile},
                python=local.get('python', sys.executable),
                adb=os.environ.get('AUTOGAME_ADB', mumu.get('adb', str(install / 'adb.exe'))),
                manager=os.environ.get('AUTOGAME_MUMU_MANAGER', mumu.get('manager', str(install / 'MuMuManager.exe'))))


def load_cache(path=CACHE):
    data = defaults()
    if Path(path).exists():
        saved = read_json(path)
        if saved.get('version') != 1 or not isinstance(saved.get('profiles'), dict) or not saved['profiles']:
            raise ValueError('无法读取配置版本或方案列表')
        base = next(iter(data['profiles'].values()))
        saved['profiles'] = {name: dict(copy.deepcopy(base), **value) for name, value in saved['profiles'].items()}
        data.update(saved)
        if data['selected'] not in data['profiles']:
            data['selected'] = next(iter(data['profiles']))
    for profile in data['profiles'].values():
        migrate_mainline(profile)
    return data


def migrate_mainline(profile):
    """The former fixed stage-34 GUI mode is now an ordinary mainline profile."""
    if profile.get('mode') != '旧版34关':
        return profile
    strategy = read_json(GAME / 'strategy.json')
    profile.update(mode='单人战术', stage='34', lineup={
        'slots': [dict(value, hero=key) for key, value in strategy['heroes'].items()],
        'buff_priority': strategy['buff_priority'],
        'price_ratio': strategy['next_price_ratio'],
        'hero_definitions': strategy['heroes']})
    profile['entry'] = '恢复状态文件' if profile.get('resume') else '从首页开始'
    profile.pop('_legacy_lineup', None)
    return profile


def resolved(value):
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def number(value, label, integer=False, zero=False):
    try:
        n = int(value) if integer else float(value)
        if not math.isfinite(n) or n < 0 or (n == 0 and not zero):
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        raise ValueError(label + ('必须是非负整数' if zero else '必须是正整数' if integer else '必须是正数')) from None
    return str(n)


def validate_tactics(profile):
    catalog = read_json(GAME / 'heroes.json')
    for key, hero in profile.get('hero_definitions', {}).items():
        if not isinstance(hero, dict) or not isinstance(hero.get('name'), str) or not hero['name'].strip():
            raise ValueError('自定义英雄需要准确名称')
        if not isinstance(hero.get('buff_keywords'), list) or any(not isinstance(v, str) or not v for v in hero['buff_keywords']):
            raise ValueError('英雄关键词必须是非空字符串列表')
        catalog[key] = hero
    for key in ('upgrade', 'summon'):
        number(profile.get('price_ratio', {}).get(key, 2 if key == 'upgrade' else 1), '费用比例')
    return compile_tactics(profile, catalog)


LINEUPS = {'lineup': 'tactics', 'host_lineup': 'host_tactics', 'guest_lineup': 'guest_tactics'}


def hydrate_lineups(profile):
    """Migrate path-based GUI configurations without overwriting their source files."""
    for key, old_key in LINEUPS.items():
        if key not in profile:
            source = profile.get(old_key, '')
            profile[key] = read_json(resolved(source)) if source else {
                'slots': [dict(hero='', role=role, reserve=0 if role == 'damage' else 2,
                               min_remaining=0, buff_order=[]) for role in ('damage', 'damage', 'control', 'support')],
                'price_ratio': {'upgrade': 2, 'summon': 1}}
    return profile


def prepare_launch(settings, profile):
    """Freeze inline tactics per launch so later GUI edits cannot change a running job."""
    p = copy.deepcopy(profile)
    hydrate_lineups(p)
    selected = ['lineup']
    if p['mode'] == '双人合作':
        selected = [side + '_lineup' for side in ('host', 'guest') if p['only_side'] in ('双方', side)]
    for key in selected:
        validate_tactics(p[key])
    snapshot = resolved(p['runtime']) / 'launch-configs' / uuid.uuid4().hex
    for key in selected:
        path = snapshot / (key + '.json')
        atomic_json(path, p[key])
        p[LINEUPS[key]] = str(path)
    return build_launch(settings, p)


def build_launch(settings, profile):
    p = profile
    python = resolved(settings['python'])
    if not python.is_file():
        raise ValueError('请选择有效的 Python 可执行文件')
    if not p['runtime'].strip():
        raise ValueError('请指定独立运行目录')
    runtime = resolved(p['runtime'])
    modes = {'单人战术': 'blue_planet', '双人合作': 'bilibili_hero_merge_coop'}
    if p['mode'] not in modes:
        raise ValueError('未知运行模式')
    args = [str(python), '-X', 'utf8', '-u', str(ROOT / 'run.py'), modes[p['mode']]]
    args += ['--minutes', number(p['minutes'], '总时限')]
    env = os.environ.copy()
    env.update(AUTOGAME_RUNTIME=str(runtime), AUTOGAME_MUMU_INDEX=number(p['index'], 'MuMu索引', True, True),
               AUTOGAME_ADB=settings['adb'], AUTOGAME_MUMU_MANAGER=settings['manager'], PYTHONIOENCODING='utf-8')
    deps = ROOT / '.local/python-deps'
    if deps.is_dir():
        env['PYTHONPATH'] = str(deps) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    devices = []

    def device(key, flag):
        value = p[key].strip()
        if not value or any(c.isspace() for c in value) or value.startswith('-'):
            raise ValueError('请填写明确的 ADB 设备序列号')
        devices.append(value)
        args.extend([flag, value])

    def file_arg(key, flag, tactics=False):
        if not p[key].strip():
            raise ValueError('请填写 ' + flag + ' 文件')
        path = resolved(p[key])
        if not path.is_file():
            raise ValueError('文件不存在：' + str(path))
        if tactics:
            validate_tactics(read_json(path))
            load_tactics(path)
        args.extend([flag, str(path)])

    if p['mode'] == '双人合作':
        args += ['--stage', number(p['stage'], '层数', True), '--runtime', str(runtime)]
        if p['only_side'] not in ('双方', 'host', 'guest'):
            raise ValueError('未知合作控制侧')
        if p['only_side'] != '双方':
            if not p['battle_only']:
                raise ValueError('单侧控制必须勾选「仅接管战斗」')
            args += ['--only-side', p['only_side']]
        if p['battle_only']:
            args.append('--battle-only')
        # Both names are used to verify room identity, including single-side runs.
        for side in ('host', 'guest'):
            if not p[side + '_name'].strip():
                raise ValueError('合作需要填写双方游戏内准确昵称')
            args += ['--' + side + '-name', p[side + '_name'].strip()]
            if p['only_side'] not in ('双方', side):
                continue
            device(side + '_device', '--' + side + '-device')
            file_arg(side + '_tactics', '--' + side + '-tactics', True)
            if p[side + '_state'].strip():
                if not p['battle_only']:
                    raise ValueError('恢复合作检查点需要「仅接管战斗」')
                file_arg(side + '_state', '--' + side + '-state')
        if len(devices) != len(set(devices)):
            raise ValueError('合作双方不能使用同一个设备序列号')
    else:
        device('device', '--device')
        if p['until_stamina']:
            args.append('--until-stamina')
        else:
            args += ['--runs', number(p['runs'], '局数', True)]
        args += ['--stage', number(p['stage'], '关卡', True)]
        file_arg('tactics', '--tactics', True)
        entries = {'从首页开始': '--start-home', '空棋盘接管': '--empty-board', '暂停局接管': '--adopt-paused', '恢复状态文件': '--resume-state'}
        if p['entry'] not in entries:
            raise ValueError('未知战斗入口')
        if p['entry'] == '恢复状态文件': file_arg('state', '--resume-state')
        else: args.append(entries[p['entry']])
        if p['stop_on_loss']: args.append('--stop-on-loss')
    return args, env, runtime, devices
