"""Synthetic Lua ABI fixtures, including early server stage advancement."""
import struct
import unittest
from live_battle import LiveBattle,find_instances,lua_pairs
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
        live,_=self.fixture();live.refs['ed.StageBattleController']*=2
        with self.assertRaisesRegex(LiveReadError,'不唯一'):live.snapshot()

    def test_reused_class_reference_requires_relocation(self):
        live,_=self.fixture();live.refs['ed.StageModel']=live.refs['ed.StageBattleController']
        with self.assertRaisesRegex(LiveReadError,'失效'):live.snapshot()


if __name__=='__main__':unittest.main()
