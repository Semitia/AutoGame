"""Compare Python grid/star rules with executable original Lua 5.4 bytecode."""
import argparse,json
from pathlib import Path
from model import Catalog
from probe_headless import runtime
from rules import grid_areas,star_icons


def verify(source,data,dataset):
    catalog=Catalog(data,dataset)
    lua,setup=runtime(source)
    setup.init('Src_Battle_Logic_System_BattleBaseModule')
    setup.init('Src_Battle_Logic_Module_BattleModule')
    def value(obj):
        if isinstance(obj,dict): return lua.table_from({int(k) if str(k).isdigit() else k:value(v) for k,v in obj.items()})
        if isinstance(obj,list): return lua.table_from([value(v) for v in obj])
        return obj
    original=lua.eval('''function(env,mode,config)
        env.enum={BattleMode={Stage=1}}
        env.ed.getDataTable=function() return {[1]=mode} end
        env.ed.BattleConfigUtils={getBattleEnemyRoundConfig=function() return {config=config} end}
        env.table.add=table.insert
        local m={}
        env.ed.BattleModule.InitFieldGridsArea(m,1,1)
        env.ed.BattleModule.InitDeployGridsArea(m,1,1)
        return {field=m.fieldGridsArea,deploy=m.deployGridsArea}
    end''')
    errors=[]; samples=[]
    for stage in catalog.stages:
        d=catalog.stage(stage['id'])
        got=original(setup.env,value(catalog.battle_mode),value(d['waves']))
        expected={name:dict(area.items()) for name,area in got.items()}
        actual=grid_areas(d)
        if actual!=expected: errors.append(dict(stage=stage['id'],actual=actual,expected=expected))
        if stage['id'] in (1,2,3,4,5,6,7,8,9,10,101,826,6400):
            samples.append(dict(stage=stage['name'],areas=actual))
    # PetStarPanel's original pure methods can be loaded without any UI constructor.
    setup.env.ed.uiTypes=lua.table(); setup.env.ed.Mvc=lua.table_from({'BaseSubView':lua.table()})
    setup.env.Drequire=lua.eval('function() return {} end')
    setup.env.ed.lookupDataTable=lua.eval(f'function() return {catalog.star_grade} end')
    load=lua.eval('function(blob,env) return assert(load(blob,"star","b",env))() end')
    cls=load((source/'Src/UI/Pet/Component/PetStarPanel.luae').read_bytes(),setup.env)
    obj=lua.eval('function(c) return setmetatable({},{__index=c}) end')(cls)
    star_errors=[]
    for stars in range(catalog.max_star+1):
        if cls.IsSpecialPlusStar(obj,stars):
            ids=[13+catalog.star_grade+stars-cls.GetSpecialPlusStartLevel(obj)]
        elif cls.IsSpecialStar(obj,stars):
            ids=[13+stars-cls.GetSpecialStarStartLevel(obj)]
        elif stars==0: ids=[]
        else: ids=[v for _,v in sorted(cls.GetStarLevels(obj,stars).items())]
        if ids!=star_icons(stars,catalog.star_grade): star_errors.append(stars)
    return dict(grid_checked=len(catalog.stages),grid_errors=errors,samples=samples,
                stars_checked=catalog.max_star+1,star_errors=star_errors)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--data',type=Path,required=True)
    p.add_argument('--dataset',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();report=verify(a.source,a.data,a.dataset)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print({k:v for k,v in report.items() if k!='samples'})
    raise SystemExit(bool(report['grid_errors'] or report['star_errors']))
