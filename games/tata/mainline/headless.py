"""Original-bytecode combat runtime. Missing dependencies fail explicitly."""
from pathlib import Path
import struct

from lupa.lua54 import LuaRuntime

SOURCE = Path(__file__).resolve().parents[3]/'runtime/tata/research/decoded-0.50.1'


class CombatRuntime:
    def __init__(self, source=SOURCE):
        self.source=Path(source)
        self.lua=LuaRuntime(register_eval=False,register_builtins=False,max_memory=512*1024**2)
        self.api=self.lua.execute(Path(__file__).with_name('headless.lua').read_text(encoding='utf-8'))
        self.env=self.api.env
        self.api.load_file=self.load_file
        for name in ('game_common','game_base1','game_base2','game_battle'):
            self.api.capture((self.source/f'Src/{name}.luae').read_bytes())
        self.modules=set(self.api.modules.keys())
        self.unresolved=set()
        self.env.load_ed=self.load_ed
        self.env.load_config=self.load_config
        self.loaded={}
        self.load_enums()
        self.load_file('Tolua.UnityEngine.Mathf')

    def load_enums(self):
        from google.protobuf.descriptor_pb2 import FileDescriptorSet
        blob=(self.source/'Pb/pgame.pbe').read_bytes();p=0;enums={}
        while p<len(blob):
            size=struct.unpack_from('<I',blob,p)[0];p+=4
            group=FileDescriptorSet.FromString(blob[p:p+size]);p+=size
            for file in group.file:
                if file.package not in ('enumx','enumc'):continue
                for enum in file.enum_type:
                    values=enums.setdefault(enum.name,{})
                    values.update({v.name.removeprefix(enum.name+'_'):v.number for v in enum.value})
        self.env.enum=self.value(enums)
        self.api.make_enums()

    def load_file(self,name):
        relative=name.replace('.','/')+'.luae'
        path=self.source/relative
        if not path.is_file():raise ValueError(f'Missing original module: {name}')
        return self.api.execute(path.read_bytes(),name)

    def load_ed(self,name):
        if name in self.unresolved:return None
        candidates=[k for k in self.modules if k.endswith('_'+name)]
        if not candidates:
            files=list((self.source/'Src/Battle').rglob(name+'.luae'))
            if len(files)==1:
                value=self.load_file(str(files[0].relative_to(self.source).with_suffix('')).replace('\\','.'))
                if value is not None:self.env.ed[name]=value
                return value
        if not candidates:
            self.unresolved.add(name)
            return None
        if len(candidates)!=1:raise ValueError(f'Ambiguous ed.{name}: {candidates}')
        return self.api.init(candidates[0])

    def load_config(self,name):
        self.load_file('Config.'+name)
        value=self.api.config_table(name)
        if value is None:raise ValueError(f'Config table missing: {name}')
        return value

    def value(self,obj):
        if isinstance(obj,dict):return self.lua.table_from({int(k) if str(k).isdigit() else k:self.value(v) for k,v in obj.items()})
        if isinstance(obj,list):return self.lua.table_from([self.value(v) for v in obj])
        return obj

    def initialize(self):
        for name in ('Src_Battle_Version','Src_Battle_Logic_BattleCommonDefine',
                     'Src_Battle_Logic_Utils_BattleMath','Src_Battle_Logic_Utils_BattleTools',
                     'Src_Tools_Edp'):
            self.api.init(name)
        return self.api.engine()


if __name__=='__main__':
    r=CombatRuntime();e=r.initialize();print('Original BattleEngine initialized')
