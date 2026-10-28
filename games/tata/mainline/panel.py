"""Local desktop workbench for manual rosters and explainable formation candidates."""
import argparse
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from model import Catalog, DATA, DATASET, RUNTIME, ELEMENTS, load_roster, snapshot, write_json
from policy import recommend, slots_for


class MainlinePanel:
    def __init__(self, root, catalog, state=RUNTIME/'roster.json'):
        self.root, self.catalog, self.state = root, catalog, Path(state)
        self.pets, self.candidates, self.placements, self.images = [], [], {}, {}
        self.plan_mode = 'manual'
        root.title('Tata · 主线布阵工作台')
        width = min(1120, root.winfo_screenwidth()-60)
        height = min(760, root.winfo_screenheight()-100)
        root.geometry(f'{width}x{height}'); root.minsize(min(980, width), min(680, height))
        style = ttk.Style(root); style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('Treeview', rowheight=30)
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 21, 'bold'), foreground='#15344d')
        style.configure('Hint.TLabel', foreground='#63758a')
        outer = ttk.Frame(root, padding=20); outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Tata 主线布阵', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='本地角色池  /  关卡数据  /  布阵候选', style='Hint.TLabel').pack(anchor='w', pady=(4, 15))
        self.status = tk.StringVar(value='手动录入后自动保存到本机。尚未连接游戏账号。')
        ttk.Label(outer, textvariable=self.status, style='Hint.TLabel', wraplength=1000).pack(side='bottom', anchor='w', pady=(10, 0))
        self.tabs = ttk.Notebook(outer); self.tabs.pack(fill='both', expand=True)
        roster = ttk.Frame(self.tabs, padding=15); stages = ttk.Frame(self.tabs, padding=15)
        self.tabs.add(roster, text='  我的角色池  '); self.tabs.add(stages, text='  关卡与布阵  ')
        self.build_roster(roster); self.build_stages(stages)
        if self.state.exists():
            try:
                self.pets = load_roster(self.state, self.catalog)['pets']
            except Exception as exc:
                messagebox.showerror('角色池读取失败', str(exc), parent=root)
        self.refresh_roster(); self.search(); self.load_stage()

    def guard(self, action):
        try:
            return action()
        except Exception as exc:
            messagebox.showerror('无法完成', str(exc), parent=self.root)

    def build_roster(self, parent):
        tools = ttk.Frame(parent); tools.pack(fill='x', pady=(0, 12))
        ttk.Label(tools, text='角色池由你录入；数据来源：APK 0.50.1。', style='Hint.TLabel').pack(side='left')
        ttk.Button(tools, text='导入 JSON', command=lambda: self.guard(self.import_roster)).pack(side='right', padx=4)
        ttk.Button(tools, text='导出 JSON', command=lambda: self.guard(self.export_roster)).pack(side='right')
        body = ttk.Frame(parent); body.pack(fill='both', expand=True)
        left = ttk.Frame(body); left.pack(side='left', fill='both', expand=True, padx=(0, 20))
        searchbar = ttk.Frame(left); searchbar.pack(fill='x')
        self.query = tk.StringVar()
        ttk.Entry(searchbar, textvariable=self.query).pack(side='left', fill='x', expand=True)
        ttk.Button(searchbar, text='搜索宠物', command=self.search).pack(side='left', padx=(8, 0))
        self.query.trace_add('write', lambda *_: self.search())
        self.catalog_box = ttk.Combobox(left, state='readonly'); self.catalog_box.pack(fill='x', pady=8)
        self.catalog_box.bind('<<ComboboxSelected>>', lambda _: self.new_pet())
        self.tree = ttk.Treeview(left, columns=('name', 'level', 'evolution', 'element'), show='headings', height=12)
        for key, label, width in [('name', '已拥有的宠物', 170), ('level', '等级', 65), ('evolution', '进化', 65), ('element', '元素', 65)]:
            self.tree.heading(key, text=label); self.tree.column(key, width=width, anchor='center')
        self.tree.pack(fill='both', expand=True); self.tree.bind('<<TreeviewSelect>>', self.select_owned)
        buttons = ttk.Frame(left); buttons.pack(fill='x', pady=10)
        ttk.Button(buttons, text='新建录入', command=self.new_pet).pack(side='left')
        ttk.Button(buttons, text='删除所选', command=lambda: self.guard(self.remove)).pack(side='left', padx=8)
        self.count = tk.StringVar(); ttk.Label(buttons, textvariable=self.count, style='Hint.TLabel').pack(side='right')
        right = ttk.LabelFrame(body, text='宠物详情', padding=14); right.pack(side='right', fill='both')
        self.portrait = ttk.Label(right, text='选择宠物', anchor='center', width=25); self.portrait.pack(pady=6)
        self.pet_title = tk.StringVar(value='从左侧选择宠物')
        ttk.Label(right, textvariable=self.pet_title, font=('Microsoft YaHei UI', 13, 'bold')).pack(pady=5)
        form = ttk.Frame(right); form.pack(fill='x')
        self.fields = {}
        for i, (key, label, default) in enumerate([('level', '等级', '1'), ('evolution', '进化阶段', '1'),
                ('stars', '星级', '0'), ('skill_level', '技能等级', '1'), ('atk', '面板攻击（选填）', ''),
                ('def', '面板防御（选填）', ''), ('hp', '面板生命（选填）', ''), ('notes', '装备 / 其他备注', '')]):
            self.fields[key] = tk.StringVar(value=default)
            ttk.Label(form, text=label).grid(row=i, column=0, sticky='w', pady=3)
            ttk.Entry(form, textvariable=self.fields[key], width=19).grid(row=i, column=1, padx=(12, 0), pady=3)
        self.evo_hint = tk.StringVar()
        ttk.Label(right, textvariable=self.evo_hint, style='Hint.TLabel', wraplength=320).pack(anchor='w', pady=8)
        ttk.Button(right, text='保存到角色池', command=lambda: self.guard(self.save_pet)).pack(fill='x', pady=5)
        ttk.Label(right, text='星级 / 技能 / 装备：仅记录，尚未参与评分。', style='Hint.TLabel', wraplength=280).pack(anchor='w', pady=4)
        self.editing_id = None

    def search(self):
        query = self.query.get().strip().casefold()
        self.filtered = [int(k) for k in sorted(self.catalog.pets, key=int)
                         if query in f'{k} {self.catalog.name(k)} {self.catalog.pets[k]["Name"]}'.casefold()]
        self.catalog_box['values'] = [f'{k} · {self.catalog.name(k)}' for k in self.filtered]
        if self.filtered:
            self.catalog_box.current(0)

    def new_pet(self):
        index = self.catalog_box.current()
        if index < 0 or index >= len(self.filtered):
            return
        self.editing_id = self.filtered[index]
        for key, value in self.fields.items():
            value.set('1' if key in ('level', 'evolution', 'skill_level') else '0' if key == 'stars' else '')
        self.update_portrait()

    def update_portrait(self):
        key = self.editing_id
        if key is None:
            return
        try:
            evolution = int(self.fields['evolution'].get())
        except ValueError:
            evolution = 1
        self.pet_title.set(f'{self.catalog.name(key, evolution)} · #{key}')
        self.evo_hint.set('可用进化阶段：'+'、'.join(sorted(self.catalog.evolutions[str(key)], key=int)))
        icon = Path(self.catalog.resource(key, evolution).get('IconName', '')).stem
        path = RUNTIME/'icons'/f'{icon}.png'
        if path.exists():
            if icon not in self.images:
                image = tk.PhotoImage(file=str(path))
                scale = max(1, (max(image.width(), image.height())+95)//96)
                self.images[icon] = image.subsample(scale)
            self.portrait.configure(image=self.images[icon], text='')
        else:
            self.portrait.configure(image='', text=f'[{ELEMENTS.get(self.catalog.pets[str(key)].get("UnitElement"), "?")}] 头像暂缺')

    def select_owned(self, _=None):
        selected = self.tree.selection()
        if not selected:
            return
        pet = next(p for p in self.pets if str(p['unit_id']) == selected[0])
        self.editing_id = pet['unit_id']
        for key, value in self.fields.items():
            value.set('' if pet.get(key) is None else str(pet[key]))
        self.update_portrait()

    def persist(self):
        value = snapshot(self.pets, self.catalog)
        write_json(self.state, value); self.pets = value['pets']
        self.candidates = []; self.placements = {}
        self.results.delete(*self.results.get_children())
        self.refresh_roster(); self.draw_board()
        self.status.set(f'已保存 {len(self.pets)} 只宠物 · {self.state}')

    def save_pet(self):
        if self.editing_id is None:
            raise ValueError('请先在宠物目录中选择一只宠物')
        from model import validate_pet
        pet = validate_pet(dict(unit_id=self.editing_id, **{k: v.get() for k, v in self.fields.items()}), self.catalog)
        old = self.pets
        self.pets = [p for p in old if p['unit_id'] != self.editing_id] + [pet]
        try:
            self.persist()
        except Exception:
            self.pets = old
            raise
        self.update_portrait()

    def remove(self):
        selected = self.tree.selection()
        if selected:
            old = self.pets
            self.pets = [p for p in old if str(p['unit_id']) != selected[0]]
            try:
                self.persist()
            except Exception:
                self.pets = old
                raise

    def refresh_roster(self):
        self.tree.delete(*self.tree.get_children())
        for p in sorted(self.pets, key=lambda p: p['unit_id']):
            self.tree.insert('', 'end', iid=str(p['unit_id']), values=(self.catalog.name(p['unit_id'], p['evolution']),
                p['level'], p['evolution'], ELEMENTS.get(self.catalog.pets[str(p['unit_id'])].get('UnitElement'), '?')))
        self.count.set(f'已录入 {len(self.pets)} 只')
        self.assign_ids = [p['unit_id'] for p in self.pets]
        self.assign_box['values'] = ['清空格子']+[f'{p["unit_id"]} · {self.catalog.name(p["unit_id"], p["evolution"])}' for p in self.pets]
        self.assign_box.current(0)

    def import_roster(self):
        path = filedialog.askopenfilename(title='导入角色池', filetypes=[('角色池 JSON', '*.json')])
        if path:
            value = load_roster(path, self.catalog)
            old = self.pets
            self.pets = value['pets']
            try:
                self.persist()
            except Exception:
                self.pets = old
                raise

    def export_roster(self):
        path = filedialog.asksaveasfilename(title='导出角色池', defaultextension='.json', initialfile='tata-roster.json')
        if path:
            write_json(path, snapshot(self.pets, self.catalog)); self.status.set('角色池已导出：'+path)

    def build_stages(self, parent):
        toolbar = ttk.Frame(parent); toolbar.pack(fill='x')
        ttk.Label(toolbar, text='关卡名称或编号').pack(side='left')
        self.stage_query = tk.StringVar(value='1-1')
        ttk.Entry(toolbar, textvariable=self.stage_query, width=15).pack(side='left', padx=8)
        ttk.Button(toolbar, text='加载关卡', command=lambda: self.guard(self.load_stage)).pack(side='left')
        ttk.Button(toolbar, text='生成候选', command=lambda: self.guard(self.plan)).pack(side='left', padx=8)
        ttk.Button(toolbar, text='保存当前布阵', command=lambda: self.guard(self.save_plan)).pack(side='right')
        self.stage_info = tk.StringVar()
        ttk.Label(parent, textvariable=self.stage_info, wraplength=1000).pack(anchor='w', pady=12)
        self.results = ttk.Treeview(parent, columns=('candidate', 'score', 'pets'), show='headings', height=3)
        for key, title, width in [('candidate', '候选', 80), ('score', '偏好分', 90), ('pets', '宠物选择', 720)]:
            self.results.heading(key, text=title); self.results.column(key, width=width)
        self.results.pack(fill='x'); self.results.bind('<<TreeviewSelect>>', self.choose_candidate)
        controls = ttk.Frame(parent); controls.pack(fill='x', pady=12)
        ttk.Label(controls, text='手动布阵：选择宠物，再点格子').pack(side='left')
        self.assign_box = ttk.Combobox(controls, state='readonly', width=30); self.assign_box.pack(side='left', padx=8)
        self.board = ttk.Frame(parent); self.board.pack(fill='x')
        self.details = tk.Text(parent, height=9, wrap='word', relief='flat', padx=10, pady=10, font=('Microsoft YaHei UI', 10))
        self.details.pack(fill='both', expand=True, pady=(12, 0)); self.details.configure(state='disabled')
        self.stage_data = None

    def explain(self, text):
        self.details.configure(state='normal'); self.details.delete('1.0', 'end')
        self.details.insert('end', text); self.details.configure(state='disabled')

    def load_stage(self):
        query = self.stage_query.get().strip()
        row = next((s for s in self.catalog.stages if s['name'] == query), None)
        key = row['id'] if row else query
        data = self.catalog.stage(key)
        self.stage_data = data; self.candidates = []; self.placements = {}
        self.results.delete(*self.results.get_children())
        summary = self.catalog.stage_index[str(data['stage']['ID'])]
        enemies = '、'.join(f'{self.catalog.name(k)} ×{v}' for k, v in summary['enemies'].items())
        self.stage_info.set(f'{data["stage"]["DisplayName"]}  ·  最多 {summary["deploy_limit"]} 只  ·  出怪 {summary["enemy_count"]} 只\n{enemies}')
        self.draw_board()
        self.explain('当前为启发式候选 v0：按稀有度、等级和敌人元素覆盖选宠物，未模拟战斗。\n位置可手动调整；未给出伤害或通关率。\n关卡列表来自 APK 配置，可能含当前未开放关卡。')

    def draw_board(self):
        for child in self.board.winfo_children():
            child.destroy()
        if self.stage_data is None:
            return
        try:
            slots = slots_for(self.stage_data)
        except ValueError as exc:
            ttk.Label(self.board, text=str(exc)).pack(); return
        rows = sorted({y for _, y in slots})
        for x, y in slots:
            key = (x, y); unit_id = self.placements.get(key)
            text = self.catalog.name(unit_id) if unit_id else '＋ 空位'
            ttk.Button(self.board, text=f'{text}\n({x}, {y})', command=lambda k=key: self.guard(lambda: self.place(k))).grid(
                row=rows.index(y), column=x-1, padx=4, pady=4, sticky='nsew', ipady=9)
            self.board.columnconfigure(x-1, weight=1)

    def place(self, slot):
        index = self.assign_box.current()
        if index <= 0:
            self.placements.pop(slot, None)
        else:
            unit_id = self.assign_ids[index-1]
            allowed = set(self.stage_data['waves'].get('CanUsePetIDs', {}).values())
            if allowed and unit_id not in allowed:
                raise ValueError('此宠物不符合该关卡的限制')
            previous = next((k for k, v in self.placements.items() if v == unit_id), None)
            if slot not in self.placements and previous is None and len(self.placements) >= self.stage_data['waves']['CanDeployNum']:
                raise ValueError('超过关卡上阵数量限制')
            if previous:
                self.placements.pop(previous)
            self.placements[slot] = unit_id
        self.draw_board()
        self.plan_mode = 'manual'
        self.explain('当前为手动布阵，未模拟战斗。保存时会附带角色池快照。')

    def plan(self):
        if self.stage_data is None:
            raise ValueError('请先加载关卡')
        self.candidates = recommend(self.catalog, self.stage_data, self.pets)
        self.results.delete(*self.results.get_children())
        for i, candidate in enumerate(self.candidates):
            names = '、'.join(self.catalog.name(p['unit_id']) for p in candidate['placements'])
            self.results.insert('', 'end', iid=str(i), values=(f'候选 {i+1}', candidate['score'], names))
        self.results.selection_set('0'); self.choose_candidate()
        self.status.set('已生成启发式候选；位置顺序填充，尚未模拟战斗。')

    def choose_candidate(self, _=None):
        selected = self.results.selection()
        if not selected or not self.candidates:
            return
        candidate = self.candidates[int(selected[0])]
        self.plan_mode = candidate['mode']
        self.placements = {(p['x'], p['y']): p['unit_id'] for p in candidate['placements']}
        self.draw_board()
        self.explain('\n'.join(f'{self.catalog.name(k)}：{v}' for k, v in candidate['reasons'].items())+'\n\n'+'；'.join(candidate['limitations']))

    def save_plan(self):
        if not self.placements:
            raise ValueError('请先生成候选或手动布阵')
        path = filedialog.asksaveasfilename(title='保存布阵', initialdir=str(RUNTIME), defaultextension='.json', initialfile=f'plan-{self.stage_data["stage"]["ID"]}.json')
        if path:
            write_json(path, dict(schema_version=1, simulated=False, stage_id=self.stage_data['stage']['ID'],
                data_version='apk-0.50.1', policy=self.plan_mode, roster=snapshot(self.pets, self.catalog),
                placements=[dict(unit_id=v, x=k[0], y=k[1]) for k, v in self.placements.items()]))
            self.status.set('布阵已保存：'+path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=DATA)
    parser.add_argument('--dataset', type=Path, default=DATASET)
    parser.add_argument('--state', type=Path, default=RUNTIME/'roster.json')
    args = parser.parse_args()
    root = tk.Tk()
    try:
        MainlinePanel(root, Catalog(args.data, args.dataset), args.state)
    except Exception as exc:
        root.withdraw()
        messagebox.showerror('主线数据尚未准备', f'{exc}\n\n请先按 games/tata/mainline/README.md 导出本地配置与关卡数据。', parent=root)
        root.destroy(); return
    root.mainloop()


if __name__ == '__main__':
    main()
