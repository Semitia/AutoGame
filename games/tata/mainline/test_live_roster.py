"""Synthetic ABI fixtures: no game dump or player data is included in tests."""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from live_roster import (LuaHeap, TableRef, LiveReadError, find_pet_models,
                         extract_model, to_roster, read_live)
from model import load_roster, write_json
from test_workbench import catalog


class Fixture:
    def __init__(self):
        self.data=bytearray(32768);self.pos=64;self.strings={}
    def alloc(self,n):
        p=self.pos;self.pos+=(n+7)//8*8;return p
    def string(self,s):
        if s in self.strings:return self.strings[s]
        b=s.encode();p=self.alloc(17+len(b));self.strings[s]=p
        self.data[p+4]=4;self.data[p+7]=len(b);self.data[p+16:p+16+len(b)]=b
        return p
    def value(self,v):
        if type(v) is bool:return bytes(8)+bytes([17 if v else 1])+bytes(7)
        if type(v) is int:return struct.pack('<q',v)+b'\x03'+bytes(7)
        if isinstance(v,TableRef):return struct.pack('<I',v.address)+bytes(4)+b'\x45'+bytes(7)
        return struct.pack('<I',self.string(v))+bytes(4)+b'\x44'+bytes(7)
    def table(self,entries):
        p=self.alloc(32);log=max(0,(len(entries)-1).bit_length());nodes=self.alloc(24*(1<<log))
        self.data[p+4]=5;self.data[p+7]=log;struct.pack_into('<I',self.data,p+16,nodes)
        for i,(key,value) in enumerate(entries.items()):
            q=nodes+24*i;kv=self.value(key);v=self.value(value)
            self.data[q:q+9]=v[:9];self.data[q+9]=kv[8];self.data[q+16:q+24]=kv[:8]
        return TableRef(p)
    def model(self,owned=True):
        cls=self.table({'__cname':'ed.PetModel'})
        feed=self.table(dict(petTid=1,feedLevel=1,feedGrowth=3,feedCount=2))
        pet=self.table(dict(tid=1,level=234,starLv=1,evoTID=1,isGet=owned,feedData=feed,gs=100))
        pets=self.table({1:pet})
        return self.table(dict(_level=234,hasInitPets=True,petCount=1,pets=pets,**{'class':cls}))
    def heap(self):return LuaHeap(lambda p,n:bytes(self.data[p:p+n]),len(self.data))


def capture():
    return dict(captured_at='2026-10-28T12:00:00+00:00',shared_level=234,
        pets=[dict(tid=1,level=234,evoTID=1,starLv=1,gs=100,isGet=True,
                   feed=dict(petTid=1,feedLevel=1,feedGrowth=3,feedCount=2))])


class LiveRosterTests(unittest.TestCase):
    def test_owned_model_before_encyclopedia_adds_isget_flag(self):
        f=Fixture();root=f.model();heap=f.heap()
        pet=heap.table(heap.table(heap.table(root)['pets'])[1])
        ref=heap.table(heap.table(root)['pets'])[1]
        header=f.data[ref.address:ref.address+32];node=struct.unpack_from('<I',header,16)[0]
        for i in range(1<<header[7]):
            offset=node+i*24
            if heap.value(f.data,offset+16,f.data[offset+9])=='isGet':f.data[offset+8]=0
        self.assertNotIn('isGet',heap.table(ref))
        self.assertTrue(extract_model(heap,root)['pets'][0]['isGet'])

    def test_discovery_uses_structure_and_class_not_fixed_offsets(self):
        f=Fixture();f.alloc(1232);root=f.model()
        self.assertEqual(find_pet_models(bytes(f.data)),[root])
        value=extract_model(f.heap(),root)
        self.assertEqual(value['shared_level'],234)
        self.assertEqual(value['pets'][0]['feed']['feedLevel'],1)
        # A coincidentally matching _level table is not another model.
        f.table(dict(_level=234,pets=f.table({}),hasInitPets=True))
        self.assertEqual(find_pet_models(bytes(f.data)),[root])

    def test_array_part_and_dead_nodes(self):
        f=Fixture();ref=f.table({'discarded':'old'})
        nodes=struct.unpack_from('<I',f.data,ref.address+16)[0]
        f.data[nodes+8]=0  # Nil value with a stale key pointer must be ignored.
        array=f.alloc(32);f.data[array:array+16]=f.value(42);f.data[array+16:array+32]=f.value(False)
        struct.pack_into('<II',f.data,ref.address+8,2,array)
        self.assertEqual(f.heap().table(ref),{1:42,2:False})

    def test_invalid_pointers_and_unowned_are_rejected(self):
        f=Fixture();root=f.model(owned=False)
        with self.assertRaisesRegex(LiveReadError,'已拥有'):extract_model(f.heap(),root)
        with self.assertRaises(LiveReadError):f.heap().table(TableRef(999999))
        struct.pack_into('<I',f.data,root.address+16,len(f.data)-8)
        with self.assertRaises(LiveReadError):f.heap().table(root)

    def test_conversion_preserves_exact_observation_and_derives_ranks(self):
        c=catalog();value=to_roster(capture(),c);pet=value['pets'][0]
        self.assertEqual(pet['attribute_ranks'],dict(ATK='D',DEF='E',HP='E'))
        self.assertEqual(pet['game_observed']['feed']['feedGrowth'],3)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'roster.json';write_json(path,value)
            self.assertEqual(load_roster(path,c)['pets'],value['pets'])
        changed=capture();changed['pets'][0]['feed']['feedLevel']=999
        with self.assertRaisesRegex(LiveReadError,'缺少'):to_roster(changed,c)
        changed=capture();changed['pets'][0]['token']='must not be saved'
        # The conversion only accepts the game-state allowlist.
        with self.assertRaisesRegex(ValueError,'观测字段'):to_roster(changed,c)
        for key,value in [('isGet',False),('level',233)]:
            changed=capture();changed['pets'][0][key]=value
            with self.subTest(key=key),self.assertRaises(LiveReadError):to_roster(changed,c)

    def test_changing_or_multiple_live_models_are_rejected(self):
        class Reader:
            def __init__(self,pid):pass
            def heaps(self):return [(0,256)]
            def read(self,p,n):return b'cs_common.Dn_Pet PetModel evoTID starLv'.ljust(n,b'\0')
            def close(self):pass
        with patch('live_roster.renderer_pids',return_value=[1]),patch('live_roster.WindowsReader',Reader),patch(
                'live_roster.find_pet_models',return_value=[TableRef(8)]),patch(
                'live_roster.extract_model',side_effect=[dict(shared_level=1),dict(shared_level=2)]):
            with self.assertRaisesRegex(LiveReadError,'正在变化'):read_live()
        with patch('live_roster.renderer_pids',return_value=[1,2]),patch('live_roster.WindowsReader',Reader),patch(
                'live_roster.find_pet_models',return_value=[TableRef(8)]),patch(
                'live_roster.extract_model',return_value=dict(shared_level=1)):
            with self.assertRaisesRegex(LiveReadError,'多个'):read_live()


if __name__=='__main__':unittest.main()
