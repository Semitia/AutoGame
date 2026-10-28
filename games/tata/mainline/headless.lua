-- Host bridge only. Combat methods and configurations come from original bytecode.
local env, modules, loaded, loading = {}, {}, {}, {}
for _,k in ipairs({'assert','error','ipairs','pairs','next','select','tonumber','tostring','type',
    'getmetatable','setmetatable','rawget','rawset','rawequal','pcall','xpcall','collectgarbage'}) do env[k]=_G[k] end
env.math,env.string,env.table,env.coroutine = math,string,{},coroutine
env._VERSION=_VERSION
env.math.atan2=math.atan
env.math.log10=function(x) return math.log(x,10) end
env.math.clamp=function(x,lo,hi) return math.max(lo,math.min(hi,x)) end
env.math.deg2rad=math.pi/180
env.math.rad2deg=180/math.pi
env.string.interp=function(template,...)
    local args={...}
    return (template:gsub('%${(.-)}',function(key)
        local value=tonumber(key) and args[tonumber(key)] or (type(args[1])=='table' and args[1][key])
        assert(value~=nil,'Missing template argument '..key)
        return tostring(value)
    end))
end
env.string.isNilOrEmpty=function(s) return s==nil or s=='' end
env.Mathf={Random=math.random}
env.UnityEngine={Mathf=env.Mathf}
for k,v in pairs(table) do env.table[k]=v end
env.unpack=table.unpack
env.table.add=table.insert
env.table.clear=function(t) for k in pairs(t) do t[k]=nil end end
env.table.cleararray=function(t) for i=#t,1,-1 do t[i]=nil end end
env.table.indexOf=function(t,v) for i,x in ipairs(t) do if x==v then return i end end end
env.table.containsValue=function(t,v) for _,x in pairs(t) do if x==v then return true end end return false end
env.table.removeByValue=function(t,v) local i=env.table.indexOf(t,v);if i then return table.remove(t,i) end end
env.table.reverse=function(t) for i=1,math.floor(#t/2) do t[i],t[#t-i+1]=t[#t-i+1],t[i] end return t end
env.table.keys=function(t) local a={};for k in pairs(t) do a[#a+1]=k end return a end
env.table.values=function(t) local a={};for _,v in pairs(t) do a[#a+1]=v end return a end
env.table.nums=function(t) local n=0;for _ in pairs(t) do n=n+1 end return n end
env.table.isNilOrEmpty=function(t) return t==nil or next(t)==nil end
env.table.merge=function(t,source) for _,v in ipairs(source) do table.insert(t,v) end return t end
env.table.clone=function(t) local c={};for k,v in pairs(t) do c[k]=v end return c end
env.clone=function(t,seen)
    if type(t)~='table' then return t end
    seen=seen or {};if seen[t] then return seen[t] end
    local c={};seen[t]=c;for k,v in pairs(t) do c[env.clone(k,seen)]=env.clone(v,seen) end
    return setmetatable(c,getmetatable(t))
end
env.config={}
env._G=env
env.class=function(name,super,...)
    local parents={super,...}
    local cls={__cname=name,super=super}
    cls.__index=cls
    setmetatable(cls,{__index=function(_,key)
        for _,parent in ipairs(parents) do local v=parent[key];if v~=nil then return v end end
    end})
    cls.Create=function(...)
        local obj=setmetatable({class=cls},cls)
        if obj.Ctor then obj:Ctor(...) end
        return obj
    end
    cls.New=cls.Create
    return cls
end
local registry=setmetatable({}, {
    __newindex=function(_,k,v) modules[k]=v end,
    __index=function() return function() end end
})
env.luacode=registry
local function execute(blob,name)
    return assert(load(blob,name,'b',env))()
end
local function init(name)
    if loaded[name] then return loaded[name] end
    assert(not loading[name],'Circular module: '..name)
    loading[name]=true
    local result=assert(modules[name],'Module missing: '..name)(registry)
    loaded[name]=result or true;loading[name]=nil
    return result
end
env.ed=setmetatable({}, {__index=function(t,key)
    env.load_ed(key)
    return rawget(t,key)
end})
local api={env=env,modules=modules,execute=execute,init=init}
env.require=function(name)
    if loaded[name] then return loaded[name] end
    local key=name:gsub('%.','_')
    if modules[key] then return init(key) end
    assert(not loading[name],'Circular require: '..name)
    loading[name]=true
    local result=api.load_file(name)
    loaded[name]=result or true;loading[name]=nil
    return result
end
env.Drequire=env.require
local function config_table(name)
    local parts={};for part in name:gmatch('[^.]+') do parts[#parts+1]=part end
    local t=env.config
    for i=1,#parts-1 do t=t[parts[i]];if not t then return nil end end
    return t[parts[#parts]..'Table']
end
api.config_table=config_table
env.ed.getDataTable=function(name)
    return config_table(name) or env.load_config(name)
end
env.ed.lookupDataTable=function(name,field,...)
    local row=env.ed.getDataTable(name)
    for _,key in ipairs({...}) do if row==nil then return nil end;row=row[key] end
    return row and row[field]
end
-- Display/logging adapters do not change combat state.
env.ed.log=function() end;env.ed.warn=function() end
env.event=setmetatable({}, {__index=function(t,group)
    local v=setmetatable({}, {__index=function(s,key) local name=group..'.'..key;rawset(s,key,name);return name end})
    rawset(t,group,v);return v
end})
api.ui_events={}
env.ed.fireEvent=function(name,...) api.ui_events[#api.ui_events+1]={name,...} end
env.ed.error=function(...) error(table.concat({...},' ')) end
env.ed.assert=assert
env.ed.override=function(original,replacement)
    assert(original);assert(replacement)
    return function(...) return replacement(original,...) end
end
env.ed.SortingLayer={BattleUnit=0,BattleEffectBackground=0,BattleEffectForeground=0,BattleProjectile=0}
env.ed.Sys={isEditor=false}
-- Native grid storage bridge; path search uses the game's retained Lua algorithm.
-- Native-vs-Lua path tie-breaking still requires calibration against a real replay.
env.BattleAStarData={
    Create=function(w,h) return {width=w,height=h,occupied={}} end,
    Reset=function(m) m.occupied={} end,
    Destroy=function(m) m.occupied={} end,
    OccupyGrid=function(m,x,y) m.occupied[x*10000+y]=true end,
    ReleaseGrid=function(m,x,y) m.occupied[x*10000+y]=nil end,
    IsOccupied=function(m,x,y) return m.occupied[x*10000+y]==true end
}
env.BattleAStar={
    Create=function(w,h) return env.require('Src.Battle.Logic.Utils.BattleAStar').Create(api.current_engine,w,h) end,
    Destroy=function(a) end,
    FindPath=function(a,...) return a:FindPath(...) end
}
api.capture=function(blob) execute(blob,'bundle') end
api.engine=function()
    local e=env.ed.BattleEngine.Create(1);api.current_engine=e;return e
end
api.make_enums=function()
    for _,t in pairs(env.enum) do
        setmetatable(t,{__call=function(_,value)
            for key,v in pairs(t) do if v==value then return key end end
            error('Unknown enum value: '..tostring(value))
        end})
    end
end
return api
