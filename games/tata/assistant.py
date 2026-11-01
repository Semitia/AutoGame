"""One local desktop workspace for Tata mainline, fishing and hunting."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNTIME = ROOT/'runtime/tata'
BG, PANEL, TEXT, MUTED, ACCENT = '#211e39', '#302b4d', '#f7f4ff', '#b9b3cf', '#b7eb43'


def load_panel(feature):
    """The legacy panels have the same filename; give each a distinct module ID."""
    name = 'tata_' + feature + '_panel'
    if name in sys.modules:
        return sys.modules[name]
    folder = HERE/feature
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location(name, folder/'panel.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def running(owner, name):
    process = getattr(owner, name, None)
    return process is not None and process.poll() is None


class TataAssistant:
    def __init__(self, root, *, mainline_options=None):
        self.root = root
        self.mainline_options = mainline_options or {}
        self.mainline = self.fishing = self.hunting = None
        self.pages = {}
        self.closing = False
        self.current_page = None
        root.title('塔塔冒险队 · 辅助器')
        root.configure(bg=BG)
        width, height = min(1480, root.winfo_screenwidth()-60), min(940, root.winfo_screenheight()-80)
        root.geometry(f'{width}x{height}')
        root.minsize(min(1200, width), min(760, height))
        self.style()

        header = ttk.Frame(root, padding=(20, 12))
        header.pack(fill='x')
        ttk.Label(header, text='TATA / 塔塔冒险队辅助器', style='Title.TLabel').pack(side='left')
        ttk.Button(header, text='停止全部任务', command=self.stop_all).pack(side='right')
        self.activity = tk.StringVar(value='当前没有运行任务')
        ttk.Label(header, textvariable=self.activity, style='Hint.TLabel').pack(side='right', padx=18)

        body = ttk.Frame(root)
        body.pack(fill='both', expand=True)
        sidebar = ttk.Frame(body, padding=(12, 16), width=145)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text='功能', style='Hint.TLabel').pack(anchor='w', padx=8, pady=(0, 12))
        self.navigation = {}
        for key, label in [('home', '总览'), ('mainline', '主线工作台'), ('fishing', '自动钓鱼'), ('hunting', '围猎臭臭')]:
            button = ttk.Button(sidebar, text=label, command=lambda k=key: self.show(k))
            button.pack(fill='x', pady=5)
            self.navigation[key] = button
        ttk.Button(sidebar, text='打开本机数据', command=self.open_runtime).pack(side='bottom', fill='x', pady=8)
        self.host = ttk.Frame(body)
        self.host.pack(side='left', fill='both', expand=True)
        self.notice = tk.StringVar(value='选择功能开始。自动操作时保持游戏在前台，F8 可停止当前输入。')
        ttk.Label(root, textvariable=self.notice, style='Hint.TLabel', padding=(20, 10), wraplength=1200).pack(fill='x')
        self.build_home()
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.show('home')
        self.timer = root.after(250, self.poll)

    def style(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10), background=BG, foreground=TEXT)
        for widget in ('TFrame', 'TLabel', 'TCheckbutton'):
            style.configure(widget, background=BG, foreground=TEXT)
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 17, 'bold'), foreground=ACCENT)
        style.configure('Hint.TLabel', foreground=MUTED)
        style.configure('TButton', background=PANEL, foreground=TEXT, padding=(12, 9))
        style.map('TButton', background=[('active', '#5a4c78')])
        style.configure('Active.TButton', background='#486321', foreground='#efffc8')
        style.configure('Card.TFrame', background=PANEL)
        style.configure('Card.TLabel', background=PANEL)
        style.configure('CardTitle.TLabel', background=PANEL, font=('Microsoft YaHei UI', 16, 'bold'))
        style.configure('TSpinbox', fieldbackground='#fcfbff', foreground='#201b35')

    def build_home(self):
        page = ttk.Frame(self.host, padding=26)
        self.pages['home'] = page
        ttk.Label(page, text='今天想做什么？', style='Title.TLabel').pack(anchor='w', pady=(8, 12))
        ttk.Label(page, text='主线养成、钓鱼和围猎，都在一个窗口里。', style='Hint.TLabel').pack(anchor='w')
        cards = ttk.Frame(page)
        cards.pack(fill='x', pady=24)
        cards.columnconfigure((0, 1, 2), weight=1, uniform='cards')
        for col, key, title, description in [
            (0, 'mainline', '主线工作台', '账号与角色池同步\n原图图鉴、地图拖放布阵\n本地模拟、经验搜索与自动推关'),
            (1, 'fishing', '钓鱼大赛', '设置本次运行时长\n自动出杆、提钩与收取鱼获\n查看实时状态、计数与运行日志'),
            (2, 'hunting', '围猎臭臭', '低倍攒锁定，可用狂暴提速\n200倍只等萨满，锁定后跟踪\n目标结束立即退出，避免换靶'),
        ]:
            card = ttk.Frame(cards, style='Card.TFrame', padding=24)
            card.grid(row=0, column=col, sticky='nsew', padx=(0, 12) if col < 2 else 0)
            ttk.Label(card, text=title, style='CardTitle.TLabel').pack(anchor='w')
            ttk.Label(card, text=description, style='Card.TLabel', justify='left').pack(anchor='w', pady=20)
            ttk.Button(card, text='进入'+title, command=lambda k=key: self.show(k)).pack(anchor='w')
        ttk.Label(page, text='当前任务', style='Title.TLabel').pack(anchor='w', pady=(10, 12))
        self.mainline_status = tk.StringVar(value='主线：尚未打开')
        self.fishing_status = tk.StringVar(value='钓鱼：尚未打开')
        self.hunting_status = tk.StringVar(value='围猎：尚未打开')
        for variable in (self.mainline_status, self.fishing_status, self.hunting_status):
            ttk.Label(page, textvariable=variable, wraplength=920).pack(anchor='w', pady=8)
        ttk.Label(page, text='主线、钓鱼和围猎共用游戏控制权；本地阵容搜索可以与小游戏同时运行。',
                  style='Hint.TLabel', wraplength=900).pack(anchor='w', pady=20)

    def check_start(self, feature):
        if self.closing:
            raise ValueError('辅助器正在关闭，请等待任务保存并退出')
        for name,owner,process,label in [('mainline',self.mainline,'autoplay_process','自动推关'),
                ('fishing',self.fishing,'process','钓鱼'),('hunting',self.hunting,'process','围猎')]:
            if name!=feature and running(owner,process) and not getattr(owner,'observing',False) and not getattr(owner,'observe',False):
                raise ValueError(label+'正在运行，请先停止再启动其他自动操作')

    def show(self, key):
        if self.closing:
            return
        if key not in self.pages:
            page = ttk.Frame(self.host)
            self.pages[key] = page
            try:
                module = load_panel(key)
                if key == 'mainline':
                    from resources import ensure_default_resources
                    preparing = ttk.Label(page, text='正在准备主线资源…', padding=30)
                    preparing.pack()
                    page.pack(fill='both', expand=True)
                    self.root.update_idletasks()
                    ensure_default_resources()
                    preparing.destroy()
                    self.mainline = module.MainlinePanel(page, module.Catalog(), embedded=True,
                        before_autoplay=lambda: self.check_start('mainline'), **self.mainline_options)
                elif key=='hunting':
                    self.hunting=module.HuntPanel(page,embedded=True,before_start=lambda:self.check_start('hunting'))
                else:
                    controls = ttk.Frame(page, width=540)
                    controls.pack(side='left', fill='y')
                    controls.pack_propagate(False)
                    self.fishing = module.FishingPanel(controls, embedded=True,
                        before_start=lambda: self.check_start('fishing'))
                    guide = ttk.Frame(page, padding=(20, 28))
                    guide.pack(side='left', fill='both', expand=True)
                    ttk.Label(guide, text='开始前', style='Title.TLabel').pack(anchor='w', pady=(0, 16))
                    ttk.Label(guide, text='1. 在电脑微信打开塔塔冒险队。\n\n2. 进入「钓鱼大赛」。\n\n3. 设置时长，点击「开始钓鱼」。',
                              justify='left', wraplength=350).pack(anchor='w')
                    ttk.Label(guide, text='开始后保持游戏在前台。\nF8、停止钓鱼或顶部停止按钮均可停止。',
                              style='Hint.TLabel', wraplength=350).pack(anchor='w', pady=24)
            except Exception as error:
                for child in page.winfo_children():
                    child.destroy()
                ttk.Label(page, text='此功能未能加载：'+str(error), wraplength=850, padding=28).pack(anchor='w')
                ttk.Button(page, text='重新加载', command=lambda: self.retry(key)).pack(anchor='w', padx=28)
                self.notice.set('加载失败；可继续使用其他功能。')
        for page in self.pages.values():
            page.pack_forget()
        self.pages[key].pack(fill='both', expand=True)
        self.current_page = key
        for name, button in self.navigation.items():
            button.configure(style='Active.TButton' if name == key else 'TButton')

    def retry(self, key):
        self.pages.pop(key).destroy()
        self.show(key)

    def stop_all(self, *, global_signals=True):
        # Global signals also cover separately launched Tata runners.
        if global_signals:
            for path in (RUNTIME/'mainline/AUTOPLAY-STOP', RUNTIME/'fishing/STOP', RUNTIME/'hunting/STOP'):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('用户停止\n', encoding='utf-8')
        if self.mainline:
            self.mainline.stop_search()
            if running(self.mainline, 'autoplay_process'):
                self.mainline.stop_autoplay()
        if self.fishing:
            self.fishing.stop()
        if self.hunting:
            self.hunting.stop()
        self.notice.set('已请求停止。搜索完成当前模拟后保存进度；已开始的游戏战斗会继续结算。')

    def open_runtime(self):
        RUNTIME.mkdir(parents=True, exist_ok=True)
        os.startfile(RUNTIME)

    def active_jobs(self):
        jobs = []
        for name, label in [('autoplay_process', '自动推关'), ('combat_process', '本地模拟 / 搜索'),
                            ('live_process', '账号同步'), ('layout_process', '布局检查'), ('art_process', '资源同步')]:
            if running(self.mainline, name):
                jobs.append(label)
        if running(self.fishing, 'process'):
            jobs.append('自动钓鱼')
        if running(self.hunting,'process'):
            jobs.append('围猎只读检查' if self.hunting.observing else '围猎自动化')
        return jobs

    def poll(self):
        jobs = self.active_jobs()
        self.activity.set(' · '.join(jobs) if jobs else '当前没有运行任务')
        if self.mainline:
            self.mainline_status.set('主线：'+self.mainline.run_status.get())
        if self.fishing:
            self.fishing_status.set('钓鱼：'+self.fishing.status.get()+'\n'+self.fishing.metrics.get())
        if self.hunting:
            self.hunting_status.set('围猎：'+self.hunting.status.get()+'\n'+self.hunting.metrics.get())
        if self.closing and not jobs:
            # Give the panels' exit callbacks a turn to close log streams.
            self.root.after(600, self.root.destroy)
            return
        self.timer = self.root.after(250, self.poll)

    def close(self):
        if self.closing:
            return
        self.closing = True
        if self.mainline:
            self.mainline.save_workspace()
            self.mainline.auto_sync.set(False)
            self.mainline.replay_playing = False
            if getattr(self.mainline, '_sync_timer', None):
                self.mainline.root.after_cancel(self.mainline._sync_timer)
        self.stop_all(global_signals=False)
        for button in self.navigation.values():
            button.configure(state='disabled')
        for page in self.pages.values():
            page.pack_forget()
        ttk.Label(self.host, text='正在保存并停止任务…', padding=36, style='Title.TLabel').pack(anchor='w')
        self.notice.set('正在停止任务并保存搜索进度，完成后自动关闭…')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--page', choices=('home', 'mainline', 'fishing', 'hunting'), default='home')
    args = parser.parse_args()
    root = tk.Tk()
    app = TataAssistant(root)
    app.show(args.page)
    root.mainloop()


if __name__ == '__main__':
    main()
