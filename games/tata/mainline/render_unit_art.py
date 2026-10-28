"""Rasterize local original GPU animation Idle frames into static unit previews.

Samples the original VAT position/alpha textures, not a Spine animation player.
Optional extraction dependencies: UnityPy, numpy, opencv-python.
"""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler

from extract_cached_art import discover_tata_caches
from inspect_catalog import parse
from model import Catalog, RUNTIME, ROOT, read_json, write_json


def rasterize(mesh, texture, size=320, vertices=None, vertex_alpha=None):
    m=MeshHandler(mesh);m.process()
    if not m.m_Vertices or not m.m_UV0:raise ValueError('Mesh has no vertices/UVs')
    vertices=np.asarray(m.m_Vertices)[:,:2] if vertices is None else vertices
    uv=np.asarray(m.m_UV0)
    if vertex_alpha is None:vertex_alpha=np.ones(len(vertices))
    visible=vertices[vertex_alpha>.01]
    if not len(visible):raise ValueError('Idle frame contains no visible vertices')
    lower=visible.min(axis=0);upper=visible.max(axis=0)
    scale=(size-20)/(upper-lower).max();points=(vertices-lower)*scale+5
    points[:,1]=size-10-points[:,1]
    tex=np.asarray(texture.convert('RGBA'),dtype=float)/255;canvas=np.zeros((size,size,4))
    for triangles in m.get_triangles():
        for tri in triangles:
            xy=points[list(tri)];coords=uv[list(tri)]
            x0=max(0,int(xy[:,0].min()));x1=min(size-1,int(np.ceil(xy[:,0].max())))
            y0=max(0,int(xy[:,1].min()));y1=min(size-1,int(np.ceil(xy[:,1].max())))
            if x0>x1 or y0>y1:continue
            a,b,c=xy
            denominator=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(denominator)<1e-9:continue
            xx,yy=np.meshgrid(np.arange(x0,x1+1)+.5,np.arange(y0,y1+1)+.5)
            wa=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denominator
            wb=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denominator;wc=1-wa-wb
            inside=(wa>=-1e-5)&(wb>=-1e-5)&(wc>=-1e-5)
            uvs=wa[...,None]*coords[0]+wb[...,None]*coords[1]+wc[...,None]*coords[2]
            sx=np.clip((uvs[...,0]*(tex.shape[1]-1)).astype(int),0,tex.shape[1]-1)
            sy=np.clip(((1-uvs[...,1])*(tex.shape[0]-1)).astype(int),0,tex.shape[0]-1)
            src=tex[sy,sx].copy();src[~inside]=0
            weights=vertex_alpha[list(tri)]
            src[:,:,3]*=np.clip(wa*weights[0]+wb*weights[1]+wc*weights[2],0,1)
            dst=canvas[y0:y1+1,x0:x1+1];alpha=src[:,:,3:4]
            dst[:,:,:3]=src[:,:,:3]*alpha+dst[:,:,:3]*(1-alpha)
            dst[:,:,3:4]=alpha+dst[:,:,3:4]*(1-alpha)
    alpha=canvas[:,:,3:4]
    canvas[:,:,:3]=np.divide(canvas[:,:,:3],alpha,out=np.zeros_like(canvas[:,:,:3]),where=alpha>0)
    pixels=np.uint8(np.clip(canvas,0,1)*255)
    # Unused attachments in the stored pose can leave isolated atlas-edge fragments.
    n,labels,stats,_=cv2.connectedComponentsWithStats((pixels[:,:,3]>20).astype('uint8'),8)
    if n<2:raise ValueError('No visible mesh pixels')
    main=1+int(np.argmax(stats[1:,cv2.CC_STAT_AREA]));pixels[labels!=main]=0
    image=Image.fromarray(pixels);return image.crop(image.getbbox())


