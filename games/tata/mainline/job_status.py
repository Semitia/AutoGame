"""Human-readable job results shared by CLI and panel; no desktop dependencies."""
PHASES={'initializing':'加载战斗引擎','starting':'生成初始候选','resuming':'恢复搜索进度',
    'validating':'模拟复核','single-replacement':'系统检查单宠替换'}


def search_limits(candidates,minutes):
    import math
    try:budget=int(candidates);seconds=float(minutes)*60
    except (ValueError,TypeError):raise ValueError('候选上限填整数，搜索时长填分钟；0表示不限')
    if budget<0 or not math.isfinite(seconds) or seconds<0:raise ValueError('候选/搜索时长上限应为非负数；0表示不限')
    return budget,seconds


def duration(seconds):
    seconds=max(0,int(seconds));return f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}'


def search_summary(value):
    state=value.get('status');reason=value.get('reason','')
    if state=='error':return '搜索出错：'+reason
    if state in ('verified','no_solution','cancelled'):
        prefix={'verified':'已找到通过方案（仍待实战）','no_solution':'本次未找到符合当前复核设置的方案','cancelled':'搜索已停止'}[state]
    else:prefix=PHASES.get(value.get('phase'),'搜索中')
    n=value.get('run_evaluated',value.get('evaluated',0));limit=value.get('budget',0)
    details=f'本轮候选 {n}'+(f'/{limit}' if limit else '（数量不限）')
    if value.get('evaluated',0)>n:details+=f' · 累计 {value["evaluated"]}'
    details+=f' · 用时 {duration(value.get("run_elapsed_seconds",0))}'
    if value.get('review_mode'):
        from review import LABELS
        details+=' · 复核 '+LABELS.get(value['review_mode'],value['review_mode'])
    if value.get('max_seconds'):details+='/'+duration(value['max_seconds'])
    checks=value.get('validation_total',0);wins=value.get('validation_wins',0);checked=value.get('validation_checked',checks)
    if value.get('finalists'):
        best=value['finalists'][0];checks=best.get('validation_expected',len(best.get('validation',[])))
        wins=sum(v['won'] for v in best.get('validation',[]));checked=len(best.get('validation',[]))
    if checked:details+=f' · 最佳复核 {wins}/{checked}'+(f'（尚缺 {checks-checked} 次）' if checked<checks else '')
    if value.get('simulations'):details+=f' · 模拟 {value["simulations"]} 次'
    v=value.get('evaluation',{})
    if 'kills' in v:details+=f' · 击杀 {v["kills"]}/{v["total_enemies"]}'
    if value.get('replacement_total'):details+=f' · 单宠替换第 {value.get("replacement_round",1)} 轮 {value.get("replacement_checked",0)}/{value["replacement_total"]}'
    return prefix+' · '+details+(' · '+reason if reason else '')


def error_code(exc):
    text=str(exc)
    if type(exc).__name__=='LiveReadError':return 'game_state_error'
    if '前台' in text or '遮挡' in text:return 'foreground_lost'
    if '尺寸' in text or '校准' in text:return 'calibration_error'
    if '超时' in text:return 'game_timeout'
    if '停止' in text or 'F8' in text:return 'user_stop' if '用户' in text or 'F8' in text else 'verification_failed'
    return 'error'


def autoplay_summary(value):
    if value.get('search'):return search_summary(value['search'])
    event=value.get('event');reason=value.get('reason','')
    labels={'initializing':'正在连接游戏','planning':'同步后评估阵容','deploy':'自动布阵',
        'deployment_verified':'整队核验通过','request_order_verified':'入场顺序复核通过','battle_started':'实战中',
        'request_order_checked':'整队与入场顺序已核对（模拟复核已关闭）',
        'battle_settled':'实战已结算','preparation_ready':'下一关布阵就绪','stage_advanced':'已进入下一关',
        'finished':'本次完成','stopped':'已停止'}
    return f'自动推关 · 已通过 {len(value.get("completed",[]))} 关 · '+labels.get(event,event or '准备中')+('：'+reason if reason else '')
