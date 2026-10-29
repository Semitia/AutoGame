"""Prior-guided original-Lua search with persistent cases and online preference learning."""
import argparse
from pathlib import Path
import math

from combat import Simulator
from experience import Experience,DEFAULT_PATH
from model import Catalog,RUNTIME,read_json,write_json
from review import MODES


def search(sim,stage,budget=120,seed=123456,progress=None,initial_plan=None,experience=None,**options):
    from search_session import run_search
    return run_search(sim,stage,budget,seed,progress,initial_plan,experience,**options)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',type=Path,default=RUNTIME/'live-capture.json')
    p.add_argument('--stage',default='11-26');p.add_argument('--budget',type=int,default=120)
    p.add_argument('--out',type=Path,default=RUNTIME/'search-result.json');p.add_argument('--initial',type=Path)
    p.add_argument('--seconds',type=float,default=0,help='搜索秒数上限，0不限；在两次模拟之间检查')
    p.add_argument('--stop-file',type=Path);p.add_argument('--checkpoint',type=Path);p.add_argument('--resume',type=Path)
    p.add_argument('--stop-on-success',action='store_true');p.add_argument('--robust-orders',action='store_true')
    p.add_argument('--review',choices=MODES,help='复核方式：light默认1次，none关闭，full完整多种子/顺序；旧--robust-orders等同full')
    p.add_argument('--experience',type=Path,default=DEFAULT_PATH)
    p.add_argument('--no-experience',action='store_true',help='Independent cold search; neither reads nor writes experience')
    a=p.parse_args()
    if a.budget<0 or not math.isfinite(a.seconds) or a.seconds<0:p.error('候选/时长上限不能为负，0表示不限')
    def status(value):
        write_json(a.out.with_suffix('.progress.json'),value)
    status(dict(status='searching',phase='initializing',evaluated=0,budget=a.budget,max_seconds=a.seconds))
    memory=None
    try:
        c=Catalog();stage=c.stage(next((s['id'] for s in c.stages if s['name']==a.stage),a.stage))
        sim=Simulator(read_json(a.capture),c)
        memory=None if a.no_experience else Experience(a.experience)
        result=search(sim,stage,a.budget,status=status,experience=memory,max_seconds=a.seconds,
            stop_path=a.stop_file or a.out.with_suffix('.STOP'),checkpoint=a.checkpoint or a.out.with_suffix('.checkpoint.json'),
            resume=a.resume,stop_when_verified=a.stop_on_success,robust_orders=a.robust_orders,review_mode=a.review,
            initial_plan=read_json(a.initial)['placements'] if a.initial else None)
        write_json(a.out,result)
        from job_status import search_summary
        print(search_summary(result),flush=True)
    except Exception as exc:
        status(dict(status='error',reason=str(exc)))
        raise
    finally:
        if memory:memory.close()


if __name__=='__main__':main()
