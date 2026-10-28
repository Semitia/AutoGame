"""Image-first Tata roster and drag/drop map workbench using local game art."""
import argparse
from pathlib import Path
import tkinter as tk
import subprocess,sys,json
from tkinter import ttk, filedialog, messagebox, simpledialog
from model import (Catalog, DATA, DATASET, RUNTIME, load_roster, snapshot, write_json,
                   validate_pet, filtered_pets, shared_level_value, SharedLevelConflict)
from formation import move_unit
from policy import recommend
from rules import evolution_gate,feed_candidates
from widgets import Art, Gallery, BattleBoard, ScrollArea, StarPicker, draw_stars, BG, PANEL, TEXT, MUTED, ACCENT


class MainlinePanel:
    def __init__(self, root, catalog, state=RUNTIME/'roster.json'):
        self.root, self.catalog, self.state = root, catalog, Path(state)
        self.pets, self.placements, self.candidates = [], {}, []
        self.selected_id, self.stage_data, self.ghost, self.drag_id = None, None, None, None
        self.plan_mode, self.notes, self.read_error = 'manual', '', False
        root.title('Tata · 图鉴与地图布阵'); root.configure(bg=BG)
        width, height = min(1280,root.winfo_screenwidth()-70), min(820,root.winfo_screenheight()-100)
        root.geometry(f'{width}x{height}'); root.minsize(min(1050,width),min(660,height))
        self.level = tk.StringVar(value='1'); self.query = tk.StringVar()
        self.status = tk.StringVar(value='点图片编辑；卡片底部切换拥有。所有塔塔共享等级。')
        self.element = self.career = None; self.owned_only = tk.BooleanVar(value=False)
        if self.state.exists():
            try:
                value = self.read_profile(self.state)
                self.pets, self.notes = value['pets'],value['notes']; self.level.set(str(value['shared_level']))
            except Exception as exc:
                self.read_error = True; self.status.set(f'角色池未载入，原文件已保留：{exc}')
        self.art = Art(root); self.style()
        header = ttk.Frame(root,padding=(18,12)); header.pack(fill='x')
        ttk.Label(header,text='TATA / 主线工作台',style='Title.TLabel').pack(side='left')
        for text, action in [('导入角色池',self.import_roster),('导出',self.export_roster),('保存等级',self.save_level)]:
            ttk.Button(header,text=text,command=lambda f=action:self.guard(f)).pack(side='right',padx=5)
        entry = ttk.Entry(header,textvariable=self.level,width=7); entry.pack(side='right')
        entry.bind('<Return>',lambda _:self.guard(self.save_level))
        ttk.Label(header,text='共享等级 Lv. ').pack(side='right')
        self.sync_button=ttk.Button(header,text='同步本机资源',command=lambda:self.guard(self.sync_art))
        self.sync_button.pack(side='right',padx=6)
        ttk.Label(root,textvariable=self.status,style='Hint.TLabel',wraplength=1100,padding=(18,9)).pack(side='bottom',fill='x')
        self.tabs = ttk.Notebook(root); self.tabs.pack(fill='both',expand=True,padx=12)
        roster, battle = ttk.Frame(self.tabs,padding=8),ttk.Frame(self.tabs,padding=8)
        self.tabs.add(roster,text='  塔塔图鉴 / 角色池  '); self.tabs.add(battle,text='  地图布阵  ')
        self.filters(roster,True)
        content = ttk.Frame(roster); content.pack(fill='both',expand=True,pady=(8,0))
        self.gallery = Gallery(content,self); self.gallery.pack(side='left',fill='both',expand=True,padx=(0,12))
        editor_host = ttk.Frame(content,width=290); editor_host.pack(side='right',fill='y'); editor_host.pack_propagate(False)
        self.editor_actions=ttk.Frame(editor_host,padding=(0,6));self.editor_actions.pack(side='bottom',fill='x')
        editor_scroll = ScrollArea(editor_host); editor_scroll.pack(fill='both',expand=True)
        self.editor = editor_scroll.body
        self.build_editor(); self.build_battle(battle)
        self.query.trace_add('write',lambda *_:self.refresh())
        self.level.trace_add('write',lambda *_:self.refresh_cards())
        self.load_stage(); self.refresh()

    def style(self):
        s=ttk.Style(self.root); s.theme_use('clam')
        s.configure('.',font=('Microsoft YaHei UI',10),background=BG,foreground=TEXT)
        for widget in ('TFrame','TLabel','TCheckbutton'): s.configure(widget,background=BG,foreground=TEXT)
        s.configure('Title.TLabel',font=('Microsoft YaHei UI',17,'bold'),foreground=ACCENT)
        s.configure('Hint.TLabel',foreground=MUTED)
        s.configure('TButton',background=PANEL,foreground=TEXT,padding=(8,6),bordercolor='#595070')
        s.map('TButton',background=[('active','#5a4c78')])
        s.configure('Active.TButton',background='#486321',foreground='#efffc8')
        s.configure('TEntry',fieldbackground='#fcfbff',foreground='#201b35')
        s.configure('TCombobox',fieldbackground='#fcfbff',foreground='#201b35')
        s.map('TCombobox',fieldbackground=[('readonly','#fcfbff')],foreground=[('readonly','#201b35')])
        s.configure('TNotebook',background=BG,borderwidth=0)
        s.configure('TNotebook.Tab',background=PANEL,foreground=MUTED,padding=(16,8))
        s.map('TNotebook.Tab',background=[('selected','#554377')],foreground=[('selected','white')])

    def guard(self, action):
        try: return action()
        except Exception as exc:
            self.status.set(str(exc)); messagebox.showerror('无法完成',str(exc),parent=self.root)

    def read_profile(self, path):
        try:
            return load_roster(path,self.catalog)
        except SharedLevelConflict as exc:
            level = simpledialog.askinteger('迁移旧角色池',
                f'旧版记录了不同等级：{exc.levels}\n所有塔塔共享等级，请填实际等级：',
                minvalue=1,maxvalue=100000,parent=self.root)
            if level is None:
                raise ValueError('已取消等级确认，原角色池未改动') from None
            return load_roster(path,self.catalog,shared_level_override=level)

    def filters(self,parent,owned_toggle=False):
        box=ttk.Frame(parent); box.pack(fill='x')
        top=ttk.Frame(box); top.pack(fill='x',pady=3)
        ttk.Label(top,text='找塔塔  ').pack(side='left')
        ttk.Entry(top,textvariable=self.query,width=21).pack(side='left')
        ttk.Button(top,text='重置筛选',command=self.reset_filters).pack(side='left',padx=8)
        if owned_toggle: ttk.Checkbutton(top,text='只看已拥有',variable=self.owned_only,command=self.refresh).pack(side='left')
        for label,table,kind in [('职业',self.catalog.careers,'career'),('元素',self.catalog.elements,'element')]:
            row=ttk.Frame(box); row.pack(fill='x',pady=2)
            ttk.Label(row,text=label+'  ').pack(side='left')
            ttk.Button(row,text='全部',width=4,command=lambda k=kind:self.set_filter(k,None)).pack(side='left',padx=2)
            for key,info in sorted(table.items(),key=lambda kv:int(kv[0])):
                name=info.get('ShowName') or {2:'水',3:'火',4:'草',5:'电',6:'岩'}.get(int(key),key)
                icon=self.art.image(info.get('IconName',''),22,22)
                button=ttk.Button(row,text=name,width=4,image=icon or '',compound='left',command=lambda k=kind,v=int(key):self.set_filter(k,v))
                button.pack(side='left',padx=2)
                if not hasattr(self,'filter_buttons'): self.filter_buttons=[]
                self.filter_buttons.append((button,kind,int(key)))

    def set_filter(self,kind,value): setattr(self,kind,value); self.refresh()
    def reset_filters(self):
        self.element=self.career=None; self.query.set(''); self.owned_only.set(False); self.refresh()
    def visible_ids(self,battle=False):
        return filtered_pets(self.catalog,self.pets,self.query.get(),self.element,self.career,battle or self.owned_only.get())
    def refresh_cards(self):
        for name in ('gallery','battle_gallery'):
            if hasattr(self,name): getattr(self,name).draw()
    def refresh(self):
        self.refresh_cards()
        if hasattr(self,'board'): self.board.draw()
        for button,kind,value in getattr(self,'filter_buttons',[]):
            button.configure(style='Active.TButton' if getattr(self,kind)==value else 'TButton')
        if hasattr(self,'roster_count'): self.roster_count.set(f'已拥有 {len(self.pets)} / {len(self.catalog.pets)} 种塔塔')

    def build_editor(self):
        self.roster_count=tk.StringVar(); ttk.Label(self.editor,textvariable=self.roster_count,foreground=ACCENT).pack(anchor='w')
        self.portrait=ttk.Label(self.editor,anchor='center'); self.portrait.pack(pady=8)
        self.pet_title=tk.StringVar(value='点击左侧塔塔图片')
        ttk.Label(self.editor,textvariable=self.pet_title,font=('Microsoft YaHei UI',13,'bold')).pack()
        self.pet_subtitle=tk.StringVar(value='所有塔塔使用顶部共享等级')
        ttk.Label(self.editor,textvariable=self.pet_subtitle,style='Hint.TLabel',wraplength=250).pack(pady=6)
        self.forms=ttk.Frame(self.editor); self.forms.pack(fill='x',pady=8)
        self.fields={k:tk.StringVar(value=v) for k,v in [('evolution','1'),('stars','0'),('skill_level','1'),('notes','')]}
        self.star_preview=tk.Canvas(self.editor,width=245,height=36,bg=BG,highlightthickness=0);self.star_preview.pack()
        ttk.Button(self.editor,text='按星星 / 月亮图案选星级',command=self.pick_star).pack(fill='x',pady=4)
        self.star_rule=tk.StringVar();ttk.Label(self.editor,textvariable=self.star_rule,style='Hint.TLabel',wraplength=245).pack()
        form=ttk.Frame(self.editor); form.pack(fill='x')
        self.rank_vars={};self.rank_boxes={};self.rank_icons={}
        for i,(attr,title) in enumerate([('ATK','攻击评级'),('DEF','防御评级'),('HP','生命评级')]):
            ttk.Label(form,text=title).grid(row=i,column=0,sticky='w',pady=4)
            self.rank_vars[attr]=tk.StringVar(value='未知')
            box=ttk.Combobox(form,textvariable=self.rank_vars[attr],width=8,state='readonly')
            box.grid(row=i,column=1,padx=5);box.bind('<<ComboboxSelected>>',lambda _:self.update_growth())
            self.rank_boxes[attr]=box
            icon=ttk.Label(form);icon.grid(row=i,column=2);self.rank_icons[attr]=icon
        self.growth_info=tk.StringVar();ttk.Label(self.editor,textvariable=self.growth_info,style='Hint.TLabel',wraplength=245).pack(pady=6)
        for i,(key,title) in enumerate([('skill_level','技能等级'),('notes','装备 / 备注')],start=3):
            ttk.Label(form,text=title).grid(row=i,column=0,sticky='w',pady=4)
            ttk.Entry(form,textvariable=self.fields[key],width=13).grid(row=i,column=1,columnspan=2,padx=(5,0),pady=4)
        ttk.Button(self.editor_actions,text='收入角色池 / 保存修改',command=lambda:self.guard(self.save_pet)).pack(fill='x',pady=(4,4))
        ttk.Button(self.editor_actions,text='从角色池移出',command=lambda:self.guard(lambda:self.toggle_owned(self.selected_id,True))).pack(fill='x')
        ttk.Label(self.editor,text='点形态图片切换阶段；星级按原图选择。\n字母评级只限定可能的养成状态，\n不会猜算成精确属性数值。',style='Hint.TLabel',wraplength=245).pack(anchor='w',pady=10)

    def select_pet(self,uid):
        self.selected_id=uid
        pet=next((p for p in self.pets if p['unit_id']==uid),dict(unit_id=uid,evolution=1,stars=0,skill_level=1))
        for key,value in self.fields.items(): value.set('' if pet.get(key) is None else str(pet[key]))
        for key,value in self.rank_vars.items():value.set(pet.get('attribute_ranks',{}).get(key) or '未知')
        for child in self.forms.winfo_children(): child.destroy()
        for e in sorted(self.catalog.evolutions[str(uid)],key=int):
            icon=self.art.image(self.catalog.resource(uid,int(e)).get('IconName',''),42,42)
            ttk.Button(self.forms,text=e,width=4,image=icon or '',compound='top',command=lambda evo=e:self.set_evolution(evo)).pack(side='left',padx=2)
        self.update_portrait(); self.refresh_cards()
    def set_evolution(self,evolution):
        self.fields['evolution'].set(str(evolution))
        gate=evolution_gate(self.catalog,self.selected_id,int(evolution))
        stars=self.current_star()
        if stars is not None and (stars<gate['minimum'] or (not gate['can_wait_for_trial'] and stars>gate['normal_max'])):
            self.fields['stars'].set('')
            self.status.set('已切换形态，请按实际图案重新选择星级；未自动猜测星级')
        self.update_portrait()

    def current_star(self):
        value=self.fields['stars'].get()
        return int(value) if value else None

    def pick_star(self):
        if self.selected_id is not None:
            StarPicker(self,self.selected_id,int(self.fields['evolution'].get()),self.set_star)

    def set_star(self,stars):
        self.fields['stars'].set('' if stars is None else str(stars));self.update_growth()

    def update_growth(self):
        if self.selected_id is None:return
        stars=self.current_star()
        self.star_preview.delete('all');draw_stars(self.star_preview,self,122,18,stars,210,29)
        gate=evolution_gate(self.catalog,self.selected_id,int(self.fields['evolution'].get()))
        text=f'本形态最低：{gate["minimum"]}；'
        text+=f'下一进化门槛：{gate["next_threshold"]}' if gate['next_threshold'] is not None else '当前为最终形态'
        if gate['can_wait_for_trial']:text+='（还需进化试炼）'
        self.star_rule.set(text)
        possible=feed_candidates(self.catalog,self.selected_id,stars)
        ordered=sorted(self.catalog.feed_ranks.values(),key=lambda r:r['RankID'])
        ratings={k:None if v.get()=='未知' else v.get() for k,v in self.rank_vars.items()}
        for attr,box in self.rank_boxes.items():
            values={row['ranks'][attr] for row in possible}
            box['values']=['未知']+[r['RankName'] for r in ordered if r['RankName'] in values]
            row=next((r for r in ordered if r['RankName']==ratings[attr]),{})
            image=self.art.image(row.get('Icon',''),24,24)
            self.rank_icons[attr].configure(image=image or '',text='' if image else '?')
        matches=feed_candidates(self.catalog,self.selected_id,stars,ratings)
        self.growth_info.set('符合游戏养成配置；未知评级可以保留为空。' if matches else '此评级组合与当前星级/塔塔不匹配，请核对原游戏。')
    def update_portrait(self):
        uid=self.selected_id
        if uid is None: return
        evolution=int(self.fields['evolution'].get())
        image=self.art.image(self.catalog.resource(uid,evolution).get('IconName',''),110,110)
        self.portrait.configure(image=image or '',text='' if image else '头像尚缺')
        self.pet_title.set(self.catalog.name(uid,evolution))
        unit=self.catalog.pets[str(uid)]; career=self.catalog.careers.get(str(unit.get('UnitCareer')),{}).get('ShowName','')
        self.pet_subtitle.set(f'编号 {uid} · {career} · 形态 {evolution} · 共享 Lv.{self.level.get()}')
        self.update_growth()

    def persist(self,pets=None):
        if self.read_error: raise ValueError('原角色池读取失败，已禁止覆盖；请修正原文件或导入有效角色池')
        value=snapshot(self.pets if pets is None else pets,self.catalog,self.notes,shared_level=self.level.get())
        if self.state.exists(): self.state.with_suffix('.previous.json').write_bytes(self.state.read_bytes())
        write_json(self.state,value); self.pets=value['pets']
        ids={p['unit_id'] for p in self.pets}; self.placements={k:v for k,v in self.placements.items() if v in ids}
        self.candidates=[]
        if hasattr(self,'candidate_box'): self.candidate_box['values']=[]; self.candidate_box.set('')
        self.refresh(); self.status.set(f'已保存：共享 Lv.{value["shared_level"]}，角色池 {len(self.pets)} 只')
    def save_level(self): shared_level_value(self.level.get()); self.persist(); self.update_portrait()
    def save_pet(self):
        if self.selected_id is None: raise ValueError('请先点击一张塔塔卡片')
        base=next((dict(p) for p in self.pets if p['unit_id']==self.selected_id),{})
        base.update(unit_id=self.selected_id,**{k:v.get() for k,v in self.fields.items()},
                    attribute_ranks={k:None if v.get()=='未知' else v.get() for k,v in self.rank_vars.items()})
        pet=validate_pet(base,self.catalog)
        self.persist([p for p in self.pets if p['unit_id']!=self.selected_id]+[pet])
    def toggle_owned(self,uid,remove_only=False):
        if uid is None: return
        owned=any(p['unit_id']==uid for p in self.pets)
        if owned: self.persist([p for p in self.pets if p['unit_id']!=uid])
        elif not remove_only: self.persist(self.pets+[validate_pet(dict(unit_id=uid),self.catalog)])
        self.select_pet(uid)
    def import_roster(self):
        path=filedialog.askopenfilename(title='导入角色池',filetypes=[('角色池 JSON','*.json')])
        if not path: return
        value=self.read_profile(path); old=(self.pets,self.notes,self.level.get(),self.read_error)
        try:
            self.read_error=False; self.notes=value['notes']; self.level.set(str(value['shared_level'])); self.persist(value['pets'])
        except Exception:
            self.pets,self.notes,level,self.read_error=old; self.level.set(level); self.refresh(); raise
    def export_roster(self):
        path=filedialog.asksaveasfilename(title='导出角色池',defaultextension='.json',initialfile='tata-roster.json')
        if path: write_json(path,snapshot(self.pets,self.catalog,self.notes,shared_level=self.level.get())); self.status.set('已导出：'+path)

    def build_battle(self,parent):
        toolbar=ttk.Frame(parent); toolbar.pack(fill='x',pady=(0,8)); self.stage_query=tk.StringVar(value='1-1')
        ttk.Label(toolbar,text='关卡').pack(side='left')
        entry=ttk.Entry(toolbar,textvariable=self.stage_query,width=12); entry.pack(side='left',padx=6)
        entry.bind('<Return>',lambda _:self.guard(self.load_stage))
        ttk.Button(toolbar,text='加载',command=lambda:self.guard(self.load_stage)).pack(side='left')
        ttk.Button(toolbar,text='一键候选',command=lambda:self.guard(self.plan)).pack(side='left',padx=6)
        self.candidate_box=ttk.Combobox(toolbar,state='readonly',width=18); self.candidate_box.pack(side='left')
        self.candidate_box.bind('<<ComboboxSelected>>',lambda _:self.choose_candidate(self.candidate_box.current()))
        ttk.Button(toolbar,text='保存布阵',command=lambda:self.guard(self.save_plan)).pack(side='right')
        ttk.Button(toolbar,text='清空',command=self.clear_board).pack(side='right',padx=6)
        content=ttk.Frame(parent); content.pack(fill='both',expand=True)
        left=ttk.Frame(content); left.pack(side='left',fill='both',expand=True,padx=(0,10)); self.filters(left)
        ttk.Label(left,text='拖卡片上阵 · 地图内拖动交换位置 · 拖回卡片区下阵',foreground=ACCENT).pack(anchor='w',pady=8)
        self.battle_gallery=Gallery(left,self,True); self.battle_gallery.pack(fill='both',expand=True)
        self.reason=tk.StringVar(value='启发式候选未模拟战斗，位置顺序填充。')
        ttk.Label(left,textvariable=self.reason,style='Hint.TLabel',wraplength=590).pack(fill='x',pady=6)
        right=ttk.Frame(content,width=440); right.pack(side='right',fill='both'); right.pack_propagate(False)
        self.board=BattleBoard(right,self); self.board.pack(fill='both',expand=True)
    def load_stage(self):
        query=self.stage_query.get().strip(); row=next((s for s in self.catalog.stages if s['name']==query),None)
        self.stage_data=self.catalog.stage(row['id'] if row else query); self.clear_board()
        reference=self.catalog.battle_resources.get(str(self.stage_data['battle'].get('ResID')),{}).get('BackgroundRes','')
        if not self.read_error:
            self.status.set('已载入原地图与关卡约束' if self.art.path(reference) else '关卡数据已载入；此章贴图未包含在本地资源中')
    def clear_board(self):
        self.placements={}; self.candidates=[]; self.plan_mode='manual'
        self.candidate_box['values']=[]; self.candidate_box.set(''); self.refresh()
    def place(self,uid,target):
        self.placements=move_unit(self.stage_data,self.pets,self.placements,uid,target)
        self.plan_mode='manual'; self.refresh(); self.status.set('已调整布阵 · 未模拟战斗；可保存本地方案')
    def begin_drag(self,uid):
        self.drag_id=uid; self.select_pet(uid)
        self.ghost=tk.Toplevel(self.root); self.ghost.overrideredirect(True); self.ghost.attributes('-topmost',True)
        pet=next(p for p in self.pets if p['unit_id']==uid)
        image=self.art.image(self.catalog.resource(uid,pet['evolution']).get('IconName',''),72,72)
        tk.Label(self.ghost,image=image or '',text='' if image else self.catalog.name(uid),bg=PANEL).pack()
    def drag_at(self,x,y):
        if self.ghost: self.ghost.geometry(f'+{x+18}+{y+18}')
    def finish_drag(self,x,y):
        if self.ghost: self.ghost.destroy(); self.ghost=None
        uid,self.drag_id=self.drag_id,None
        if uid is None: return
        target=self.board.hit(x,y); g=self.battle_gallery
        over_gallery=g.winfo_rootx()<=x<g.winfo_rootx()+g.winfo_width() and g.winfo_rooty()<=y<g.winfo_rooty()+g.winfo_height()
        if target is not None or over_gallery:
            try: self.place(uid,target)
            except ValueError as exc: self.status.set(str(exc))
    def plan(self):
        self.candidates=recommend(self.catalog,self.stage_data,self.pets)
        self.candidate_box['values']=[f'候选 {i+1} · {c["score"]}' for i,c in enumerate(self.candidates)]
        self.candidate_box.current(0); self.choose_candidate(0)
    def choose_candidate(self,index):
        if not 0<=index<len(self.candidates): return
        candidate=self.candidates[index]; self.placements={(p['x'],p['y']):p['unit_id'] for p in candidate['placements']}
        self.plan_mode=candidate['mode']
        self.reason.set('候选偏好分不是胜率；位置尚未优化，可拖动调整。星级、属性评级与技能暂未参与评分。')
        self.refresh()
    def save_plan(self):
        if not self.placements: raise ValueError('请先拖入塔塔或生成候选')
        path=filedialog.asksaveasfilename(title='保存布阵',defaultextension='.json',initialfile=f'plan-{self.stage_data["stage"]["ID"]}.json')
        if path:
            write_json(path,dict(schema_version=3,simulated=False,stage_id=self.stage_data['stage']['ID'],data_version='apk-0.50.1',policy=self.plan_mode,
                roster=snapshot(self.pets,self.catalog,self.notes,shared_level=self.level.get()),placements=[dict(unit_id=v,x=k[0],y=k[1]) for k,v in self.placements.items()]))
            self.status.set('已保存布阵：'+path)

    def sync_art(self):
        from extract_cached_art import discover_tata_caches
        caches=discover_tata_caches()
        if not caches:raise ValueError('未找到这台电脑上的塔塔小游戏资源缓存')
        RUNTIME.mkdir(parents=True,exist_ok=True)
        self.art_log=(RUNTIME/'art-sync.log').open('w',encoding='utf-8')
        args=[sys.executable,str(Path(__file__).with_name('extract_cached_art.py')),'--data',str(self.catalog.data),'--out',str(RUNTIME/'art')]
        for path in caches:args+=['--cache-root',str(path)]
        self.art_process=subprocess.Popen(args,stdout=self.art_log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.sync_button.configure(state='disabled');self.status.set('正在读取塔塔本机资源缓存，只提取图片…')
        self.root.after(300,self.poll_art)

    def poll_art(self):
        if self.art_process.poll() is None:self.root.after(300,self.poll_art);return
        self.art_log.close();self.sync_button.configure(state='normal');self.refresh()
        if self.art_process.returncode==0:
            report=json.loads((RUNTIME/'art/cache-art-report.json').read_text(encoding='utf-8'))
            self.status.set(f'资源同步完成：补充 {len(report["added"])} 张图片；地图与图标已刷新。'
                            +('部分文件未解析，见资源报告。' if report['errors'] else ''))
        else:self.status.set('资源读取未完成，见 runtime/tata/mainline/art-sync.log')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=DATA); parser.add_argument('--dataset',type=Path,default=DATASET)
    parser.add_argument('--state',type=Path,default=RUNTIME/'roster.json')
    args=parser.parse_args(); root=tk.Tk()
    try: MainlinePanel(root,Catalog(args.data,args.dataset),args.state)
    except Exception as exc:
        root.withdraw(); messagebox.showerror('主线工作台未能启动',str(exc),parent=root); root.destroy(); return
    root.mainloop()


if __name__=='__main__': main()
