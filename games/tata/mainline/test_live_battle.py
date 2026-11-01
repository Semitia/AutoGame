"""Synthetic Lua ABI fixtures, including early server stage advancement."""
import struct
import unittest
from unittest.mock import patch
from live_battle import LiveBattle,find_instances,lua_pairs,current_prepare
from live_roster import LiveReadError
from test_live_roster import Fixture


class LiveBattleTests(unittest.TestCase):
    def roster_fixture(self):
        from live_roster import find_pet_models
        from live_session import account_key
        live,f=self.fixture();f.model()
        f.table(dict(_uid=123,_name='测试',token='DO NOT EXPORT',**{'class':f.table({'__cname':'ed.PlayerModel'})}))
        live.refs=find_instances(bytes(f.data),{'ed.PlayerModel','ed.StageModel'},(b'_uid',b'_stageID'))
        live.pet_refs=find_pet_models(bytes(f.data));live.account_key=account_key(123)
        return live,f

    def test_cached_session_roster_is_fresh_and_needs_no_heap_scan_or_process_query(self):
        live,_=self.roster_fixture()
        with patch('live_battle.renderer_pids',side_effect=AssertionError('process query')),\
             patch('live_battle.find_instances',side_effect=AssertionError('heap scan')),\
             patch('live_battle.find_pet_models',side_effect=AssertionError('roster scan')):
            value=live.capture_roster()
        self.assertEqual(value['account']['uid'],'123')
        self.assertEqual(value['shared_level'],234)
        self.assertNotIn('DO NOT EXPORT',str(value))

    def test_roster_fast_path_still_rejects_mutation_wrong_uid_and_duplicate_models(self):
        from live_roster import extract_model
        from live_session import account_key
        live,_=self.roster_fixture();observed=extract_model(live.heap,live.pet_refs[0])
        with patch('live_battle.extract_model',side_effect=[observed,dict(observed,shared_level=235)]):
            with self.assertRaisesRegex(LiveReadError,'正在变化'):live.capture_roster()
        live.account_key=account_key(456)
        with self.assertRaisesRegex(LiveReadError,'账号已切换'):live.capture_roster()
        live,_=self.roster_fixture();live.pet_refs.append(live.pet_refs[0])
        self.assertEqual(live.capture_roster()['shared_level'],234)
        live.pet_refs.append(live.heap.table(live.pet_refs[0])['class'])
        with self.assertRaisesRegex(LiveReadError,'唯一有效角色池'):live.capture_roster()

    def test_refresh_keeps_the_verified_reader_instead_of_enumerating_renderers(self):
        from types import SimpleNamespace
        live,f=self.roster_fixture();reads=[]
        live.base=100;live.size=len(f.data)
        def read(address,size):reads.append((address,size));return bytes(f.data)
        reader=SimpleNamespace(read=read);live.reader=reader
        with patch('live_battle.renderer_pids',side_effect=AssertionError('process query')):live.refresh()
        self.assertIs(live.reader,reader)
        self.assertEqual(reads,[(100,len(f.data))])
        self.assertEqual(len(live.pet_refs),1)

    def test_lua_pairs_visits_array_before_hash_storage(self):
        f=Fixture();ref=f.table({5:'five',3:'three'})
        array=f.alloc(32);f.data[array:array+16]=f.value('one');f.data[array+16:array+32]=f.value('two')
        struct.pack_into('<II',f.data,ref.address+8,2,array)
        self.assertEqual([key for key,_ in lua_pairs(f.heap(),ref)],[1,2,5,3])

    def fixture(self):
        f=Fixture()
        def instance(name,**values):return f.table(dict(values,**{'class':f.table({'__cname':name})}))
        model=instance('ed.StageModel',_stageID=829)
        module=f.table(dict(state=4,battleID=828,result=1))
        controller=instance('ed.StageBattleController',stageID=829,battleID=829,battleMode=1,
            inBattle=True,battleEngine=f.table(dict(battleModule=module)))
        instance('ed.StageBattlePrepareView',stageID=828,isShow=False)
        instance('ed.StageBattleVictoryView',battleController=controller,isShow=True,animFinished=True)
        # A similarly shaped unrelated table must not become a stage controller.
        instance('ed.Unrelated',stageID=829,inBattle=True)
        live=LiveBattle.__new__(LiveBattle);live.reader=None;live.heap=f.heap();live.refs=find_instances(bytes(f.data))
        return live,f

    def test_finds_classes_and_retains_actual_battle_identity(self):
        live,_=self.fixture();state=live.snapshot()
        self.assertEqual(state['current_stage_id'],829)
        self.assertEqual(state['battle']['battleID'],828)
        self.assertTrue(state['victory']['isShow'])
        self.assertNotIn('prepare',state)
        self.assertNotIn('ed.Unrelated',live.refs)

    def test_multiple_active_controllers_fail_closed(self):
        live,f=self.fixture();cls=f.table({'__cname':'ed.StageBattleController'})
        live.refs['ed.StageBattleController'].append(f.table(dict(stageID=829,inBattle=True,**{'class':cls})))
        with self.assertRaisesRegex(LiveReadError,'不唯一'):live.snapshot()

    def test_duplicate_references_are_not_duplicate_objects(self):
        live,_=self.fixture();live.refs['ed.StageBattleController']*=2
        self.assertEqual(live.snapshot()['controller']['stageID'],829)

    def test_old_prepare_views_are_excluded_by_lifecycle_and_identity(self):
        f=Fixture();controller=f.table({});other=f.table({});unit=f.table(dict(tid=11))
        selected=f.table({11:unit});current=dict(stageID=829,battleController=controller,selectedUnitDict=selected,isShow=False)
        variants=[dict(current,isBaseViewClose=True),dict(current,_behavior_destructed=True),
            dict(current,_duringOut=True),dict(current,battleController=other),
            dict(current,selectedUnitDict=f.table({}))]
        self.assertIs(current_prepare(f.heap(),variants+[current],controller,{},829,{unit}),current)
        with self.assertRaisesRegex(LiveReadError,'2 个有效布阵'):
            current_prepare(f.heap(),[current,dict(current)],controller,{},829,{unit})

    def test_reused_class_reference_requires_relocation(self):
        live,_=self.fixture();live.refs['ed.StageModel']=live.refs['ed.StageBattleController']
        with self.assertRaisesRegex(LiveReadError,'失效'):live.snapshot()

    def chapter_fixture(self,active=False,closed=False,duplicate=False):
        f=Fixture()
        def instance(name,**values):return f.table(dict(values,**{'class':f.table({'__cname':name})}))
        model=instance('ed.StageModel',_stageID=579)
        instance('ed.StageBattleController',stageID=578,battleID=578,battleMode=1,inBattle=active)
        values=dict(stageModel=model,_lastPlayerStageID=579,_isStarted=True,isShow=False,
                    isBaseViewClose=closed,isExiting=False,isCarMoving=False,isStartingBattle=False)
        instance('ed.WorldMapView',**values)
        if duplicate:instance('ed.WorldMapView',**values)
        live=LiveBattle.__new__(LiveBattle);live.reader=None;live.heap=f.heap();live.refs=find_instances(bytes(f.data))
        return live

    def test_inactive_old_controller_does_not_hide_the_current_chapter_map(self):
        state=self.chapter_fixture().snapshot()
        self.assertEqual(state['screen'],'chapter')
        self.assertEqual(state['chapter']['stage_id'],579)
        self.assertNotIn('battle',state);self.assertNotIn('prepare',state)

    def test_cached_map_cannot_bypass_active_or_ambiguous_controller_checks(self):
        with self.assertRaisesRegex(LiveReadError,'控制器已切换'):self.chapter_fixture(active=True).snapshot()
        with self.assertRaisesRegex(LiveReadError,'章节地图不唯一'):self.chapter_fixture(duplicate=True).snapshot()
        self.assertEqual(self.chapter_fixture(closed=True).snapshot()['screen'],'inactive')


if __name__=='__main__':unittest.main()
