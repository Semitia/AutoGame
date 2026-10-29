"""Synthetic Lua ABI fixtures, including early server stage advancement."""
import struct
import unittest
from live_battle import LiveBattle,find_instances,lua_pairs,current_prepare
from live_roster import LiveReadError
from test_live_roster import Fixture


class LiveBattleTests(unittest.TestCase):
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


if __name__=='__main__':unittest.main()
