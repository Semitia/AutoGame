"""Separate local workspaces by stable game UID, never by level or pet fingerprint."""
from pathlib import Path
import shutil

from model import RUNTIME, load_roster, read_json, write_json
from live_session import account_key


class Profiles:
    def __init__(self, root=RUNTIME/'accounts', legacy=RUNTIME/'roster.json'):
        self.root = Path(root)
        self.index_path = self.root/'index.json'
        self.index = read_json(self.index_path) if self.index_path.exists() else dict(schema_version=1, active=None, accounts={})
        if self.index.get('schema_version') != 1 or not isinstance(self.index.get('accounts'), dict):
            raise ValueError('本地账号目录无法读取，原文件已保留')
        if not self.index['accounts'] and legacy and Path(legacy).exists():
            key = 'unbound'
            path = self.folder(key)/'roster.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, path)
            self.index['accounts'][key] = dict(label='原本地角色池（未绑定账号）')
            self.activate(key)

    def folder(self, key):
        if key != 'unbound' and (len(key) != 24 or any(c not in '0123456789abcdef' for c in key)):
            raise ValueError('本地账号编号无效')
        return self.root/key

    def activate(self, key):
        if key not in self.index['accounts']:
            raise ValueError('本地账号不存在')
        self.index['active'] = key
        write_json(self.index_path, self.index)

    @property
    def active(self):
        return self.index.get('active')

    def workspace(self, key):
        path = self.folder(key)/'workspace.json'
        return read_json(path) if path.exists() else {}

    def save_workspace(self, key, value):
        write_json(self.folder(key)/'workspace.json', value)

    def label(self, key):
        account = self.index['accounts'][key]
        return account.get('label') or account.get('name') or ('账号 ' + account.get('uid', key)[-6:])

    def rename(self, key, label):
        label = str(label).strip()[:80]
        if not label:
            raise ValueError('账号名称不能为空')
        self.index['accounts'][key]['label'] = label
        write_json(self.index_path, self.index)

    def sync(self, capture, catalog):
        from live_roster import to_roster
        account = capture['account']
        key = account_key(account['uid'])
        if key != account.get('key'):
            raise ValueError('账号观测归属校验失败')
        value = to_roster(capture, catalog)
        stage = catalog.stage(capture['current_stage_id'])
        folder = self.folder(key)
        path, observed = folder/'roster.json', folder/'live-capture.json'
        before = read_json(observed) if observed.exists() else None
        def growth(c):
            return dict(shared_level=c['shared_level'], pets=sorted(c['pets'], key=lambda p: p['tid']))
        changed = not before or growth(before) != growth(capture) or not path.exists()
        if changed:
            if path.exists():
                previous = load_roster(path, catalog)
                notes = {p['unit_id']: p.get('notes', '') for p in previous['pets']}
                value['notes'] = previous.get('notes', '')
                for pet in value['pets']:
                    pet['notes'] = notes.get(pet['unit_id'], '')
                path.with_suffix('.previous.json').write_bytes(path.read_bytes())
            write_json(path, value)
        write_json(observed, capture)
        record = self.index['accounts'].setdefault(key, {})
        record.update(uid=account['uid'], name=account.get('name', ''),
                      level=capture['shared_level'], stage_id=capture['current_stage_id'],
                      stage_name=stage['stage']['DisplayName'], captured_at=capture['captured_at'])
        write_json(self.index_path, self.index)
        return key, changed
