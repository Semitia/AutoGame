"""Execute isolated original functions with fake models; never attach to a game."""
import argparse
import hashlib
import json
from pathlib import Path
from hunt_paths import RUNTIME
from headless import SOURCE
from lupa.lua54 import LuaRuntime


def verify(source=SOURCE):
    if Path(source)==SOURCE and not (Path(source)/'Src/game_base1.luae').exists():
        from resources import ensure_default_resources
        ensure_default_resources()
    lua=LuaRuntime(register_eval=False,register_builtins=False,max_memory=192*1024**2)
    api=lua.execute('''
local modules={}
local env={assert=assert,error=error,ipairs=ipairs,pairs=pairs,type=type,tonumber=tonumber,
    tostring=tostring,math=math,table=table,string=string,setmetatable=setmetatable,config={}}
env.ed={Mvc={BaseProxy={},BaseView={},BaseSubView={}},BaseScene={},
    TrapBattleViewMapping={MapSeatIndex=function(x)return x end},
    AudioManager={PlayEventByID=function()end},AudioEventID={Trap_Battle_Aim=1}}
env.Drequire=function()end
env.UnityEngine={GameObject={Instantiate=function()error('Native Unity construction is not part of this check')end}}
env.T=function(_,text)return text end
env.handler=function(self,fn)return function(...)return fn(self,...)end end
env.ed.TutorialManager={GetCurrentTutorialID=function()return 0 end}
env.event={TrapBattleEvent={OnUnitDead='dead',OnClickUseItem='clicked',UseItem='use',LeaveRoom='leave'}}
env.class=function(name,super)
    local cls={__cname=name,super=super};cls.__index=cls
    setmetatable(cls,{__index=super})
    cls.New=function(...)return setmetatable({class=cls},cls)end
    return cls
end
env.luacode=setmetatable({}, {__newindex=function(_,k,v)modules[k]=v end,__index=function()return function()end end})
env.ed.lookupDataTable=function(name,key,id)return env.config[name..'Table'][id][key] end
return {env=env,modules=modules,load=function(blob)
    return assert(load(blob,'original hunt function','b',env))()
end,init=function(suffix)
    local found={};for name,fn in pairs(modules)do if name:sub(-#suffix)==suffix then found[#found+1]=fn end end
    assert(#found==1,'ambiguous/missing original module '..suffix);return found[1]()
end,checks=function()
    local ed=env.ed;local checks={}
    local function checked(name,condition)assert(condition,name);checks[#checks+1]=name end
    local enemy=ed.TrapBattleEnemyData.New()
    enemy:Init({id=77,cfgId=2008,pathID=2,createTick=4,exitTick=44},100)
    checked('enemy identity is cfgId, stable instance is id',enemy:GetUnitID()==77 and enemy:GetUnitTid()==2008)
    checked('spawn/exit ticks use 0.25 seconds',enemy:GetSpawnTime()==101 and enemy:GetExitTime()==111)
    checked('200x public config Magni and NeedBullet field values',env.config.TrapDungeonTable[8].Magni==200 and env.config.TrapDungeonTable[8].NeedBullet==90000)
    local player=ed.TrapBattlePlayerData.New();player.effectFlag={}
    player:_refreshEffectFlag(31,true)
    checked('rage activation uses effectFlag.angry for item31',player.effectFlag.angry==true)
    player:_refreshEffectFlag(31,false)
    checked('rage expiry clears effectFlag.angry',player.effectFlag.angry==nil)
    local m=ed.TrapBattleModel.New();m:_init()
    m._seatIndex=1;m._players={[1]={},[2]={}};m._enemyDataPool={};m.events={}
    m.FireEvent=function(self,ev,player,unit)self.events[#self.events+1]={ev=ev,id=unit:GetUnitID()}end
    for _,killer in ipairs({1,2})do
        local u=ed.TrapBattleEnemyData.New();u:Init({id=77,cfgId=2008},100);m._units[77]=u
        m:OnUnitDead({enemyId=77,killerUid=killer})
        checked('death removes instance for killer '..killer,m._units[77]==nil and m.events[#m.events].id==77)
    end
    local low=ed.TrapBattleEnemyData.New();low:Init({id=55,cfgId=2007},100)
    local function actor(e,x,y)return {enemyData=e,isActive=true,node={},transform={position={x=x,y=y}},
        IsValid=function()return true end,GetCollisionCenter=function()return x,y end}end
    local scene=ed.TrapBattleScene.New();scene._seatTrans={[1]={position={x=0,y=0}}}
    scene._enemyActors={[55]=actor(low,0,0),[77]=actor(enemy,2,0)}
    checked('lock prefers highest score over nearest enemy',scene:FindBestLockTarget(1)==77)
    env.ed.TrapBattleManager={GetInstance=function()return {GetScene=function()return scene end}end}
    local tip=ed.TrapBattleBossTipNode.New();tip._unitID=77;tip._tipPoint={x=0,y=0}
    tip.Destroy=function(self)self.destroyed=true end;tip:OnUpdate()
    checked('edge portrait remains while far from entry point',not tip.destroyed)
    scene._enemyActors[77].transform.position={x=.1,y=.1};tip:OnUpdate()
    checked('portrait disappears on distance, not death',tip.destroyed and scene._enemyActors[77].isActive)
    local view=ed.TrapBattleView.New();local events={}
    m.GetLockItemCount=function()return 5 end
    view.GetProxy=function()return m end
    view.FireEvent=function(self,ev,item,target)events[#events+1]={ev=ev,item=item,target=target}end
    view:_onBtnLockClick()
    checked('lock button uses item 30 and chosen instance',events[#events].ev=='use' and events[#events].item==30 and events[#events].target==77)
    local pending={}
    view.GetProxy=function()return {GetPendingBossRewards=function()return pending end}end
    view:OnBtnCloseClick();checked('exit without rewards requests leave',events[#events].ev=='leave')
    local reward;env.ed.ShowBaseRewardView=function(v)reward=v end
    pending={{amount=1}};local n=#events;view:OnBtnCloseClick()
    checked('own rewards defer leave until reward popup closes',reward and #events==n)
    reward.closeCallback(view);checked('reward close completes leave request',events[#events].ev=='leave')
    local overlay=ed.BaseRewardView.New();overlay.PlayFlyAnim=function(self)self.started=true end
    ed.isClickLocked=true;overlay:OnSimpleTap()
    checked('reward tap waits for original click lock',not overlay.started)
    ed.isClickLocked=false;overlay:OnSimpleTap()
    checked('reward UI tap starts fly animation without a dedicated close button',overlay.started)
    local backpack=ed.BackpackModel.New();backpack._itemMapRaw={[30]=8,[31]=9}
    checked('inventory comes from raw item map',backpack:GetAmount(30)==8 and backpack:GetAmount(31)==9)
    local inside=ed.InsideModel.New();inside.insideMap={[110008001]={amount=99000}}
    checked('bullet balance is insideMap.amount',inside:GetInsideAmount(110008001)==99000)
    return checks
end}
''')
    sources=[]
    def load(path):
        blob=(Path(source)/path).read_bytes();sources.append(dict(path=path,sha256=hashlib.sha256(blob).hexdigest()));api.load(blob)
    for path in ('Config/TrapZobo.luae','Config/TrapDungeon.luae','Src/game_base1.luae'):
        load(path)
    api.init('Src_AssetData_BackpackModel');api.init('Src_AssetData_InsideModel')
    api.init('BaseRewardView')
    for name in ('TrapBattleConfig','Data/TrapBattleEnemyData','Data/TrapBattlePlayerData','TrapBattleModel','TrapBattleScene',
                 'View/TrapBattleBossTipNode','View/TrapBattleView'):
        load('Src/UI/TrapBattle/'+name+'.luae')
    checks=list(api.checks().values())
    return dict(original_version='0.50.1',mode='isolated original-bytecode execution with synthetic models',
                checks=checks,passed=len(checks),sources=sources,game_input=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=RUNTIME/'original-logic-verification.json')
    a=p.parse_args();report=verify();a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'original bytecode checks={report["passed"]}; no game attachment/input')


if __name__=='__main__':main()
