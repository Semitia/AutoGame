"""Read allowlists against a synthetic Lua ABI, including opaque native values."""
import struct
import unittest
import hunt_paths
from hunt_live import HuntLive,present,CLASSES,KEYS
from live_battle import find_instances
from live_roster import LiveReadError
from test_live_roster import Fixture


def fixture(in_room=True):
    f=Fixture();f.data=bytearray(131072)
    def obj(name,**values):return f.table(dict(values,**{'class':f.table({'__cname':name})}))
    player=obj('ed.PlayerModel',_uid=123,_name='not exported',token='NEVER EXPORT')
    backpack=obj('ed.BackpackModel',_itemMapRaw=f.table({30:10,31:3}))
    inside=obj('ed.InsideModel',insideMap=f.table({110008001:f.table(dict(amount=99000))}))
    obj('ed.PlayerAssetModel',backpackModel=backpack,insideModel=inside)
    obj('ed.TrapModel',_totalBulletGet=999999)
    unit=obj('ed.TrapBattleEnemyData',_unitID=77,_unitTid=2008,_spawnTime=10,_exitTime=100)
    actor=obj('ed.TrapEnemyActor',enemyData=unit,isActive=True,node=f.table({}))
    obj('ed.TrapBattleScene',_enemyActors=f.table({77:actor}),sceneRoot=f.table({}))
    own=obj('ed.TrapBattlePlayerData',_player=f.table(dict(uid=123,seatIdx=1)),effectFlag=f.table(dict(lock=True)),_lockTargetID=77)
    battle=obj('ed.TrapBattleModel',_roomID=1,_roomCreateTs=100,_dungeonID=8,_roomState=1 if in_room else 0,
        _connState=1,_units=f.table({77:unit}),_players=f.table({123:own}))
    obj('ed.TrapBattleView',_bossRewardOwners=f.table({}),_isStarted=True,isBaseViewClose=not in_room)
    obj('ed.TrapMainView',_dungeonList=f.table({i:f.table(dict(ID=i)) for i in range(1,11)}),
        _currentDungeonIndex=1,_isStarted=True,isBaseViewClose=in_room)
    live=HuntLive.__new__(HuntLive);live.reader=None;live.account=None;live.heap=f.heap()
    live.refs=find_instances(bytes(f.data),CLASSES,KEYS);live.scores={2008:1500}
    return live,f,dict(player=player,battle=battle,actor=actor,unit=unit,obj=obj)


def set_field(f,ref,key,value):
    heap=f.heap();node=struct.unpack_from('<I',f.data,ref.address+16)[0]
    for i in range(1<<f.data[ref.address+7]):
        p=node+i*24
        if heap.value(f.data,p+16,f.data[p+9])==key:
            data=f.value(value);f.data[p:p+9]=data[:9];return
    raise AssertionError('missing key '+key)


class LiveTests(unittest.TestCase):
    def test_room_snapshot_uses_verified_model_fields_without_exporting_identity_secrets(self):
        live,_,_=fixture();s=live.snapshot()
        self.assertEqual((s['screen'],s['locks'],s['rage'],s['bullets']),('room',10,3,99000))
        self.assertEqual(s['enemies'][0]['tid'],2008);self.assertTrue(s['enemies'][0]['active'])
        self.assertTrue(s['lock_active']);self.assertEqual(s['lock_target'],77)
        self.assertNotIn('NEVER EXPORT',str(s));self.assertNotIn('_uid',s)

    def test_lobby_keeps_actual_sorted_dungeon_index_and_inventory(self):
        live,_,_=fixture(False);s=live.snapshot()
        self.assertEqual(s['screen'],'lobby');self.assertEqual(s['selected_dungeon'],1)
        self.assertEqual(s['dungeons'],list(range(1,11)))

    def test_native_node_presence_is_not_mistaken_for_nil_by_allowlist_decoder(self):
        live,f,refs=fixture();actor=refs['actor'];node=struct.unpack_from('<I',f.data,actor.address+16)[0]
        for i in range(1<<f.data[actor.address+7]):
            p=node+i*24
            if f.heap().value(f.data,p+16,f.data[p+9])=='node':f.data[p+8]=7
        self.assertNotIn('node',live.heap.table(actor))
        self.assertTrue(present(live.heap,actor,'node'));self.assertTrue(live.snapshot()['enemies'][0]['active'])

    def test_uid_change_duplicate_room_or_foreign_instance_never_gets_chosen(self):
        live,f,refs=fixture();live.snapshot();set_field(f,refs['player'],'_uid',456)
        with self.assertRaisesRegex(LiveReadError,'账号已切换'):live.snapshot()
        live,f,refs=fixture();duplicate=refs['obj']('ed.TrapBattleModel',_roomID=2)
        live.refs.setdefault('ed.TrapBattleModel',[]).append(duplicate)
        with self.assertRaisesRegex(LiveReadError,'房间模型不唯一'):live.snapshot()
        live,f,refs=fixture();set_field(f,refs['unit'],'_unitID',88)
        with self.assertRaisesRegex(LiveReadError,'身份校验'):live.snapshot()

    def test_removed_portrait_does_not_affect_enemy_presence_but_inactive_actor_does(self):
        live,f,refs=fixture();s=live.snapshot();self.assertTrue(s['enemies'][0]['active'])
        set_field(f,refs['actor'],'isActive',False)
        self.assertFalse(live.snapshot()['enemies'][0]['active'])

    def test_original_bytecode_functions_confirm_strategy_dependencies(self):
        from verify_logic import verify
        report=verify();self.assertEqual(report['passed'],16);self.assertFalse(report['game_input'])
