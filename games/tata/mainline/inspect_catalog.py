"""Resolve asset paths to bundle dependencies in the recovered FlatBuffers catalog.

Field order comes from ContentCatalogDataBinary metadata. This inspects local data;
it does not guess CDN URLs or download/execute game content.
"""
import argparse,hashlib,json,struct
from pathlib import Path


def parse(blob):
    def u(p):
        if p<0 or p+4>len(blob):raise ValueError('Catalog offset outside buffer')
        return struct.unpack_from('<I',blob,p)[0]
    def field(index):
        root=u(0);vt=root-struct.unpack_from('<i',blob,root)[0]
        if vt<0 or vt+4>len(blob):raise ValueError('Invalid catalog vtable')
        size=struct.unpack_from('<H',blob,vt)[0]
        if 4+index*2+2>size:raise ValueError('Missing catalog field')
        offset=struct.unpack_from('<H',blob,vt+4+index*2)[0]
        if not offset:raise ValueError('Missing catalog field')
        p=root+offset;return p+u(p)
    def vector(index):
        p=field(index);n=u(p)
        if n>len(blob)-p-4:raise ValueError('Truncated catalog vector')
        return blob[p+4:p+4+n]
    def string(p):
        n=u(p)
        if n>len(blob)-p-4:raise ValueError('Truncated catalog string')
        return blob[p+4:p+4+n].decode('utf-8')
    p=field(5);count=u(p)
    if count>(len(blob)-p-4)//4:raise ValueError('Truncated internal IDs')
    internal=[]
    for i in range(count):
        q=p+4+i*4;internal.append(string(q+u(q)))
    keys,buckets,entries=vector(6),vector(7),vector(8)
    if min(map(len,(keys,buckets,entries)))<4:raise ValueError('Missing catalog data header')
    entry_count=struct.unpack_from('<I',entries)[0]
    if len(entries)!=4+entry_count*24:raise ValueError('Unsupported entry stride; expected six int32')
    rows=[struct.unpack_from('<6i',entries,4+i*24) for i in range(entry_count)]
    bucket_count=struct.unpack_from('<I',buckets)[0]
    if bucket_count>(len(buckets)-4)//8:raise ValueError('Invalid bucket count')
    locations=[];pos=4
    for _ in range(bucket_count):
        if pos+8>len(buckets):raise ValueError('Truncated catalog bucket')
        offset,n=struct.unpack_from('<II',buckets,pos);pos+=8
        if pos+n*4>len(buckets) or offset>=len(keys):raise ValueError('Invalid bucket extent')
        indices=struct.unpack_from('<'+'I'*n,buckets,pos);pos+=n*4
        if any(i>=entry_count for i in indices):raise ValueError('Invalid entry index')
        key=None
        if keys[offset] in (0,1):
            if offset+5>len(keys):raise ValueError('Truncated key')
            size=struct.unpack_from('<I',keys,offset+1)[0]
            if offset+5+size>len(keys):raise ValueError('Truncated key string')
            key=keys[offset+5:offset+5+size].decode('utf-8' if keys[offset]==0 else 'utf-16le')
        locations.append((key,indices))
    if pos!=len(buckets):raise ValueError('Unexpected bucket trailer')
    result={}
    for key,indices in locations:
        if not key or '/' not in key:continue
        deps=set()
        for index in indices:
            row=rows[index]
            if not 0<=row[0]<len(internal):raise ValueError('Invalid internal ID')
            dependency=row[2]
            if dependency==-1:continue
            if not 0<=dependency<len(locations):raise ValueError('Invalid dependency bucket')
            for dep in locations[dependency][1]:
                j=rows[dep][0]
                if not 0<=j<len(internal):raise ValueError('Invalid dependency internal ID')
                deps.add(internal[j])
        if deps:result[key]=sorted(deps)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('catalog',type=Path);p.add_argument('--asset');p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();raw=a.catalog.read_bytes();locations=parse(raw)
    matches={k:v for k,v in locations.items() if a.asset and k.casefold()==a.asset.casefold()
             or not a.asset and 'battlescene_bg_' in k.lower()}
    report=dict(catalog_sha256=hashlib.sha256(raw).hexdigest(),locations=len(locations),matches=matches)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'locations={len(locations)} matches={len(matches)}')
