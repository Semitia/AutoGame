"""Read-only current UID, trap inventory, room, actors and instance IDs."""
from datetime import datetime,timezone
import struct
import hunt_paths
from hunt_config import rules,BULLET_ASSET
from live_roster import LuaHeap,TableRef,WindowsReader,renderer_pids,LiveReadError
from live_battle import find_instances,open_view
from live_session import account_key

CLASSES={'ed.PlayerModel','ed.PlayerAssetModel','ed.TrapModel','ed.TrapBattleModel',
         'ed.TrapMainView','ed.TrapBattleView','ed.TrapBattleScene','ed.BaseRewardView'}
KEYS=tuple(x.encode() for x in ('_uid','backpackModel','_totalBulletGet','_roomID','_units',
    '_currentDungeonIndex','_holdShootAngle','_bossRewardOwners','_enemyActors','isShow'))


def present(heap,ref,key):
    """Test nil exactly like IsValid, without decoding or following Unity userdata."""
    header=heap.block(ref.address,32)
    if header[4]!=5 or header[7]>14:raise LiveReadError('无效Lua对象')
    node=struct.unpack_from('<I',header,16)[0];nodes=heap.block(node,24*(1<<header[7]))
    for i in range(0,len(nodes),24):
        if nodes[i+8]&15 and heap.value(nodes,i+16,nodes[i+9])==key:return True
    return False


