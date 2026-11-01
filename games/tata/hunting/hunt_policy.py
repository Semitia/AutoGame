"""Pure hunt decisions: high rooms never receive manual fire or rage actions."""
from dataclasses import dataclass
from hunt_config import TARGET_TID,room_for


@dataclass(frozen=True)
class Options:
    stock:int=10
    low_multiplier:int=1
    use_rage:bool=True
    rounds:int=10
    seconds:float=3600
    reserve:int=0

    def validate(self):
        import math
        if type(self.stock) is not int or not 1<=self.stock<=9999:raise ValueError('锁定储备数量应为1–9999')
        if self.low_multiplier not in (1,2,5):raise ValueError('低倍场仅支持1、2或5倍')
        if type(self.rounds) is not int or not 1<=self.rounds<=1000:raise ValueError('本次轮数应为1–1000')
        if not math.isfinite(self.seconds) or not 0<self.seconds<=86400:raise ValueError('运行时长应在0–1440分钟内')
        if type(self.reserve) is not int or self.reserve<0:raise ValueError('保留金猎币应为非负整数')
        return self


def token(enemy):return (enemy['id'],enemy['tid'],enemy['spawn_time'])


class Policy:
    def __init__(self,options):
        self.options=options.validate();self.mode=None;self.target=None;self.pending=False;self.completed=0

    def decide(self,s):
        if self.completed>=self.options.rounds:return dict(kind='finish',reason='达到本次轮数上限')
        if s['screen'] not in ('room','lobby','reward','transition'):raise ValueError('当前不是已确认的围猎界面')
        if s['screen']=='transition':return dict(kind='wait',reason='等待围猎界面就绪')
        if self.mode is None:
            self.mode='hunt' if s['locks']>=self.options.stock or (s.get('multiplier')==200 and (s['locks']>0 or s.get('lock_active'))) else 'farm'
        if s['screen']=='reward':raise ValueError('启动时存在奖励页，请先关闭后再运行围猎')
        if self.target is not None:
            if s['screen']!='room':raise ValueError('跟踪萨满时房间上下文改变，停止')
            alive=next((e for e in s['enemies'] if token(e)==self.target and e['active']),None)
            if alive is None:return dict(kind='exit',reason='目标已死亡或离场，立即退出以防自动换靶',completed=True)
            if s['bullets']<=self.options.reserve+s['multiplier']:
                return dict(kind='exit',reason='锁定期间达到金猎币保留数量',finish=True)
            if not s['lock_active']:return dict(kind='exit',reason='锁定效果已结束，退出等待下一轮')
            if s['lock_target']!=self.target[0]:return dict(kind='exit',reason='锁定已切换到其他目标，立即退出')
            return dict(kind='wait',reason='锁定萨满中；按唯一编号跟踪，不看头像是否显示')
        if self.mode=='farm' and s['locks']>=self.options.stock:self.mode='hunt'
        if self.mode=='hunt' and s['locks']<=0 and not self.pending and not s.get('lock_active'):self.mode='farm'
        desired=200 if self.mode=='hunt' else self.options.low_multiplier
        room=room_for(desired)
        if s['screen']=='lobby':
            if s['switching']:return dict(kind='wait',reason='等待场地切换完成')
            if s['total_bullets']<room['unlock_cost']:raise ValueError(f'{desired}倍场尚未解锁，未点击进入')
            if s['bullets']<max(room['need_bullets'],self.options.reserve+desired):
                raise ValueError(f'金猎币不足以进入{desired}倍场或已达到保留数量')
            if s['selected_dungeon']!=room['id']:
                ids=s['dungeons']
                if room['id'] not in ids:raise ValueError('目标场地不在当前游戏可选列表中')
                return dict(kind='next' if ids.index(s['selected_dungeon'])<ids.index(room['id']) else 'previous')
            return dict(kind='enter',dungeon=room['id'])
        if s['multiplier']!=desired:return dict(kind='exit',reason=f'切换到{desired}倍场')
        if s['bullets']<=self.options.reserve+desired:return dict(kind='exit',reason='达到金猎币保留数量',finish=True)
        if self.mode=='farm':
            if s['lock_active']:return dict(kind='exit',reason='低倍场存在已有锁定，先退出重置')
            if self.options.use_rage and s['rage']>0 and not s['rage_active']:return dict(kind='rage')
            return dict(kind='fire')
        candidates=[e for e in s['enemies'] if e['tid']==TARGET_TID and e['active']]
        if s['lock_active']:
            actual=next((e for e in candidates if e['id']==s['lock_target']),None)
            if actual is None:return dict(kind='exit',reason='锁定了其他臭臭，退出节省子弹')
            self.target=token(actual);self.pending=False
            return dict(kind='wait',reason='已确认实际锁定萨满臭臭')
        if self.pending:
            if not candidates:return dict(kind='exit',reason='锁定回读前萨满已离场',completed=True)
            return dict(kind='wait',reason='等待锁定生效；不重复消耗道具')
        if candidates:
            highest=max(e['score'] for e in s['enemies'] if e['active'])
            if any(e['score']==highest for e in candidates):return dict(kind='lock')
        return dict(kind='wait',reason='200倍场等待萨满，不发射、不使用狂暴')

    def exited(self,decision):
        if decision.get('completed'):self.completed+=1
        self.target=None;self.pending=False