def idle_pose(mesh,position,color,index_texture,animation,animation_index,minimum,maximum):
    """CPU equivalent of the recovered GPU Skeleton Fill vertex shader's VAT path."""
    m=MeshHandler(mesh);m.process();uv=np.asarray(m.m_UV0);uv1=np.asarray(m.m_UV1)
    if position.m_TextureFormat!=17 or color.m_TextureFormat!=63:
        raise ValueError('Unsupported VAT texture formats; expected RGBAHalf/R8')
    positions=np.frombuffer(bytes(position.image_data),dtype='<f2').reshape(position.m_Height,position.m_Width,4).astype(float)
    colors=np.frombuffer(bytes(color.image_data),dtype=np.uint8).reshape(color.m_Height,color.m_Width)
    frame=int(animation['startFrame']);group=bool(animation['isTextureGroup0'])
    if index_texture.m_TextureFormat!=3:raise ValueError('Expected RGB24 vertex index texture')
    indices=np.frombuffer(bytes(index_texture.image_data),dtype=np.uint8).reshape(index_texture.m_Height,index_texture.m_Width,3)
    packed_index=indices[animation_index,np.clip(uv1[:,0].astype(int),0,index_texture.m_Width-1)].astype(int)
    mapped=packed_index[:,0]+packed_index[:,1]*256+packed_index[:,2]*65536
    # Column zero is the hidden/dummy vertex, so the packed index is used directly.
    column=np.clip(mapped,0,position.m_Width-1)
    values=positions[frame,column];xy=values[:,:2] if group else values[:,2:]
    xy=xy*(maximum-minimum)+minimum
    packed=colors[frame,np.clip(column,0,color.m_Width-1)]
    alpha=((packed & 15) if group else (packed >> 4)).astype(float)/15
    # No costume is selected. The shader hides costume/alternate-atlas attachments.
    alpha[(uv1[:,1]>=.5)|(uv[:,0]>=1.5)]=0
    alpha[mapped==0]=0
    return xy,alpha


def extract(capture,out=RUNTIME/'art',catalog_path=ROOT/'runtime/tata/research/wechat-catalog-content.bin',force=False):
    UnityPy.config.FALLBACK_UNITY_VERSION='2022.3.62f3'
    catalog=Catalog();locations=parse(Path(catalog_path).read_bytes())
    files={p.name:p for root in discover_tata_caches() for p in root.rglob('*.bundle')}
    out.mkdir(parents=True,exist_ok=True);exported=[];missing=[];errors=[]
    for pet in capture['pets']:
        uid,evolution=pet['tid'],pet['evoTID'];res=catalog.resource(uid,evolution)
        target=out/f'battle_idle_{uid}_{evolution}.png'
        if target.is_file() and not force:continue
        deps=locations.get(res.get('Prefab',''),[])
        paths=[files[Path(dep.split('?')[0]).name] for dep in deps if Path(dep.split('?')[0]).name in files]
        if not paths:missing.append(uid);continue
        try:
            env=UnityPy.load(*[str(p) for p in paths])
            materials=[o.read() for o in env.objects if o.type.name=='Material']
            textures=[o for o in env.objects if o.type.name=='Texture2D']
            puppet=res['Puppet'].replace('_','').lower()
            atlases=[o for o in textures if (o.peek_name() or '').replace('_','').lower()=='spine'+puppet]
            meshes=[o for o in env.objects if o.type.name=='Mesh']
            if not atlases or not meshes:missing.append(uid);continue
            # The prefab's main mesh hash is preferred over auxiliary meshes.
            mesh_hash=None;animation=None;animation_index=None
            for obj in env.objects:
                if obj.type.name=='MonoBehaviour':
                    tree=obj.read_typetree()
                    if tree.get('gpuAnimData'):
                        animation_index=next((i for i,a in enumerate(tree['gpuAnimData']) if a['name']=='Idle'),None)
                        animation=tree['gpuAnimData'][animation_index] if animation_index is not None else None
                        if animation:mesh_hash=str(animation['meshHash']);break
            if animation is None:raise ValueError('Idle animation metadata missing')
            mesh=next((m for m in meshes if mesh_hash and mesh_hash in (m.peek_name() or '')),meshes[0])
            position=next(o.read() for o in textures if (o.peek_name() or '').endswith('_position_all'))
            color=next(o.read() for o in textures if (o.peek_name() or '').endswith('_color_all'))
            index_texture=next(o.read() for o in textures if (o.peek_name() or '').endswith('_vertexidx_all'))
            props=next(m for m in materials if 'gpu_spine_' in m.m_Name).m_SavedProperties
            values=dict(props.m_Floats)
            xy,alpha=idle_pose(mesh.read(),position,color,index_texture,animation,animation_index,values['minUnitRange'],values['maxUnitRange'])
            image=rasterize(mesh.read(),atlases[0].read().image,vertices=xy,vertex_alpha=alpha);image.save(target)
            exported.append(dict(unit_id=uid,evolution=evolution,file=target.name,pose='Idle',frame=animation['startFrame'],
                bundles=[dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]))
        except Exception as exc:errors.append(dict(unit_id=uid,error=str(exc)))
        print(f'unit={uid} exported={len(exported)} missing={len(missing)} errors={len(errors)}',flush=True)
    report=dict(exported=exported,missing=missing,errors=errors,animated=False)
    write_json(out/'battle-art-report.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture',type=Path,default=RUNTIME/'live-capture.json')
    p.add_argument('--force',action='store_true')
    a=p.parse_args();extract(read_json(a.capture),force=a.force)
