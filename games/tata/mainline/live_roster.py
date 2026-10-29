"""Read the logged-in Tata WebGL Lua model without modifying the game process."""
import argparse
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

from model import Catalog, DATA, DATASET, RUNTIME, snapshot, write_json
from rules import rank_for_growth


class LiveReadError(ValueError):
    pass


@dataclass(frozen=True)
class TableRef:
    address: int


class LuaHeap:
    """Validated Lua 5.4 wasm32 layout; pointers are offsets in WASM memory.

    Layout reference: https://www.lua.org/source/5.4/lobject.h.html
    This game's ABI has 16-byte TValue, 24-byte Node and 32-byte Table.
    Never execute closures, follow userdata or enumerate unrelated model values.
    """
    def __init__(self, read, size):
        self.read, self.size = read, size

    def block(self, offset, size):
        if not isinstance(offset, int) or offset < 0 or size < 0 or offset+size > self.size:
            raise LiveReadError('游戏内存地址越界，请重新读取')
        data = self.read(offset, size)
        if len(data) != size:
            raise LiveReadError('游戏内存读取不完整')
        return data

    def string(self, address):
        header = self.block(address, 16)
        if header[4] != 4 or header[7] > 40:
            raise LiveReadError('不支持的 Lua 字符串布局')
        text = self.block(address+16, header[7]+1)
        if text[-1] != 0:
            raise LiveReadError('Lua 字符串边界校验失败')
        return text[:-1].decode('utf-8', errors='strict')

    def value(self, data, offset=0, tag=None):
        tag = data[offset+8] if tag is None else tag
        if tag == 3:
            return struct.unpack_from('<q', data, offset)[0]
        if tag == 19:
            return struct.unpack_from('<d', data, offset)[0]
        if tag in (1, 17):
            return tag == 17
        if tag == 68:
            return self.string(struct.unpack_from('<I', data, offset)[0])
        if tag == 69:
            return TableRef(struct.unpack_from('<I', data, offset)[0])
        return None

    def table(self, ref):
        if not isinstance(ref, TableRef):
            raise LiveReadError('角色模型字段不是 Lua 表')
        header = self.block(ref.address, 32)
        if header[4] != 5 or header[7] > 14:
            raise LiveReadError('不支持的 Lua 表布局')
        limit, array, node = struct.unpack_from('<III', header, 8)
        if limit > 10000 or (limit and not array) or not node:
            raise LiveReadError('Lua 表大小或指针无效')
        nodes = self.block(node, 24*(1 << header[7]))
        result = {}
        for i in range(0, len(nodes), 24):
            # Empty/dead nodes may still contain an old key pointer.
            if nodes[i+8] & 15 == 0:
                continue
            key = self.value(nodes, i+16, nodes[i+9])
            if type(key) not in (str, int):
                continue
            value = self.value(nodes, i)
            if value is not None:
                if key in result:
                    raise LiveReadError('Lua 表键重复，可能正在更新')
                result[key] = value
        values = self.block(array, 16*limit) if limit else b''
        for i in range(limit):
            value = self.value(values, i*16)
            if value is not None:
                if i+1 in result:
                    raise LiveReadError('Lua 数组键重复')
                result[i+1] = value
        return result


def find_pet_models(data):
    """Use an interned key and structural owner checks, never fixed addresses."""
    heap = LuaHeap(lambda p, n: data[p:p+n], len(data))
    nodes, pos = [], 0
    while (pos := data.find(b'_level\0', pos)) >= 0:
        if pos >= 16 and data[pos-12] == 4 and data[pos-9] == 6:
            pointer, q = struct.pack('<I', pos-16), 0
            while (q := data.find(pointer, q)) >= 0:
                if q >= 16 and data[q-7] == 68:
                    nodes.append(q-16)
                q += 4
        pos += 7
    if not nodes:
        return []
    candidates, pos = [], 0
    while (pos := data.find(b'\x05', pos)) >= 0:
        p, pos = pos-4, pos+1
        if p < 0 or p % 8 or p+32 > len(data) or data[p+7] > 10:
            continue
        node = struct.unpack_from('<I', data, p+16)[0]
        if not any(node <= q < node+24*(1 << data[p+7]) and (q-node) % 24 == 0 for q in nodes):
            continue
        ref = TableRef(p)
        try:
            t = heap.table(ref)
            if t.get('hasInitPets') is not True or not isinstance(t.get('pets'), TableRef):
                continue
            if heap.table(t.get('class')).get('__cname') != 'ed.PetModel':
                continue
            candidates.append(ref)
        except (LiveReadError, UnicodeError, struct.error):
            continue
    return candidates


