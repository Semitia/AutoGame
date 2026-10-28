"""Probe recovered Lua modules without Unity. This is not a combat simulator.

Capture original bytecode initializers without running them, then run only math, engine,
and battle-module initializers. Tick uses recording doubles to verify dispatch.
"""
import argparse
import json
from pathlib import Path

from lupa.lua54 import LuaRuntime


def probe(source: Path):
    lua = LuaRuntime(register_eval=False, register_builtins=False, max_memory=256*1024*1024)
    setup = lua.eval('''function()
        local modules = {}
        local registry = setmetatable({}, {
            __newindex = function(_, key, fn) modules[key] = fn end,
            __index = function() return function() end end
        })
        local env = {ed={}, luacode=registry, math=math, table=table,
            string=string, pairs=pairs, ipairs=ipairs, type=type,
            tostring=tostring, tonumber=tonumber, assert=assert,
            error=error, select=select, next=next, setmetatable=setmetatable}
        -- Minimal class adapter for method definitions only; no Unity objects.
        env.class = function(name, super)
            local c = {super=super}
            c.__index = c
            setmetatable(c, {__index=super})
            c.Create = function(...)
                local o = setmetatable({}, c)
                if c.Ctor then c.Ctor(o, ...) end
                return o
            end
            return c
        end
        local function bounded(fn, ...)
            local count = 0
            debug.sethook(function()
                count = count + 1
                if count > 50000 then error("instruction budget exceeded") end
            end, "", 1000)
            local ok, result = pcall(fn, ...)
            debug.sethook()
            if not ok then error(result) end
            return result
        end
        local function capture(text)
            bounded(assert(load(text, "bundle", "b", env)))
        end
        local function init(name) bounded(assert(modules[name]), registry) end
        local function smoke()
            init("Src_Battle_Version")
            init("Src_Battle_Logic_Utils_BattleMath")
            init("Src_Battle_Logic_System_BattleBaseModule")
            init("Src_Battle_Logic_Module_BattleModule")
            init("Src_Battle_Logic_BattleEngine")
            local module = {}
            env.ed.BattleModule.OnInit(module)
            local events = {}
            local function record(name)
                return function() events[#events+1] = name end
            end
            local e = {battleModule={IncreaseTicks=record("increaseTicks")}}
            for _, name in ipairs({"battleOperationSystem", "battleUnitSystem",
                "updateEventSystem", "enemySpawnSystem", "battleMapSystem",
                "scheduleSystem", "battleEndCheckSystem"}) do
                e[name] = {Update=record(name)}
            end
            e.updateEventSystem.UpdateDelayActiveProjectiles = record("activateProjectiles")
            e.battleUnitSystem.FlushBroadcastEvents = record("broadcastEvents")
            env.ed.BattleEngine.Tick(e, module.dt)
            return {version=env.ed.battleCheckVersion, dt=module.dt,
                defaultTimeScale=module.timeScale, events=events,
                sin90=env.ed.BattleMath.sin(90 * env.ed.BattleMath.DEG2RAD)}
        end
        return {capture=capture, modules=modules, smoke=smoke}
    end''')()
    setup.capture((source / 'Src/game_battle.luae').read_bytes())
    smoke = setup.smoke()
    return dict(bundle='Src/game_battle.luae', modules=sorted(setup.modules.keys()),
                battle_check_version=smoke.version, default_dt=smoke.dt,
                default_time_scale=smoke.defaultTimeScale, sin90=smoke.sin90,
                tick_dispatch=[v for _, v in sorted(smoke.events.items())],
                limitation='Tick dispatch uses recording doubles. No units, damage, or victory simulated.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = probe(args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