class HuntLive:
    def __init__(self):
        found=[];self.reader=None;self.account=None
        for pid in renderer_pids():
            reader=WindowsReader(pid)
            try:
                for base,size in reader.heaps():
                    data=reader.read(base,size)
                    if b'ed.TrapModel' not in data or b'ed.PlayerAssetModel' not in data:continue
                    refs=find_instances(data,CLASSES,KEYS)
                    if refs.get('ed.TrapModel') and refs.get('ed.PlayerModel'):found.append((pid,base,size,refs))
            finally:reader.close()
        if len(found)!=1:raise LiveReadError(f'需要唯一已登录塔塔围猎会话，找到{len(found)}个；请先打开围猎')
        pid,self.base,self.size,self.refs=found[0];self.reader=WindowsReader(pid)
        self.heap=LuaHeap(lambda p,n:self.reader.read(self.base+p,n),self.size)
        self.scores={r['id']:r['score'] for r in rules()['enemies']}

    def close(self):
        if self.reader:self.reader.close();self.reader=None

    def refresh(self):
        data=self.reader.read(self.base,self.size)
        refs=find_instances(data,CLASSES,KEYS)
        if not refs.get('ed.PlayerModel') or not refs.get('ed.TrapModel'):raise LiveReadError('围猎模型已改变，请重新启动')
        self.refs=refs

    def objects(self,name,view=False):
        output=[]
        for ref in dict.fromkeys(self.refs.get(name,[])):
            t=self.heap.table(ref)
            if self.heap.table(t.get('class')).get('__cname')!=name:raise LiveReadError('围猎对象已回收，请重新定位')
            if t.get('_behavior_destructed') is True:continue
            if view and (not open_view(t) or t.get('_isStarted') is not True):continue
            output.append((ref,t))
        return output

    def one(self,name):
        found=self.objects(name)
        if len(found)!=1:raise LiveReadError('需要唯一模型：'+name)
        return found[0][1]

    def snapshot(self):
        with self.heap.cached():result=self._snapshot()
        # Fresh identity/room header; aliases cached above never confirm a later observation.
        player=self.one('ed.PlayerModel')
        if account_key(player.get('_uid'))!=result['account_key']:raise LiveReadError('读取中账号已切换')
        if result['screen']=='room':
            room=self.one('ed.TrapBattleModel')
            if (room.get('_roomID'),room.get('_roomCreateTs'),room.get('_dungeonID'))!=tuple(result['room_token']):
                raise LiveReadError('读取中围猎房间已切换')
        return result

    def _snapshot(self):
        h=self.heap;uid=self.one('ed.PlayerModel').get('_uid');key=account_key(uid)
        if self.account is not None and self.account!=key:raise LiveReadError('游戏账号已切换，已停止')
        self.account=key
        assets=self.one('ed.PlayerAssetModel')
        backpack=h.table(assets.get('backpackModel'));items=h.table(backpack.get('_itemMapRaw'))
        inside=h.table(assets.get('insideModel'));balances=h.table(inside.get('insideMap'))
        if h.table(backpack.get('class')).get('__cname')!='ed.BackpackModel' or h.table(inside.get('class')).get('__cname')!='ed.InsideModel':
            raise LiveReadError('围猎资产依赖的模型类型已改变')
        balance=balances.get(BULLET_ASSET)
        if not isinstance(balance,TableRef):raise LiveReadError('金猎币尚未加载；不猜余额')
        def integer(value,label):
            if type(value) is not int or value<0:raise LiveReadError('无效字段：'+label)
            return value
        trap=self.one('ed.TrapModel')
        s=dict(schema_version=1,captured_at=datetime.now(timezone.utc).isoformat(),account_key=key,
            locks=integer(items.get(30,0),'锁定数量'),rage=integer(items.get(31,0),'狂暴数量'),
            bullets=integer(h.table(balance).get('amount'),'金猎币'),
            total_bullets=integer(trap.get('_totalBulletGet'),'累计金猎币'),screen='transition')
        rewards=self.objects('ed.BaseRewardView',True)
        if len(rewards)>1:raise LiveReadError('多个有效奖励页，停止输入')
        battle_views=self.objects('ed.TrapBattleView',True)
        lobby=self.objects('ed.TrapMainView',True)
        if len(battle_views)>1 or len(lobby)>1:raise LiveReadError('围猎活动界面不唯一')
        if rewards:
            if not battle_views and not lobby:raise LiveReadError('存在其他玩法的奖励页，不执行围猎输入')
            s.update(screen='reward',reward_fly_started=rewards[0][1].get('flyAnimStarted') is True,
                reward_anim_finished=rewards[0][1].get('animFinished') is True)
            return s
        models=self.objects('ed.TrapBattleModel')
        if len(models)>1:raise LiveReadError('围猎房间模型不唯一')
        room=models[0][1] if models else {}
        if room.get('_roomState')==1 and battle_views:
            if room.get('_connState')!=1:raise LiveReadError('围猎连接已中断，停止输入')
            dungeon=next((r for r in rules()['rooms'] if r['id']==room.get('_dungeonID')),None)
            if dungeon is None:raise LiveReadError('未知围猎场地')
            players=h.table(room.get('_players'));own=h.table(players.get(uid))
            if h.table(own.get('class')).get('__cname')!='ed.TrapBattlePlayerData':raise LiveReadError('围猎玩家模型不匹配')
            if h.table(own.get('_player')).get('uid')!=uid:raise LiveReadError('围猎玩家身份不一致')
            effect=h.table(own.get('effectFlag'))
            scenes=[entry for entry in self.objects('ed.TrapBattleScene') if present(h,entry[0],'sceneRoot')]
            if len(scenes)!=1:raise LiveReadError('围猎场景不唯一或尚未加载')
            actors=h.table(scenes[0][1].get('_enemyActors'));units=h.table(room.get('_units'));enemies=[]
            for id,ref in units.items():
                data=h.table(ref)
                if (h.table(data.get('class')).get('__cname')!='ed.TrapBattleEnemyData'
                    or data.get('_unitID')!=id or data.get('_unitTid') not in self.scores):raise LiveReadError('围猎敌人身份校验失败')
                actor_ref=actors.get(id);active=False
                if isinstance(actor_ref,TableRef):
                    actor=h.table(actor_ref)
                    if (h.table(actor.get('class')).get('__cname')=='ed.TrapEnemyActor' and actor.get('enemyData')==ref
                        and actor.get('isActive') is True and present(h,actor_ref,'node')):active=True
                enemies.append(dict(id=id,tid=data['_unitTid'],spawn_time=data['_spawnTime'],
                    exit_time=data['_exitTime'],active=active,score=self.scores[data['_unitTid']]))
            s.update(screen='room',room_token=[room.get('_roomID'),room.get('_roomCreateTs'),dungeon['id']],
                multiplier=dungeon['multiplier'],lock_active=effect.get('lock') is True,
                rage_active=effect.get('angry') is True,lock_target=own.get('_lockTargetID',0),enemies=enemies)
        elif lobby and room.get('_roomState',0)==0:
            view=lobby[0][1];listing=h.table(view.get('_dungeonList'))
            ids=[h.table(v).get('ID') for _,v in sorted(listing.items())]
            index=view.get('_currentDungeonIndex')
            if type(index) is not int or not 1<=index<=len(ids):raise LiveReadError('场地选择尚未就绪')
            s.update(screen='lobby',selected_dungeon=ids[index-1],dungeons=ids,switching=view.get('_isSwitching') is True)
        return s
