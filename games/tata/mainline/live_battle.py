"""Read-only, allowlisted mainline progress and deployment state from Tata's Lua heap."""
import argparse
from datetime import datetime,timezone
import struct
import sys

from live_roster import LuaHeap,TableRef,LiveReadError,WindowsReader,renderer_pids
from model import RUNTIME,write_json


CLASSES={'ed.StageModel','ed.StageBattleController','ed.StageBattlePrepareView','ed.StageBattleVictoryView'}


def find_instances(data):
    heap=LuaHeap(lambda p,n:data[p:p+n],len(data));nodes=[]
    for key in (b'_stageID',b'stageID',b'battleController'):
        pos=0
        while (pos:=data.find(key+b'\0',pos))>=0:
            if pos>=16 and data[pos-12]==4 and data[pos-9]==len(key):
                pointer=struct.pack('<I',pos-16);q=0
                while (q:=data.find(pointer,q))>=0:
                    if q>=16 and data[q-7]==68:nodes.append(q-16)
                    q+=4
            pos+=len(key)+1
    result={};pos=0
    while nodes and (pos:=data.find(b'\x05',pos))>=0:
        p=pos-4;pos+=1
        if p<0 or p%8 or p+32>len(data) or data[p+7]>11:continue
        base=struct.unpack_from('<I',data,p+16)[0]
        if not any(base<=q<base+24*(1<<data[p+7]) and (q-base)%24==0 for q in nodes):continue
        try:
            ref=TableRef(p);table=heap.table(ref)
            if not isinstance(table.get('class'),TableRef):continue
            name=heap.table(table['class']).get('__cname')
            if name in CLASSES:result.setdefault(name,[]).append(ref)
        except (LiveReadError,UnicodeError,struct.error):continue
    return result


def plain(heap,value,depth=3):
    if not isinstance(value,TableRef):return value
    if depth<1:return None
    return {k:plain(heap,v,depth-1) for k,v in heap.table(value).items() if k!='class' and type(v) in (bool,int,float,str,TableRef)}


def lua_pairs(heap,ref):
    """Lua next visits the array first, then occupied nodes in storage order."""
    table=heap.table(ref);limit=struct.unpack_from('<I',heap.block(ref.address,32),8)[0]
    array=lambda k:type(k) is int and 1<=k<=limit
    return sorted((k,v) for k,v in table.items() if array(k))+[(k,v) for k,v in table.items() if not array(k)]


