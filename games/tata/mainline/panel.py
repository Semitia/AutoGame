"""Image-first Tata roster and drag/drop map workbench using local game art."""
import argparse
from pathlib import Path
import tkinter as tk
import subprocess,sys,json
import uuid
from tkinter import ttk, filedialog, messagebox, simpledialog
from model import (Catalog, DATA, DATASET, RUNTIME, load_roster, snapshot, write_json,
                   validate_pet, filtered_pets, shared_level_value, SharedLevelConflict)
from formation import move_unit
from policy import recommend
from rules import evolution_gate,feed_candidates
from widgets import Art, Gallery, BattleBoard, ScrollArea, StarPicker, draw_stars, BG, PANEL, TEXT, MUTED, ACCENT


class MainlinePanel:
    def __init__(self, root, catalog, state=RUNTIME/'roster.json', initial_stage='1-1'):
        self.root, self.catalog, self.state = root, catalog, Path(state)
        self.pets, self.placements, self.candidates = [], {}, []
        self.selected_id, self.stage_data, self.ghost, self.drag_id = None, None, None, None
        self.plan_mode, self.notes, self.read_error = 'manual', '', False
        self.initial_stage=initial_stage;self.replay_frame=None;self.replay_index=0;self.replay_playing=False
        self.current_report=None;self.show_grid=tk.BooleanVar(value=False);self.search_budget=tk.StringVar(value='120')
        root.title('Tata · 图鉴与地图布阵'); root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW',self.close)
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
        sync_bar=ttk.Frame(root,padding=(18,0,18,8));sync_bar.pack(fill='x')
        self.live_button=ttk.Button(sync_bar,text='从已登录游戏同步',command=lambda:self.guard(self.sync_live))
        self.live_button.pack(side='left',padx=(0,8))
        self.sync_button=ttk.Button(sync_bar,text='同步本机资源',command=lambda:self.guard(self.sync_art))
        self.sync_button.pack(side='left',padx=(0,12))
        ttk.Label(sync_bar,text='电脑微信登录后可直接读取角色池；游戏可放后台或最小化。',foreground=MUTED).pack(side='left')
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
        toolbar=ttk.Frame(parent); toolbar.pack(fill='x',pady=(0,8)); self.stage_query=tk.StringVar(value=self.initial_stage)
        ttk.Label(toolbar,text='关卡').pack(side='left')
        entry=ttk.Entry(toolbar,textvariable=self.stage_query,width=12); entry.pack(side='left',padx=6)
        entry.bind('<Return>',lambda _:self.guard(self.load_stage))
        ttk.Button(toolbar,text='加载',command=lambda:self.guard(self.load_stage)).pack(side='left')
        ttk.Button(toolbar,text='旧启发式候选',command=lambda:self.guard(self.plan)).pack(side='left',padx=6)
        self.candidate_box=ttk.Combobox(toolbar,state='readonly',width=18); self.candidate_box.pack(side='left')
        self.candidate_box.bind('<<ComboboxSelected>>',lambda _:self.choose_candidate(self.candidate_box.current()))
        ttk.Button(toolbar,text='保存布阵',command=lambda:self.guard(self.save_plan)).pack(side='right')
        ttk.Button(toolbar,text='清空',command=self.clear_board).pack(side='right',padx=6)
        actions=ttk.Frame(parent);actions.pack(fill='x',pady=(0,8))
        self.sim_button=ttk.Button(actions,text='模拟当前布阵',command=lambda:self.guard(lambda:self.run_local(False)))
        self.sim_button.pack(side='left',padx=(0,6))
        self.search_button=ttk.Button(actions,text='经验搜索阵容',command=lambda:self.guard(lambda:self.run_local(True)))
        self.search_button.pack(side='left',padx=(0,6))
        ttk.Label(actions,text='预算').pack(side='left');ttk.Entry(actions,textvariable=self.search_budget,width=5).pack(side='left',padx=(4,10))
        ttk.Button(actions,text='打开模拟方案',command=lambda:self.guard(self.open_simulation)).pack(side='left',padx=5)
        ttk.Button(actions,text='播放 / 暂停回放',command=lambda:self.guard(self.toggle_replay)).pack(side='left',padx=5)
        ttk.Checkbutton(actions,text='显示布阵格',variable=self.show_grid,command=lambda:self.board.draw()).pack(side='left',padx=8)
        learning=ttk.Frame(parent);learning.pack(fill='x',pady=(0,6))
        self.learning_status=tk.StringVar(value='搜索自动复用本机经验；玩家攻略是弱先验，按当前角色池重新模拟。')
        ttk.Label(learning,textvariable=self.learning_status,style='Hint.TLabel').pack(side='left')
        ttk.Button(learning,text='记实战未通过',command=lambda:self.guard(lambda:self.record_battle_feedback(False))).pack(side='right')
        ttk.Button(learning,text='记实战通过',command=lambda:self.guard(lambda:self.record_battle_feedback(True))).pack(side='right',padx=6)
        auto=ttk.Frame(parent);auto.pack(fill='x',pady=(0,6))
        self.autoplay_count=tk.StringVar(value='5')
        ttk.Button(auto,text='自动布阵并推关',command=lambda:self.guard(self.start_autoplay)).pack(side='left')
        ttk.Label(auto,text='最多推进').pack(side='left',padx=(10,4))
        ttk.Spinbox(auto,from_=1,to=100,textvariable=self.autoplay_count,width=4).pack(side='left')
        ttk.Label(auto,text='关；保持游戏前台，F8 随时停止',style='Hint.TLabel').pack(side='left',padx=6)
        ttk.Button(auto,text='停止自动推关',command=self.stop_autoplay).pack(side='right')
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
        self.replay_playing=False;self.replay_frame=None;self.current_report=None
        self.placements={}; self.candidates=[]; self.plan_mode='manual'
        self.candidate_box['values']=[]; self.candidate_box.set(''); self.refresh()
    def place(self,uid,target):
        self.replay_playing=False;self.replay_frame=None;self.current_report=None
        self.placements=move_unit(self.stage_data,self.pets,self.placements,uid,target)
        self.plan_mode='manual'; self.refresh(); self.status.set('已调整布阵 · 未模拟战斗；可保存本地方案')
    def begin_drag(self,uid):
        self.drag_id=uid; self.select_pet(uid)
        self.board.draw()
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
        self.plan_mode=candidate['mode'];self.replay_frame=None;self.replay_playing=False
        if candidate.get('simulated'):
            v=candidate['evaluation'];validation=candidate.get('validation',[])
            text=f'原始 Lua 模拟：{"通过" if v["won"] else "未通过"}，击杀 {v["kills"]}/{v["total_enemies"]}，{v["battle_secs"]:.1f}s。'
            if validation:text+=f'独立种子通过 {sum(x["won"] for x in validation)}/{len(validation)}。'
            explanations=candidate.get('explanations',[])
            self.reason.set(text+'待实战校准；不是通关保证。'+ ('\n'+'\n'.join(explanations) if explanations else ''))
        else:self.reason.set('候选偏好分不是胜率；位置尚未优化，可拖动调整。星级、属性评级与技能暂未参与评分。')
        self.refresh()
    def save_plan(self):
        if not self.placements: raise ValueError('请先拖入塔塔或生成候选')
        path=filedialog.asksaveasfilename(title='保存布阵',defaultextension='.json',initialfile=f'plan-{self.stage_data["stage"]["ID"]}.json')
        if path:
            write_json(path,dict(schema_version=3,simulated=bool(self.current_report),calibrated=False,simulation=self.current_report,
                stage_id=self.stage_data['stage']['ID'],data_version='apk-0.50.1',policy=self.plan_mode,
                roster=snapshot(self.pets,self.catalog,self.notes,shared_level=self.level.get()),placements=[dict(unit_id=v,x=k[0],y=k[1]) for k,v in self.placements.items()]))
            self.status.set('已保存布阵：'+path)

    def run_local(self,search):
        if getattr(self,'autoplay_process',None) is not None and self.autoplay_process.poll() is None:raise ValueError('请先停止自动推关')
        if getattr(self,'combat_process',None) is not None and self.combat_process.poll() is None:return
        if not search and not self.placements:raise ValueError('请先摆放阵容')
        budget=int(self.search_budget.get())
        if not 4<=budget<=10000:raise ValueError('搜索预算应为 4–10000 个候选')
        rows=[];stamps=set()
        for pet in self.pets:
            observed=pet.get('game_observed',{})
            if any(observed.get(k)!=v for k,v in [('tid',pet['unit_id']),('evoTID',pet['evolution']),('starLv',pet['stars']),('level',int(self.level.get()))]):
                raise ValueError('角色池已被手动修改或缺少游戏观测，请先从已登录游戏同步')
            stamps.add(observed['captured_at']);rows.append({k:v for k,v in observed.items() if k!='captured_at'})
        if len(stamps)!=1:raise ValueError('角色池观测时间不一致，请重新同步')
        capture=dict(schema_version=1,source='wechat-webgl-memory',captured_at=next(iter(stamps)),shared_level=int(self.level.get()),pets=rows)
        from combat import pet_proto
        for row in rows:pet_proto(row)
        self.replay_playing=False;self.replay_frame=None
        job=RUNTIME/'simulations'/uuid.uuid4().hex;job.mkdir(parents=True,exist_ok=True)
        write_json(job/'capture.json',capture)
        self.combat_output=job/'result.json';self.combat_log=(job/'run.log').open('w',encoding='utf-8')
        script='search_policy.py' if search else 'combat.py'
        args=[sys.executable,'-X','utf8',str(Path(__file__).with_name(script)),
              '--capture',str(job/'capture.json'),'--stage',str(self.stage_data['stage']['ID']),'--out',str(self.combat_output)]
        if search:
            args+=['--budget',str(budget)]
            if self.placements:
                write_json(job/'plan.json',dict(placements=[dict(unit_id=uid,x=x,y=y) for (x,y),uid in self.placements.items()]))
                args+=['--initial',str(job/'plan.json')]
        else:
            write_json(job/'plan.json',dict(placements=[dict(unit_id=uid,x=x,y=y) for (x,y),uid in self.placements.items()]))
            args+=['--plan',str(job/'plan.json')]
        self.combat_input=(self.stage_data['stage']['ID'],self.level.get(),json.dumps(self.pets,sort_keys=True))
        try:self.combat_process=subprocess.Popen(args,stdout=self.combat_log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except Exception:self.combat_log.close();raise
        self.sim_button.configure(state='disabled');self.search_button.configure(state='disabled')
        self.status.set('正在本地执行原始战斗逻辑…');self.root.after(500,self.poll_combat)

    def poll_combat(self):
        progress=self.combat_output.with_suffix('.progress.json')
        if self.combat_process.poll() is None:
            if progress.is_file():
                try:
                    p=json.loads(progress.read_text(encoding='utf-8'));v=p['evaluation']
                    self.status.set(f'本地搜索 {p["evaluated"]}/{p["budget"]} · 最佳击杀 {v["kills"]}/{v["total_enemies"]}'+(' · 模拟通过' if v['won'] else ''))
                except (ValueError,OSError,KeyError):pass
            self.root.after(500,self.poll_combat);return
        self.combat_log.close();self.sim_button.configure(state='normal');self.search_button.configure(state='normal')
        if self.combat_process.returncode:
            detail=(self.combat_output.parent/'run.log').read_text(encoding='utf-8')
            self.status.set('模拟未完成，布阵未改动；日志：'+str(self.combat_output.parent/'run.log'))
            messagebox.showerror('模拟未完成',detail[-1800:],parent=self.root);return
        current=(self.stage_data['stage']['ID'],self.level.get(),json.dumps(self.pets,sort_keys=True))
        if current!=self.combat_input:
            self.status.set('模拟已保存，期间关卡或角色池发生变化；请用“打开模拟方案”查看。');return
        self.guard(lambda:self.load_simulation(self.combat_output))

    def open_simulation(self):
        path=filedialog.askopenfilename(title='打开模拟结果',initialdir=RUNTIME,filetypes=[('模拟结果 JSON','*.json')])
        if path:self.load_simulation(path)

    def load_simulation(self,path):
        from model import read_json
        report=read_json(path)
        if report.get('simulated') is not True or not isinstance(report.get('evaluation'),dict):raise ValueError('不是模拟结果文件')
        stage=self.catalog.stage(report['stage_id']);board={}
        for p in report['placements']:board=move_unit(stage,self.pets,board,p['unit_id'],(p['x'],p['y']))
        self.stage_query.set(str(report['stage_id']));self.load_stage()
        mode=report.get('mode','original-lua-simulation')
        candidates=report.get('finalists') or [dict(placements=report['placements'],evaluation=report['evaluation'],score=report['evaluation']['score'],explanations=report.get('explanations',[]))]
        self.candidates=[dict(c,mode=mode,simulated=True) for c in candidates]
        self.candidate_box['values']=[f'模拟候选 {i+1}' for i in range(len(candidates))]
        self.candidate_box.current(0);self.choose_candidate(0)
        self.current_report=report;self.replay_index=0
        memory=report.get('experience',{});stats=memory.get('after',{})
        if memory.get('enabled'):
            self.learning_status.set(f'本机经验 {stats.get("battles",0)} 局 · 偏好学习 {stats.get("preference_updates",0)} 对 · 本次复用 {len(memory.get("retrieved",[]))} 个历史方案')
        else:self.learning_status.set('此方案未启用持久学习；仍可查看模拟结果。')
        self.status.set('已载入模拟方案与回放。待实战核对，尚未保证通关。')

    def record_battle_feedback(self,won,path=None):
        from experience import Experience,DEFAULT_PATH,stable_hash
        report=self.current_report
        if not report or not report.get('engine_fingerprint') or not report.get('context'):
            raise ValueError('请先搜索并打开新版方案，再在游戏试打后记录结果')
        if {(p['x'],p['y']):p['unit_id'] for p in report['placements']}!=self.placements:
            raise ValueError('已切换或调整阵容，请先模拟当前布阵，不能把结果记到原方案')
        rows=[]
        for pet in sorted(self.pets,key=lambda p:p['unit_id']):
            observed=pet.get('game_observed',{})
            if any(observed.get(k)!=v for k,v in [('tid',pet['unit_id']),('evoTID',pet['evolution']),('starLv',pet['stars']),('level',int(self.level.get()))]):
                raise ValueError('当前角色池已修改，请重新同步与搜索后记录')
            rows.append({k:v for k,v in observed.items() if k!='captured_at'})
        if stable_hash(rows)!=report['context']['roster_hash'] or self.stage_data['stage']['ID']!=report['stage_id']:
            raise ValueError('角色池或关卡与报告不符，请重新搜索后记录')
        memory=Experience(path or DEFAULT_PATH)
        try:memory.record_feedback(report['engine_fingerprint'],report['context_hash'],report['placements'],won)
        finally:memory.close()
        self.status.set('已记玩家实战反馈：'+('通过' if won else '未通过')+'。将影响下次历史方案选择；不会冒充模拟校准。')

    def start_autoplay(self):
        from autoplay import GEOMETRY,STOP
        if getattr(self,'autoplay_process',None) is not None and self.autoplay_process.poll() is None:return
        if getattr(self,'combat_process',None) is not None and self.combat_process.poll() is None:raise ValueError('请等待当前本地模拟完成')
        if not GEOMETRY.is_file():raise ValueError('尚无已验证的游戏窗口校准配置，请先完成自动布阵校准')
        count=int(self.autoplay_count.get());budget=int(self.search_budget.get())
        if not 1<=count<=100 or not 4<=budget<=10000:raise ValueError('关卡数1–100，搜索预算4–10000')
        STOP.unlink(missing_ok=True)
        folder=RUNTIME/'autoplay-ui'/uuid.uuid4().hex;folder.mkdir(parents=True,exist_ok=True)
        self.autoplay_run_dir=folder
        self.autoplay_log=(folder/'run.log').open('w',encoding='utf-8')
        args=[sys.executable,'-X','utf8',str(Path(__file__).with_name('autoplay.py')),'--stages',str(count),'--budget',str(budget),'--run-dir',str(folder)]
        try:self.autoplay_process=subprocess.Popen(args,stdout=self.autoplay_log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except Exception:self.autoplay_log.close();raise
        self.status.set('正在同步、模拟并自动布阵；运行时不要操作游戏，F8或点停止可结束。')
        self.root.after(500,self.poll_autoplay)

    def stop_autoplay(self):
        from autoplay import STOP
        STOP.parent.mkdir(parents=True,exist_ok=True);STOP.write_text('用户停止\n',encoding='utf-8')
        self.status.set('已发送停止请求；游戏战斗本身会继续结算，工具不再输入。')

    def close(self):
        if getattr(self,'autoplay_process',None) is not None and self.autoplay_process.poll() is None:self.stop_autoplay()
        self.replay_playing=False;self.root.destroy()

    def poll_autoplay(self):
        path=RUNTIME/'autoplay-status.json'
        if path.is_file():
            try:
                state=json.loads(path.read_text(encoding='utf-8'))
                if state.get('run_dir')==str(self.autoplay_run_dir):
                    label={'planning':'同步后复核阵容','searching':'搜索阵容','deploy':'自动布阵',
                        'deployment_verified':'整队核验通过','request_order_verified':'入场顺序复核通过','battle_started':'实战中','battle_settled':'实战已结算',
                        'preparation_ready':'下一关布阵就绪','stage_advanced':'已进入下一关','finished':'本次完成','stopped':'已停止'}
                    self.status.set(f'自动推关 · 已通过 {len(state.get("completed",[]))} 关 · {label.get(state.get("event"),state.get("event",""))} · {state.get("reason","")}')
            except (ValueError,OSError):pass
        if self.autoplay_process.poll() is None:self.root.after(500,self.poll_autoplay)
        else:
            self.autoplay_log.close()
            if self.autoplay_process.returncode:self.status.set('自动推关已停止，查看日志：'+self.autoplay_log.name)

    def toggle_replay(self):
        if not self.current_report or not self.current_report['evaluation'].get('frames'):raise ValueError('请先模拟或打开带回放的方案')
        plan={(p['x'],p['y']):p['unit_id'] for p in self.current_report['placements']}
        if plan!=self.placements:raise ValueError('此候选尚无回放，请先点“模拟当前布阵”')
        self.replay_playing=not self.replay_playing
        if self.replay_playing:self.replay_tick()

    def replay_tick(self):
        if not self.replay_playing or not self.current_report:return
        frames=self.current_report['evaluation']['frames']
        if self.replay_index>=len(frames):self.replay_index=0
        self.replay_frame=frames[self.replay_index];self.replay_index+=1;self.board.draw()
        if self.replay_index>=len(frames):self.replay_playing=False;return
        self.root.after(250,self.replay_tick)

    def sync_live(self):
        if getattr(self,'autoplay_process',None) is not None and self.autoplay_process.poll() is None:raise ValueError('自动推关会逐关同步，请先停止再编辑角色池')
        if getattr(self,'live_process',None) is not None and self.live_process.poll() is None:return
        RUNTIME.mkdir(parents=True,exist_ok=True)
        self.live_output=RUNTIME/'live-capture.json'
        self.live_log=(RUNTIME/'live-sync.log').open('w',encoding='utf-8')
        args=[sys.executable,'-X','utf8',str(Path(__file__).with_name('live_roster.py')),
              '--data',str(self.catalog.data),'--dataset',str(self.catalog.dataset),'--out',str(self.live_output)]
        try:
            self.live_process=subprocess.Popen(args,stdout=self.live_log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except Exception:
            self.live_log.close();raise
        self.live_button.configure(state='disabled')
        self.status.set('正在只读获取当前微信塔塔角色池…')
        self.root.after(300,self.poll_live)

    def apply_live_capture(self,capture):
        from live_roster import to_roster
        value=to_roster(capture,self.catalog)
        old=(self.pets,self.level.get(),self.read_error)
        notes={p['unit_id']:p.get('notes','') for p in self.pets}
        for pet in value['pets']:pet['notes']=notes.get(pet['unit_id'],'')
        try:
            self.read_error=False;self.level.set(str(value['shared_level']));self.persist(value['pets'])
        except Exception:
            self.pets,level,self.read_error=old;self.level.set(level);self.refresh();raise
        if self.selected_id is not None:self.select_pet(self.selected_id)
        self.status.set(f'同步成功：共享 Lv.{value["shared_level"]}，{len(value["pets"])} 只塔塔；原角色池已备份。')

    def poll_live(self):
        if self.live_process.poll() is None:self.root.after(300,self.poll_live);return
        self.live_log.close();self.live_button.configure(state='normal')
        if self.live_process.returncode:
            detail=(RUNTIME/'live-sync.log').read_text(encoding='utf-8').strip()
            self.status.set('同步失败，原角色池未修改：'+detail[-500:]);return
        self.guard(lambda:self.apply_live_capture(json.loads(self.live_output.read_text(encoding='utf-8'))))

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
    parser.add_argument('--stage',default='1-1');parser.add_argument('--simulation',type=Path)
    args=parser.parse_args(); root=tk.Tk()
    try:
        app=MainlinePanel(root,Catalog(args.data,args.dataset),args.state,args.stage)
        if args.simulation:app.load_simulation(args.simulation)
    except Exception as exc:
        root.withdraw(); messagebox.showerror('主线工作台未能启动',str(exc),parent=root); root.destroy(); return
    root.mainloop()


if __name__=='__main__': main()
