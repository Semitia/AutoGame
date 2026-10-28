"""Image-first roster cards and a map board using the game's local extracted art."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageOps

from model import RUNTIME, ELEMENTS
from policy import slots_for

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

    def image(self, reference, width, height, stretch=False):
        path = self.path(reference)
        if path is None:
            return None
        key = (str(path), max(1, int(width)), max(1, int(height)), stretch)
        if key not in self.cache:
            with Image.open(path) as raw:
                image = raw.convert('RGBA')
                size = key[1:3]
                image = image.resize(size, Image.Resampling.LANCZOS) if stretch else ImageOps.contain(image, size, Image.Resampling.LANCZOS)
                self.cache[key] = ImageTk.PhotoImage(image, master=self.root)
        return self.cache[key]


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
        card_height = card_width+70
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
            label = f'★ {pet["stars"]}  ·  进化 {pet["evolution"]}' if uid in owned else '未拥有'
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

    def hit(self, root_x, root_y):
        x, y = root_x-self.winfo_rootx(), root_y-self.winfo_rooty()
        return next((slot for slot, r in self.regions.items() if r[0] <= x < r[2] and r[1] <= y < r[3]), None)

    def draw(self):
        app = self.app; self.delete('all'); self.regions = {}
        if app.stage_data is None:
            return
        width, height = max(self.winfo_width(), 200), max(self.winfo_height(), 300)
        map_width = min(width, height*1334/1875)
        left = (width-map_width)/2
        height = map_width*1875/1334
        resource = app.catalog.battle_resources.get(str(app.stage_data['battle'].get('ResID')), {})
        reference = resource.get('BackgroundRes', '')
        background = app.art.image(reference, map_width, height, stretch=True)
        if background:
            self.create_image(width/2, height/2, image=background)
        else:
            self.create_rectangle(left, 0, left+map_width, height, fill='#393250', outline='')
            self.create_text(width/2, height*.35, text='本章地图贴图尚未下载\n保留实际格子与布阵约束', fill=MUTED, justify='center')
        self.create_rectangle(left+10, 8, left+map_width-10, 43, fill='#211e39', outline='#7a6a9b', width=2)
        self.create_text(width/2, 26, text=f'{app.stage_data["stage"]["DisplayName"]}   敌人等级 {app.stage_data["battle"]["MonsterLevel"].get("1", "?")}', fill=TEXT, font=('Microsoft YaHei UI', 11, 'bold'))
        columns = app.stage_data['waves']['ColumnCount']
        groups = {x: [] for x in range(1, columns+1)}
        for event in app.stage_data['waves'].get('Frame', {}).values():
            for wave in event.get('Waves', {}).values():
                enemy = str(wave['EnemyID'])
                for column in wave.get('Cols', {}).values():
                    if column in groups and enemy not in groups[column]:
                        groups[column].append(enemy)
        panel_left, panel_width = left+map_width*.16, map_width*.68
        self.create_rectangle(panel_left, 49, panel_left+panel_width, 165, fill='#f0edf8', outline='#332c4d', width=2)
        self.create_text(width/2, 60, text='各列可能出现的敌人', fill='#332c4d', font=('Microsoft YaHei UI', 8))
        thumb = min(28, panel_width/columns-6)
        for column, enemies in groups.items():
            for i, enemy in enumerate(enemies[:3]):
                x = panel_left+(column-.5)*panel_width/columns
                y = 82+i*29
                icon = app.art.image(app.catalog.resource(enemy).get('IconName', ''), thumb, thumb)
                if icon:
                    self.create_image(x, y, image=icon)
                else:
                    self.create_text(x, y, text=enemy, fill='#332c4d', font=('Microsoft YaHei UI', 7))
            if len(enemies) > 3:
                self.create_text(panel_left+(column-.5)*panel_width/columns, 154,
                                 text=f'+{len(enemies)-3}', fill='#332c4d', font=('Microsoft YaHei UI', 7))
        try:
            slots = slots_for(app.stage_data)
        except ValueError as exc:
            self.create_text(width/2, height*.6, text=str(exc), fill=TEXT, width=map_width-30); return
        columns = app.stage_data['waves']['ColumnCount']
        cell = map_width*.43/columns
        center_x = width/2
        baseline = height*.78
        # Presentation coordinates on the original texture; logical x/y remain unchanged.
        for x, y in slots:
            cx = center_x+(x-(columns+1)/2)*cell
            cy = baseline-(y-1)*cell
            r = (cx-cell*.48, cy-cell*.48, cx+cell*.48, cy+cell*.48)
            self.regions[(x, y)] = r
            self.create_rectangle(*r, outline='#d6ebad', width=1, dash=(3, 3), fill='', tags='slot')
            uid = app.placements.get((x, y))
            if uid:
                pet = next(p for p in app.pets if p['unit_id'] == uid)
                image = app.art.image(app.catalog.resource(uid, pet['evolution']).get('IconName', ''), cell*1.05, cell*1.05)
                if image:
                    self.create_image(cx, cy-3, image=image)
                else:
                    self.create_text(cx, cy, text=app.catalog.name(uid), fill='white', width=cell)
            else:
                self.create_text(cx, cy, text='+', fill='#e6f5c8', font=('Microsoft YaHei UI', 15))
        self.create_rectangle(left+8, height-44, left+map_width-8, height-8, fill='#211e39', outline='#6a6086')
        self.create_text(width/2, height-26, text=f'上阵塔塔：{len(app.placements)} / {app.stage_data["waves"]["CanDeployNum"]}   ·   右键下阵', fill=TEXT)

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