class LiveBattle:
    def __init__(self):
        self.reader=None
        found=[]
        for pid in renderer_pids():
            reader=WindowsReader(pid)
            try:
                for base,size in reader.heaps():
                    data=reader.read(base,size)
                    if not all(marker in data for marker in (b'cs_common.Dn_Pet',b'PetModel',b'evoTID')):continue
                    refs=find_instances(data)
                    if refs.get('ed.StageModel'):found.append((pid,base,size,refs))
            finally:reader.close()
        if len(found)!=1:raise LiveReadError(f'需要唯一已登录塔塔主线模型，当前找到 {len(found)} 个')
        pid,base,size,self.refs=found[0];self.reader=WindowsReader(pid)
        self.heap=LuaHeap(lambda p,n:self.reader.read(base+p,n),size)

    def close(self):
        if self.reader:self.reader.close();self.reader=None

    def tables(self,name):
        results=[]
        for ref in self.refs.get(name,[]):
            table=self.heap.table(ref)
            if self.heap.table(table.get('class')).get('__cname')!=name:raise LiveReadError('主线对象已失效，请重新定位')
            results.append(table)
        return results

    def snapshot(self,debug=False):
        result=dict(captured_at=datetime.now(timezone.utc).isoformat())
        stages=self.tables('ed.StageModel')
        if len(stages)!=1:raise LiveReadError('主线进度模型不唯一')
        result['current_stage_id']=stages[0].get('_stageID')
        all_controllers=self.tables('ed.StageBattleController')
        controllers=[c for c in all_controllers if c.get('stageID')==result['current_stage_id'] and c.get('inBattle') is True]
        if all_controllers and not controllers:raise LiveReadError('关卡控制器已切换，需要重新定位')
        if len(controllers)>1:raise LiveReadError('当前关卡战斗控制器不唯一')
        if controllers:
            c=controllers[0]
            result['controller']={k:c[k] for k in ('stageID','battleID','battleMode','inBattle','inBattleScene','isAutoBattle','timeScale','defeatFlag') if type(c.get(k)) in (int,bool,float,str)}
            if debug:result['controller_keys']=list(c)
            if isinstance(c.get('params'),TableRef):
                params=self.heap.table(c['params']);result['params']={k:params[k] for k in ('stageID','battleID','battleMode') if k in params}
            for name in ('battleEngine','battleLineup','battleResultInfo'):
                if isinstance(c.get(name),TableRef):
                    table=self.heap.table(c[name])
                    if debug:result[name+'_keys']=list(table)
                    if name=='battleResultInfo':result[name]={k:table[k] for k in ('result','damage','killCount','time','stageID') if type(table.get(k)) in (int,float,bool)}
            if isinstance(c.get('battleUnitSystem'),TableRef):
                units=self.heap.table(c['battleUnitSystem'])
                if debug:result['unit_system_keys']=list(units)
                if isinstance(units.get('unitList'),TableRef):
                    entries=self.heap.table(units['unitList']);parsed=[]
                    for _,ref in entries.items():
                        if not isinstance(ref,TableRef):continue
                        u=self.heap.table(ref)
                        if u.get('camp')!=1 or not isinstance(u.get('petData'),TableRef):continue
                        pd=self.heap.table(u['petData']);uid=pd.get('tid')
                        if type(uid) is not int or not 1<=uid<100:continue
                        transform=self.heap.table(u['transformComponent'])
                        parsed.append(dict(unit_id=uid,**{k:transform[k] for k in ('_gridX','_gridY','_positionX','_positionY') if type(transform.get(k)) in (int,float)}))
                        if debug and not result.get('transform_keys'):result['transform_keys']=list(transform)
                    result['units']=parsed
            if isinstance(c.get('battleEngine'),TableRef):
                e=self.heap.table(c['battleEngine'])
                module=self.heap.table(e['battleModule'])
                if debug:result['battle_module_keys']=list(module)
                result['battle']={k:module[k] for k in ('battleID','state','elapsed_time','timeScale','result','max_time','ticks') if type(module.get(k)) in (int,float,bool)}
                if isinstance(module.get('clientBattle'),TableRef):
                    client=self.heap.table(module['clientBattle'])
                    if debug:result['client_battle_keys']=list(client)
                    result['battle_input']={k:client[k] for k in ('seed','battleID','battleMode') if type(client.get(k)) is int}
                    if debug:
                        result['battle_input_details']={k:plain(self.heap,client[k],8) for k in ('enemy_round_configs','fieldNpcInfo') if k in client}
                        heroes=[]
                        if isinstance(client.get('self_heroes'),TableRef):
                            for _,ref in sorted(self.heap.table(client['self_heroes']).items()):
                                h=self.heap.table(ref);pet=self.heap.table(h['petData'])
                                heroes.append(dict(petData={k:plain(self.heap,pet[k],4) for k in (
                                    'tid','level','progress','evoTID','starLv','feed','badgeProps') if k in pet},
                                    config=plain(self.heap,h.get('config'),3)))
                        result['battle_input_details']['self_heroes']=heroes
        victories=[v for v in self.tables('ed.StageBattleVictoryView') if v.get('isShow') is True]
        if len(victories)>1:raise LiveReadError('胜利结算界面不唯一')
        if victories:
            result['victory']={k:victories[0][k] for k in ('isShow','animFinished','animStarted','autoRecvShowDuration','exitType') if type(victories[0].get(k)) in (int,float,bool,str)}
        prepares=[p for p in self.tables('ed.StageBattlePrepareView') if p.get('stageID')==result['current_stage_id']]
        if len(prepares)>1:raise LiveReadError('当前关卡布阵对象不唯一')
        if prepares:
            p=prepares[0]
            result['prepare']={k:p[k] for k in ('isShow','stageID','_isStarted','isPlayingAutoIn','_currentPrepareListRowCount') if type(p.get(k)) in (int,bool)}
            result['touch']={k:plain(self.heap,p[k],1) for k in ('touchBeganPosition','touchMovedPosition','touchEndedPosition','currentSelectedGrid','mouseDown') if k in p}
            if isinstance(p.get('selectedUnitDict'),TableRef):
                selected=[]
                for uid,ref in self.heap.table(p['selectedUnitDict']).items():
                    unit=self.heap.table(ref);t=self.heap.table(unit['transformComponent'])
                    selected.append(dict(unit_id=uid,**{k:t[k] for k in ('_gridX','_gridY','_positionX','_positionY') if k in t}))
                result['selected']=selected
            if isinstance(p.get('selectedUnitGrid'),TableRef):
                order=[]
                for x,column in lua_pairs(self.heap,p['selectedUnitGrid']):
                    if not isinstance(column,TableRef):continue
                    for y,ref in lua_pairs(self.heap,column):
                        if not isinstance(ref,TableRef):continue
                        uid=self.heap.table(ref).get('tid')
                        if type(uid) is int:order.append(dict(unit_id=uid,x=x,y=y))
                result['request_order']=order
            if isinstance(p.get('_filterList'),TableRef):
                result['pet_list']=[self.heap.table(ref).get('tid') for _,ref in sorted(self.heap.table(p['_filterList']).items()) if isinstance(ref,TableRef)]
            if debug:result['prepare_keys']=list(p)
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',default=str(RUNTIME/'live-battle.json'));p.add_argument('--debug',action='store_true');p.add_argument('--serve',action='store_true')
    a=p.parse_args();live=LiveBattle()
    try:
        import json
        if a.serve:
            print(json.dumps(dict(ready=True)),flush=True)
            for line in sys.stdin:
                try:
                    request=json.loads(line);value=live.snapshot(request.get('debug',False))
                    write_json(a.out,value);print(json.dumps(value,ensure_ascii=False),flush=True)
                except Exception as exc:print(json.dumps(dict(error=str(exc)),ensure_ascii=False),flush=True)
        else:
            value=live.snapshot(a.debug);write_json(a.out,value)
            print(json.dumps(value,ensure_ascii=False),flush=True)
    finally:live.close()


if __name__=='__main__':main()
