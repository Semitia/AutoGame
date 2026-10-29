"""Read game UID, roster and mainline progress together, without desktop input."""
import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import struct

from live_roster import (LiveReadError, LuaHeap, WindowsReader, renderer_pids,
                         find_pet_models, extract_model, to_roster)
from live_battle import find_instances
from model import Catalog, DATA, DATASET, RUNTIME, write_json


def account_key(uid):
    if type(uid) not in (int, str) or not str(uid).isdigit() or int(uid) <= 0:
        raise LiveReadError('游戏账号 UID 无效，未覆盖任何账号')
    return hashlib.sha256(('tata:' + str(int(uid))).encode()).hexdigest()[:24]


def session_fields(heap, refs):
    def unique(name):
        tables = []
        for ref in dict.fromkeys(refs.get(name, [])):
            value = heap.table(ref)
            if heap.table(value.get('class')).get('__cname') != name:
                raise LiveReadError('账号或关卡模型已改变，请重试')
            if value.get('_behavior_destructed') is not True:
                tables.append(value)
        if len(tables) != 1:
            raise LiveReadError('需要唯一的游戏账号和主线进度模型，请等待登录完成')
        return tables[0]
    # Verified by executing original PlayerModel.GetUID/GetName getters offline.
    player, stage = unique('ed.PlayerModel'), unique('ed.StageModel')
    uid = player.get('_uid')
    key = account_key(uid)
    stage_id = stage.get('_stageID')
    if type(stage_id) is not int or stage_id <= 0:
        raise LiveReadError('当前主线关卡尚未加载')
    name = player.get('_name')
    return dict(account=dict(key=key, uid=str(uid), name=name[:80] if type(name) is str else ''),
                current_stage_id=stage_id)


def read_sessions():
    matches, errors = [], []
    for pid in renderer_pids():
        reader = None
        try:
            reader = WindowsReader(pid)
            for base, size in reader.heaps():
                data = reader.read(base, size)
                if not all(marker in data for marker in (b'cs_common.Dn_Pet', b'PetModel', b'evoTID', b'starLv')):
                    continue
                pets = find_pet_models(data)
                if not pets:
                    continue
                refs = find_instances(data, {'ed.PlayerModel', 'ed.StageModel'}, (b'_uid', b'_stageID'))
                del data
                heap = LuaHeap(lambda p, n: reader.read(base+p, n), size)
                for ref in pets:
                    first = dict(**session_fields(heap, refs), **extract_model(heap, ref))
                    second = dict(**session_fields(heap, refs), **extract_model(heap, ref))
                    if first != second:
                        raise LiveReadError('账号、关卡或养成正在变化，稍后将自动重试')
                    matches.append(dict(schema_version=2, source='wechat-webgl-memory',
                                        captured_at=datetime.now(timezone.utc).isoformat(), **first))
        except (LiveReadError, UnicodeError, struct.error) as exc:
            errors.append(str(exc))
        finally:
            if reader:
                reader.close()
    keys = [c['account']['key'] for c in matches]
    if len(keys) != len(set(keys)):
        raise LiveReadError('同一账号有多个有效会话，请关闭重复的塔塔窗口后重试')
    if not matches:
        raise LiveReadError('未找到已登录塔塔；保留本地账号和上次关卡。' + (' ' + errors[0] if errors else ''))
    return matches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=DATA)
    parser.add_argument('--dataset', type=Path, default=DATASET)
    parser.add_argument('--out', type=Path, default=RUNTIME/'sessions.json')
    args = parser.parse_args()
    try:
        sessions = read_sessions()
        catalog = Catalog(args.data, args.dataset)
        for session in sessions:
            to_roster(session, catalog)
            catalog.stage(session['current_stage_id'])
        write_json(args.out, dict(sessions=sessions))
        print(f'已读取 {len(sessions)} 个账号的角色池与当前关卡', flush=True)
    except (LiveReadError, OSError, ValueError) as exc:
        print(str(exc), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
