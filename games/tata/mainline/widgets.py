"""Image-first roster cards and a map board using the game's local extracted art."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageOps, ImageDraw, ImageChops

from model import RUNTIME, ELEMENTS
from policy import slots_for
from rules import grid_areas, rectangle_slots, star_icons, evolution_gate

BG = '#211e39'
PANEL = '#302b4d'
TEXT = '#f7f4ff'
MUTED = '#b9b3cf'
ACCENT = '#b7eb43'


class ScrollArea(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); self.canvas.pack(side='left', fill='both', expand=True)
        self.body = ttk.Frame(self.canvas)
        window = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        self.body.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(window, width=e.width))


class Art:
    def __init__(self, root):
        self.root, self.cache = root, {}

    def path(self, reference):
        name = Path(reference).stem
        for directory in ('art', 'icons'):
            p = RUNTIME/directory/(name+'.png')
            if p.is_file():
                return p
        return None

    def image(self, reference, width, height, stretch=False, crop=None, circle=False):
        path = self.path(reference)
        if path is None:
            return None
        key = (str(path), max(1, int(width)), max(1, int(height)), stretch,crop,circle)
        if key not in self.cache:
            with Image.open(path) as raw:
                image = raw.convert('RGBA')
                if crop:image=image.crop(tuple(round(v*(image.width if i%2==0 else image.height)) for i,v in enumerate(crop)))
                size = key[1:3]
                image = image.resize(size, Image.Resampling.LANCZOS) if stretch else ImageOps.contain(image, size, Image.Resampling.LANCZOS)
                if circle:
                    image=ImageOps.fit(image,size,Image.Resampling.LANCZOS)
                    mask=Image.new('L',size);ImageDraw.Draw(mask).ellipse((0,0,size[0]-1,size[1]-1),fill=255)
                    image.putalpha(ImageChops.multiply(image.getchannel('A'),mask))
                self.cache[key] = ImageTk.PhotoImage(image, master=self.root)
        return self.cache[key]

    def dimensions(self,reference):
        path=self.path(reference)
        if path:
            with Image.open(path) as raw:return raw.size
        return 1334,1875


def draw_stars(canvas, app, x, y, stars, width=120, size=20):
    if stars is None:
        canvas.create_text(x,y,text='星级待确认',fill=MUTED,font=('Microsoft YaHei UI',8)); return
    ids=star_icons(stars,app.catalog.star_grade)
    if not ids:
        canvas.create_text(x,y,text='未升星',fill=MUTED,font=('Microsoft YaHei UI',8)); return
    step=min(size,width/len(ids))
    for i,icon_id in enumerate(ids):
        image=app.art.image(app.catalog.star_resources[str(icon_id)]['IconName'],step,step)
        if image: canvas.create_image(x+(i-(len(ids)-1)/2)*step,y,image=image)
        else: canvas.create_text(x+(i-(len(ids)-1)/2)*step,y,text='?',fill=MUTED)


class StarPicker(tk.Toplevel):
    def __init__(self,app,uid,evolution,callback):
        super().__init__(app.root)
        self.title('按原游戏星级图案选择'); self.configure(bg=BG)
        self.geometry('740x560'); self.transient(app.root)
        self.grab_set()
        gate=evolution_gate(app.catalog,uid,evolution)
        tip=f'本形态最低星级编号 {gate["minimum"]}'
        if gate['next_threshold'] is not None: tip+=f'；下次进化门槛 {gate["next_threshold"]}，还需考虑进化试炼'
        ttk.Label(self,text=tip,wraplength=700).pack(pady=8)
        def select(stars): callback(stars); self.destroy()
        ttk.Button(self,text='还没确认，暂留空',command=lambda:select(None)).pack(pady=4)
        current=app.current_star()
        expanded=tk.BooleanVar(value=bool(gate['can_wait_for_trial'] and current is not None and current>gate['normal_max']))
        scroll=ScrollArea(self); scroll.pack(fill='both',expand=True,padx=8,pady=8)
        def draw():
            for child in scroll.body.winfo_children():child.destroy()
            maximum=app.catalog.max_star if expanded.get() else gate['normal_max']
            for i,stars in enumerate(range(gate['minimum'],maximum+1)):
                card=tk.Canvas(scroll.body,width=222,height=65,bg=PANEL,highlightthickness=1,highlightbackground='#685780',cursor='hand2')
                card.grid(row=i//3,column=i%3,padx=4,pady=4)
                draw_stars(card,app,110,23,stars,160,25)
                card.create_text(110,51,text=f'图案 {stars}',fill=MUTED,font=('Microsoft YaHei UI',8))
                card.bind('<Button-1>',lambda _,v=stars:select(v))
                card.bind('<MouseWheel>',lambda e:scroll.canvas.yview_scroll(-int(e.delta/120),'units'))
            scroll.canvas.yview_moveto(0)
        if gate['can_wait_for_trial']:
            ttk.Checkbutton(self,text='已达到门槛但试炼尚未完成：显示更高星级',variable=expanded,command=draw).pack(before=scroll)
        draw()


class Gallery(ttk.Frame):
    def __init__(self, parent, app, battle=False):
        super().__init__(parent)
        self.app, self.battle, self.regions = app, battle, []
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y'); self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda _: self.draw())
        self.canvas.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-int(e.delta/120), 'units'))
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.pressed = None

    def hit(self, x, y):
        y = self.canvas.canvasy(y)
        return next(((uid, box) for uid, box in self.regions if box[0] <= x < box[2] and box[1] <= y < box[3]), None)

    def draw(self):
        c, app = self.canvas, self.app
        c.delete('all'); self.regions = []
        ids = app.visible_ids(battle=self.battle)
        width = max(c.winfo_width(), 140)
        columns = max(1, width//134)
        card_width = min(150, (width-12)/columns-10)
        card_height = card_width+92
        owned = {p['unit_id']: p for p in app.pets}
        for index, uid in enumerate(ids):
            x = 6+(index % columns)*(card_width+10)
            y = 8+(index//columns)*(card_height+10)
            box = (x, y, x+card_width, y+card_height)
            self.regions.append((uid, box))
            pet = owned.get(uid, dict(unit_id=uid, evolution=1, stars=0))
            unit = app.catalog.pets[str(uid)]
            quality = app.catalog.qualities.get(str(app.catalog.quality(pet)), {})
            color = quality.get('Color', '#8f5ae2')
            selected = uid == app.selected_id
            c.create_rectangle(*box, fill='#171329', outline=ACCENT if selected else '#0c0b15', width=3)
            c.create_rectangle(x+3, y+3, x+card_width-3, y+card_width+10, fill=color, outline='')
            frame = app.art.image(quality.get('IconName', ''), card_width-4, card_width+16, stretch=True)
            if frame:
                c.create_image(x+card_width/2, y+card_width/2+8, image=frame)
            portrait = app.art.image(app.catalog.resource(uid, pet['evolution']).get('IconName', ''), card_width-10, card_width-10)
            if portrait:
                c.create_image(x+card_width/2, y+card_width/2+9, image=portrait)
            else:
                c.create_text(x+card_width/2, y+card_width/2, text='头像待补齐', fill=TEXT)
            for offset, table, key in [(0, app.catalog.elements, 'UnitElement'), (28, app.catalog.careers, 'UnitCareer')]:
                info = table.get(str(unit.get(key)), {})
                image = app.art.image(info.get('IconName', ''), 24, 24)
                if image:
                    c.create_image(x+16, y+18+offset, image=image)
            c.create_rectangle(x+card_width-59, y+5, x+card_width-5, y+24, fill='#241f3c', outline='')
            c.create_text(x+card_width-9, y+14, text=f'Lv.{app.level.get()}', anchor='e', fill='white', font=('Microsoft YaHei UI', 8, 'bold'))
            c.create_text(x+card_width/2, y+card_width+16, text=app.catalog.name(uid, pet['evolution']), fill=TEXT, font=('Microsoft YaHei UI', 9, 'bold'), width=card_width-6)
            if uid in owned:
                draw_stars(c,app,x+card_width/2,y+card_width+39,pet['stars'],card_width-8,20)
                ranks=pet.get('attribute_ranks',{})
                label=' · '.join(f'{n}{ranks.get(k) or "?"}' for k,n in [('ATK','攻'),('DEF','防'),('HP','生')])
            else: label='未拥有'
            c.create_text(x+card_width/2, y+card_height-29, text=label, fill=MUTED, font=('Microsoft YaHei UI', 8))
            if self.battle:
                deployed = uid in app.placements.values()
                label = '✓ 已上阵' if deployed else '拖到地图上阵'
            else:
                label = '✓ 已拥有  ·  点击移出' if uid in owned else '＋ 收入角色池'
            c.create_rectangle(x+3, y+card_height-19, x+card_width-3, y+card_height-2,
                               fill='#436127' if uid in owned else '#48405f', outline='')
            c.create_text(x+card_width/2, y+card_height-10, text=label, fill=TEXT, font=('Microsoft YaHei UI', 8))
        c.configure(scrollregion=(0, 0, width, max(1, ((len(ids)+columns-1)//columns)*(card_height+10)+10)))
        if not ids:
            c.create_text(width/2, 80, text='没有符合筛选条件的塔塔' if not self.battle else '角色池为空，请先在图鉴中点「收入角色池」', fill=MUTED, width=width-30)

    def press(self, event):
        self.pressed = self.hit(event.x, event.y)
        self.start = (event.x_root, event.y_root)
        self.dragging = False

    def motion(self, event):
        if not self.battle or not self.pressed:
            return
        if not self.dragging and abs(event.x_root-self.start[0])+abs(event.y_root-self.start[1]) > 7:
            self.dragging = True
            self.app.begin_drag(self.pressed[0])
        if self.dragging:
            self.app.drag_at(event.x_root, event.y_root)

    def release(self, event):
        if not self.pressed:
            return
        uid, box = self.pressed
        if self.dragging:
            self.app.finish_drag(event.x_root, event.y_root)
        else:
            self.app.select_pet(uid)
            if not self.battle and self.canvas.canvasy(event.y) >= box[3]-21:
                self.app.guard(lambda: self.app.toggle_owned(uid))
        self.pressed = None


class BattleBoard(tk.Canvas):
    def __init__(self, parent, app):
        super().__init__(parent, bg='#171329', highlightthickness=0)
        self.app, self.regions, self.dragged = app, {}, None
        self.bind('<Configure>', lambda _: self.draw())
        self.bind('<ButtonPress-1>', self.press)
        self.bind('<B1-Motion>', self.motion)
        self.bind('<ButtonRelease-1>', self.release)
        self.bind('<Button-3>', self.remove)
        self.bind('<Motion>',self.hover)

    def rounded(self,box,radius=10,**options):
        x1,y1,x2,y2=box;r=min(radius,(x2-x1)/2,(y2-y1)/2)
        return self.create_polygon(x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,x2,y2-r,x2,y2,
            x2-r,y2,x1+r,y2,x1,y2,x1,y2-r,x1,y1+r,x1,y1,smooth=True,**options)

    def element(self,unit,x,y,size):
        element=unit.get('UnitElement',1);info=self.app.catalog.elements.get(str(element),{})
        icon=self.app.art.image(info.get('IconName',''),size,size)
        if icon:self.create_image(x,y,image=icon)
        else:
            self.create_oval(x-size/2,y-size/2,x+size/2,y+size/2,fill='#7c7686',outline='#201e2d',width=2)
            self.create_text(x,y,text=ELEMENTS.get(element,'?'),fill='white',font=('Microsoft YaHei UI',max(6,int(size*.35))))

    def hover(self,event):
        enemy=next((uid for box,uid in getattr(self,'enemy_regions',[]) if box[0]<=event.x<=box[2] and box[1]<=event.y<=box[3]),None)
        if enemy is None:return
        unit=self.app.stage_data['enemy_units'][str(enemy)];element=unit.get('UnitElement',1)
        info=self.app.catalog.elements.get(str(element),{})
        self.app.status.set(f'{self.app.catalog.name(enemy)} · {ELEMENTS.get(element,"无")}元素 · '
            f'克制{ELEMENTS.get(info.get("CounterElement"),"无")}，被{ELEMENTS.get(info.get("WeakElement"),"无")}克制')

    def hit(self, root_x, root_y):
        x, y = root_x-self.winfo_rootx(), root_y-self.winfo_rooty()
        return next((slot for slot, r in self.regions.items() if r[0] <= x < r[2] and r[1] <= y < r[3]), None)

    def draw(self):
        app=self.app;self.delete('all');self.regions={};self.enemy_regions=[]
        if app.stage_data is None:return
        width,height=max(self.winfo_width(),200),max(self.winfo_height(),300)
        resource=app.catalog.battle_resources.get(str(app.stage_data['battle'].get('ResID')),{})
        reference=resource.get('BackgroundRes','')
        # The game shows a cropped camera viewport rather than the whole tall map.
        crop=(0,.18,1,.94);rw,rh=app.art.dimensions(reference);ratio=rw/(rh*(crop[3]-crop[1]))
        mw=min(width,(height-32)*ratio);mh=mw/ratio;left=(width-mw)/2
        background=app.art.image(reference,mw,mh,stretch=True,crop=crop)
        if background:self.create_image(width/2,mh/2,image=background)
        else:self.create_rectangle(left,0,left+mw,mh,fill='#645143',outline='')
        title_w=mw*.29;title_y=mh*.037
        self.rounded((width/2-title_w/2,title_y-12,width/2+title_w/2,title_y+12),8,fill='#242335',outline='black',width=2)
        self.create_text(width/2,title_y,text=app.stage_data['stage']['DisplayName'],fill='white',font=('Microsoft YaHei UI',11,'bold'))
        areas=grid_areas(app.stage_data);field,deploy=areas['field'],areas['deploy']
        groups={x:[] for x in range(field['x'],field['x']+field['width'])}
        for _,event in sorted(app.stage_data['waves'].get('Frame',{}).items(),key=lambda kv:int(kv[0])):
            for wave in event.get('Waves',{}).values():
                for col in wave.get('Cols',{}).values():
                    enemy=wave['EnemyID']
                    if col in groups and enemy not in groups[col]:groups[col].append(enemy)
        pw=mw*.64;pl=width/2-pw/2;pt=mh*.085;thumb=min(mw*.067,pw/max(5,field['width'])-.5)
        rows=max(3,max(map(len,groups.values()),default=0));ph=25+rows*(thumb+3)
        self.rounded((pl,pt,pl+pw,pt+ph),10,fill='#fffef8',outline='#191828',width=2)
        level=app.stage_data['battle']['MonsterLevel'].get('1','?')
        self.create_text(width/2,pt+11,text=f'敌人等级：{level}',fill='#171523',font=('Microsoft YaHei UI',9,'bold'))
        for col,enemies in groups.items():
            cx=pl+(col-field['x']+.5)*pw/field['width'];lane_w=pw/field['width']*.88
            self.rounded((cx-lane_w/2,pt+22,cx+lane_w/2,pt+ph-5),8,fill='#e5e0f2',outline='')
            for i,enemy in enumerate(enemies):
                cy=pt+24+thumb/2+i*(thumb+3)
                self.create_oval(cx-thumb/2-1,cy-thumb/2-1,cx+thumb/2+1,cy+thumb/2+1,fill='white',outline='#201f2e',width=1)
                icon=app.art.image(app.catalog.resource(enemy).get('IconName',''),thumb,thumb,circle=True)
                if icon:self.create_image(cx,cy,image=icon)
                else:self.create_text(cx,cy,text=str(enemy),font=('Arial',6))
                unit=app.stage_data['enemy_units'][str(enemy)]
                self.element(unit,cx+thumb*.36,cy-thumb*.37,thumb*.46)
                self.enemy_regions.append(((cx-thumb/2,cy-thumb/2,cx+thumb/2,cy+thumb/2),enemy))
        cell=mw*.114;baseline=mh*.80;center=width/2
        show_grid=getattr(app,'show_grid',None)
        show_grid=(show_grid.get() if show_grid is not None else False) or app.drag_id is not None
        for x,y in slots_for(app.stage_data):
            cx=center+(x-3)*cell;cy=baseline-(y-1)*cell
            box=(cx-cell*.48,cy-cell*.48,cx+cell*.48,cy+cell*.48)
            self.regions[(x,y)]=box
            if show_grid:
                self.rounded(box,5,fill='',outline='#f8eac0',width=1,dash=(3,3))
                if (x,y) not in app.placements:self.create_text(cx,cy,text='+',fill='#f4ebca')
        frame=getattr(app,'replay_frame',None)
        if frame:
            actors=frame['units']
        else:
            actors=[dict(tid=uid,x=x,y=y,camp=1,evolution=next(p['evolution'] for p in app.pets if p['unit_id']==uid))
                    for (x,y),uid in app.placements.items()]
        for actor in sorted(actors,key=lambda a:-a['y']):
            uid,evo=actor['tid'],actor['evolution'];cx=center+(actor['x']-3)*cell;cy=baseline-(actor['y']-1)*cell
            if cy<pt+ph+cell*.2 or cy>mh:continue
            unit=app.catalog.units.get(str(uid),{})
            body=f'battle_idle_{uid}_{evo}.png'
            image=app.art.image(body,cell*1.12,cell*1.22)
            if image is None:image=app.art.image(app.catalog.resource(uid,evo).get('IconName',''),cell*.98,cell*.98)
            self.create_oval(cx-cell*.32,cy+cell*.24,cx+cell*.32,cy+cell*.4,fill='#665536',outline='',stipple='gray50')
            if image:self.create_image(cx,cy,image=image)
            else:self.create_text(cx,cy,text=str(uid),fill='white')
            self.element(unit,cx-cell*.36,cy-cell*.39,max(9,cell*.28))
            if 'hp' in actor:
                hp=max(0,min(1,actor['hp']/max(1,actor['max_hp'])))
                self.create_rectangle(cx-cell*.4,cy+cell*.42,cx+cell*.4,cy+cell*.49,fill='#271f37',outline='')
                self.create_rectangle(cx-cell*.4,cy+cell*.42,cx-cell*.4+cell*.8*hp,cy+cell*.49,
                    fill='#76db5e' if actor['camp']==1 else '#ec625e',outline='')
        self.rounded((left+4,mh-20,left+mw-4,mh+12),6,fill='#232237',outline='')
        text=f'上阵塔塔：{len(app.placements)}/{app.stage_data["waves"]["CanDeployNum"]}'
        if frame:text=f'本地模拟回放  {frame["time"]:.1f}s'
        self.create_text(left+14,mh-4,text=text,anchor='w',fill='white',font=('Microsoft YaHei UI',10,'bold'))

    def press(self, event):
        self.dragged = self.hit(event.x_root, event.y_root)
        self.started = False; self.start = (event.x_root, event.y_root)

    def motion(self, event):
        uid = self.app.placements.get(self.dragged)
        if uid and not self.started and abs(event.x_root-self.start[0])+abs(event.y_root-self.start[1]) > 7:
            self.started = True; self.app.begin_drag(uid)
        if self.started:
            self.app.drag_at(event.x_root, event.y_root)

    def release(self, event):
        if self.started:
            self.app.finish_drag(event.x_root, event.y_root)
        elif self.dragged is not None and self.app.selected_id is not None:
            self.app.guard(lambda: self.app.place(self.app.selected_id, self.dragged))
        self.dragged = None

    def remove(self, event):
        slot = self.hit(event.x_root, event.y_root)
        uid = self.app.placements.get(slot)
        if uid:
            self.app.guard(lambda: self.app.place(uid, None))