PET_FIELDS = ('tid', 'evoTID', 'starLv', 'level', 'gs', 'extraAmount', 'isGet',
              'isShinyUnlocked', 'showShiny', 'showEvoTID', 'styleID', 'accessoryID',
              'backgroundID', 'showAuroraID', 'progress', 'isHotSpringOwner')
FEED_FIELDS = ('petTid', 'feedLevel', 'feedGrowth', 'feedCount', 'shinyFoodCnt')


def extract_model(heap, ref):
    model = heap.table(ref)
    if model.get('hasInitPets') is not True or heap.table(model.get('class')).get('__cname') != 'ed.PetModel':
        raise LiveReadError('当前角色池尚未加载或模型不匹配')
    pets = heap.table(model.get('pets'))
    if not pets or model.get('petCount') != len(pets):
        raise LiveReadError('角色池数量不一致，可能正在更新，请重试')
    result = dict(shared_level=model.get('_level'), pets=[])
    for tid, ref in sorted(pets.items()):
        pet = heap.table(ref)
        if type(tid) is not int or pet.get('tid') != tid or pet.get('level') != result['shared_level']:
            raise LiveReadError('角色编号或共享等级校验失败')
        # PetModel.pets contains owned pets (InitData/AddPet/GetAllPets). isGet is
        # only attached when GetAllPetsAndUnGet builds the encyclopedia cache.
        # Fresh logins may therefore lack it; never infer ownership from star level.
        if 'isGet' in pet and type(pet['isGet']) is not bool:
            raise LiveReadError('无法确认角色是否已拥有')
        if pet.get('isGet') is False:
            continue
        row = {k: pet[k] for k in PET_FIELDS if k in pet}
        row['isGet']=True
        feed = heap.table(pet.get('feedData'))
        if feed.get('petTid') != tid:
            raise LiveReadError('角色喂养数据归属校验失败')
        row['feed'] = {k: feed[k] for k in FEED_FIELDS if k in feed}
        for field,allowed in [('badgeProps',{'element','atkPct','defPct','hpPct'})]:
            if isinstance(pet.get(field),TableRef):
                entries=heap.table(pet[field])
                if len(entries)>20:raise LiveReadError('角色加成表长度异常')
                row[field]=[{k:v for k,v in heap.table(item).items() if k in allowed}
                            for _,item in sorted(entries.items())]
        if isinstance(pet.get('hotSpringAttrIDs'),TableRef):
            row['hotSpringAttrIDs']=[v for _,v in sorted(heap.table(pet['hotSpringAttrIDs']).items())]
        result['pets'].append(row)
    if not result['pets']:
        raise LiveReadError('未读到已拥有角色，原角色池已保留')
    return result


def to_roster(capture, catalog):
    if not capture.get('pets'):
        raise LiveReadError('未读到已拥有角色，原角色池已保留')
    pets = []
    for row in capture['pets']:
        tid = row['tid']
        if row.get('isGet') is not True or row.get('level') != capture['shared_level'] or row['feed'].get('petTid') != tid:
            raise LiveReadError('角色观测的归属、拥有状态或共享等级不一致')
        level = row['feed']['feedLevel']
        if type(level) is not int or level < 0:
            raise LiveReadError('喂养等级无效')
        config = catalog.feed_levels.get(str(tid), {}).get(str(level))
        if config is None:
            raise LiveReadError(f'本机配置缺少塔塔 {tid} 的喂养等级 {level}，请先更新配置')
        ranks = {a: rank_for_growth(catalog.feed_ranks, a, config[a+'PR']) for a in ('ATK', 'DEF', 'HP')}
        pets.append(dict(unit_id=tid, evolution=row['evoTID'], stars=row['starLv'],
                         attribute_ranks=ranks, game_observed=dict(captured_at=capture['captured_at'], **row)))
    return snapshot(pets, catalog, shared_level=capture['shared_level'])


