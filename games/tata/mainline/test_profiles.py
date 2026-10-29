import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from live_session import account_key, session_fields, read_sessions
from live_roster import LiveReadError
from model import load_roster, read_json, write_json
from profiles import Profiles
from test_live_roster import Fixture, capture
from test_workbench import catalog


def session(uid=123, stage=1):
    value=capture()
    value.update(account=dict(key=account_key(uid),uid=str(uid),name=f'玩家{uid}'),current_stage_id=stage)
    return value


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.catalog=catalog()
        self.catalog.stage=lambda i:dict(stage=dict(ID=int(i),DisplayName=f'关卡{i}'))

    def test_uid_separates_identical_growth_and_notes_survive_relogin(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Profiles(Path(directory)/'accounts',legacy=None)
            a,_=store.sync(session(123),self.catalog)
            path=store.folder(a)/'roster.json'
            roster=load_roster(path,self.catalog);roster['pets'][0]['notes']='账号 A 装备'
            write_json(path,roster);before=path.read_bytes()
            b,_=store.sync(session(456,2),self.catalog)
            self.assertNotEqual(a,b)
            self.assertEqual(load_roster(store.folder(b)/'roster.json',self.catalog)['pets'][0]['notes'],'')
            self.assertEqual(path.read_bytes(),before)
            capture=session(123);capture['captured_at']='2026-10-29T00:00:00+00:00'
            _,changed=store.sync(capture,self.catalog)
            self.assertFalse(changed);self.assertEqual(path.read_bytes(),before)
            capture['pets'][0]['gs']=200
            _,changed=store.sync(capture,self.catalog)
            self.assertTrue(changed)
            self.assertEqual(load_roster(path,self.catalog)['pets'][0]['notes'],'账号 A 装备')
            self.assertEqual(path.with_suffix('.previous.json').read_bytes(),before)
            store.rename(a,'主号');store.activate(a)
            store.save_workspace(a,dict(stage_id=8,placements=[dict(unit_id=1,x=1,y=1)]))
            store.save_workspace(b,dict(stage_id=2,placements=[]))
            reloaded=Profiles(store.root,legacy=None)
            self.assertEqual(reloaded.active,a);self.assertEqual(reloaded.label(a),'主号')
            self.assertEqual(reloaded.workspace(a)['stage_id'],8)
            self.assertEqual(reloaded.workspace(b)['stage_id'],2)

    def test_legacy_profile_is_retained_and_never_assigned_by_guessing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);legacy=root/'roster.json'
            write_json(legacy,dict(unknown='old local data'))
            before=legacy.read_bytes()
            store=Profiles(root/'accounts',legacy)
            self.assertEqual(store.active,'unbound')
            a,_=store.sync(session(),self.catalog)
            self.assertNotEqual(a,'unbound')
            self.assertEqual(legacy.read_bytes(),before)
            self.assertEqual((store.folder('unbound')/'roster.json').read_bytes(),before)

    def test_invalid_identity_does_not_overwrite_existing_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Profiles(Path(directory)/'accounts',legacy=None)
            a,_=store.sync(session(),self.catalog);path=store.folder(a)/'roster.json';before=path.read_bytes()
            forged=session(456);forged['account']['key']=a
            with self.assertRaisesRegex(ValueError,'归属'):store.sync(forged,self.catalog)
            self.assertEqual(path.read_bytes(),before)
            with self.assertRaises(ValueError):store.folder('../escape')

    def test_allowlisted_identity_and_stage_require_verified_model_classes(self):
        f=Fixture()
        player=f.table(dict(_uid=123,_name='测试号',token='NEVER OUTPUT',**{'class':f.table({'__cname':'ed.PlayerModel'})}))
        stage=f.table(dict(_stageID=566,**{'class':f.table({'__cname':'ed.StageModel'})}))
        refs={'ed.PlayerModel':[player],'ed.StageModel':[stage]}
        value=session_fields(f.heap(),refs)
        self.assertEqual(value['current_stage_id'],566)
        self.assertEqual(set(value['account']),{'uid','key','name'})
        self.assertNotIn('NEVER OUTPUT',str(value))
        refs['ed.PlayerModel']=[stage]
        with self.assertRaises(LiveReadError):session_fields(f.heap(),refs)

    def test_roster_and_identity_must_belong_to_one_stable_observation(self):
        f=Fixture();f.model();f.string('cs_common.Dn_Pet PetModel evoTID starLv')
        player=f.table(dict(_uid=123,_name='测试号',**{'class':f.table({'__cname':'ed.PlayerModel'})}))
        stage=f.table(dict(_stageID=566,**{'class':f.table({'__cname':'ed.StageModel'})}))
        class Reader:
            def __init__(self,pid):pass
            def heaps(self):return [(0,len(f.data))]
            def read(self,p,n):return bytes(f.data[p:p+n])
            def close(self):pass
        with patch('live_session.renderer_pids',return_value=[1]),patch('live_session.WindowsReader',Reader):
            values=read_sessions()
            self.assertEqual(len(values),1)
            self.assertEqual(values[0]['current_stage_id'],566)
            before=session_fields(f.heap(),{'ed.PlayerModel':[player],'ed.StageModel':[stage]})
            after=copy.deepcopy(before);after['account']['uid']='456'
            with patch('live_session.session_fields',side_effect=[before,after]):
                with self.assertRaisesRegex(LiveReadError,'正在变化'):read_sessions()

    def test_autoplay_rejects_another_account_with_identical_growth(self):
        from autoplay import Runner,RunStopped
        runner=Runner.__new__(Runner);runner.account_key=account_key(123)
        with patch('live_session.read_sessions',return_value=[session(456)]):
            with self.assertRaisesRegex(RunStopped,'账号不同'):runner.read_account_capture()