class WindowsReader:
    """Only QUERY_INFORMATION | VM_READ. No write, injection, suspend or debug."""
    def __init__(self, pid):
        from ctypes import wintypes as w
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        class MBI(ctypes.Structure):
            _fields_ = [('base', ctypes.c_void_p), ('allocation', ctypes.c_void_p),
                        ('allocation_protect', w.DWORD), ('partition', w.WORD),
                        ('size', ctypes.c_size_t), ('state', w.DWORD),
                        ('protect', w.DWORD), ('kind', w.DWORD)]
        self.MBI = MBI
        self.k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.k.OpenProcess.restype = w.HANDLE
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.k.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.k.ReadProcessMemory.restype = w.BOOL
        self.k.VirtualQueryEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
        self.k.VirtualQueryEx.restype = ctypes.c_size_t
        self.k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        self.k.QueryFullProcessImageNameW.restype = w.BOOL
        self.handle = self.k.OpenProcess(0x410, False, pid)
        if not self.handle:
            raise LiveReadError(f'无法只读打开游戏进程：Windows {ctypes.get_last_error()}')
        path, n = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
        if not self.k.QueryFullProcessImageNameW(self.handle, 0, path, ctypes.byref(n)) or Path(path.value).name.lower() != 'wechatappex.exe':
            self.close()
            raise LiveReadError('目标不是微信小游戏进程')

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None

    def read(self, address, size):
        if not size:
            return b''
        buffer, n = ctypes.create_string_buffer(size), ctypes.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(n)) or n.value != size:
            raise LiveReadError('游戏内存读取失败，窗口可能已关闭或内存已改变')
        return buffer.raw

    def heaps(self):
        address = 0
        while True:
            m = self.MBI()
            if not self.k.VirtualQueryEx(self.handle, ctypes.c_void_p(address), ctypes.byref(m), ctypes.sizeof(m)):
                return
            if m.state == 0x1000 and m.protect == 4 and m.kind == 0x20000 and 128*1024**2 <= m.size <= 2*1024**3:
                yield int(m.base), m.size
            address = int(m.base or 0)+m.size


def renderer_pids():
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise LiveReadError('自动读取需要 64 位 Windows Python 和电脑微信小游戏')
    # Metadata only; no command lines, user identifiers or session credentials.
    script = "Get-CimInstance Win32_Process -Filter \"Name='WeChatAppEx.exe'\" | Where-Object {$_.CommandLine -match '--type=renderer'} | Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress"
    run = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                         capture_output=True, text=True, timeout=20,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if run.returncode:
        raise LiveReadError('无法列出微信小游戏进程')
    value = json.loads(run.stdout.strip() or '[]')
    return ([value] if type(value) is int else value) or []


def read_live():
    matches, errors = [], []
    for pid in renderer_pids():
        reader = None
        try:
            reader = WindowsReader(pid)
            for base, size in reader.heaps():
                data = reader.read(base, size)
                # Require multiple Tata-specific model/protocol markers before parsing.
                if not all(marker in data for marker in (b'cs_common.Dn_Pet', b'PetModel', b'evoTID', b'starLv')):
                    del data
                    continue
                refs = find_pet_models(data)
                del data
                heap = LuaHeap(lambda p, n: reader.read(base+p, n), size)
                for ref in refs:
                    first = extract_model(heap, ref)
                    second = extract_model(heap, ref)
                    if first != second:
                        raise LiveReadError('角色池正在变化，请停止养成操作后重新读取')
                    matches.append(first)
        except (LiveReadError, UnicodeError, struct.error) as exc:
            errors.append(str(exc))
        finally:
            if reader:
                reader.close()
    if len(matches) > 1:
        raise LiveReadError('检测到多个塔塔角色池，请只保留一个已登录的塔塔游戏窗口')
    if not matches:
        raise LiveReadError('未找到已加载的塔塔角色池。请打开电脑微信塔塔小游戏并进入角色列表。'
                            + (' '+errors[0] if errors else ''))
    return dict(schema_version=1, source='wechat-webgl-memory',
                captured_at=datetime.now(timezone.utc).isoformat(), **matches[0])


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=DATA)
    parser.add_argument('--dataset', type=Path, default=DATASET)
    parser.add_argument('--out', type=Path, default=RUNTIME/'live-capture.json')
    args = parser.parse_args()
    try:
        capture = read_live()
        to_roster(capture, Catalog(args.data, args.dataset))  # Validate before any output.
        write_json(args.out, capture)
        print(f'已读取：共享 Lv.{capture["shared_level"]}，{len(capture["pets"])} 只塔塔', flush=True)
    except (LiveReadError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
