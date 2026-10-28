"""Small local start/stop panel; runner work stays in a separate process."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
import uuid

from windows import DesktopWindow,find_game_window,user
from paths import ROOT,RUNTIME

STATES={'idle':'准备出杆','waiting':'等待鱼上钩','hook':'鱼已上钩','slider':'预判收杆',
        'reward':'收取鱼获','reward_animation':'鱼获展示中','rare_reward':'稀有鱼获！','record_reward':'刷新纪录，正在收鱼',
        'result_card':'收取鱼获展示页','unknown':'等待画面稳定，必要时点击空白处恢复'}
ACTIONS={'cast':'已出杆','hook':'已提钩','reel':'已点击收杆','collect':'已收取鱼获','dismiss_rare':'已收取稀有鱼获',
         'dismiss_record':'已收取纪录鱼获','dismiss_card':'已收取鱼获','recover_blank':'已点击空白处恢复'}


def friendly_error(text):
    if 'foreground' in text:return '游戏离开前台，已停止'
    if 'covered' in text:return '游戏按钮被遮挡，已停止'
    if 'minimized' in text:return '游戏已关闭或最小化'
    if 'Open exactly one' in text:return '请先打开一个「塔塔冒险队」游戏窗口'
    if 'already controlled' in text or 'existing controller' in text:return '已有程序在控制游戏，请先停止另一个程序'
    return text.removeprefix('ERROR: ').strip()


class FishingPanel:
    def __init__(self,root,observe=False):
        self.root=root;self.observe=observe;self.process=None;self.stop_file=None
        self.queue=queue.Queue();self.stopping=False;self.closing=False;self.deadline=None
        self.counts={'cast':0,'reel':0,'collect':0};self.started=None;self.last_error=None
        root.title('自动钓鱼 · 控制面板');root.resizable(False,False)
        root.configure(bg='#f4f7fb');root.attributes('-topmost',True)
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('TFrame',background='#f4f7fb')
        style.configure('TLabel',background='#f4f7fb',foreground='#20324a',font=('Microsoft YaHei UI',10))
        style.configure('Title.TLabel',font=('Microsoft YaHei UI',18,'bold'))
        style.configure('Hint.TLabel',foreground='#64748b',font=('Microsoft YaHei UI',9))
        outer=ttk.Frame(root,padding=22);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='自动钓鱼',style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer,text='塔塔冒险队 · 电脑微信版',style='Hint.TLabel').pack(anchor='w',pady=(2,16))
        self.status=tk.StringVar(value='已停止，点击下方按钮开始')
        ttk.Label(outer,textvariable=self.status,wraplength=430).pack(anchor='w',pady=(0,15))
        self.button=tk.Button(outer,text='开始钓鱼',command=self.toggle,font=('Microsoft YaHei UI',15,'bold'),
                              bg='#167dcb',fg='white',activebackground='#1264a3',activeforeground='white',
                              relief='flat',borderwidth=0,pady=12,cursor='hand2')
        self.button.pack(fill='x')
        settings=ttk.Frame(outer);settings.pack(fill='x',pady=14)
        ttk.Label(settings,text='运行时长').pack(side='left')
        self.minutes=tk.StringVar(value='30')
        self.duration=ttk.Spinbox(settings,from_=1,to=1440,width=6,textvariable=self.minutes,font=('Microsoft YaHei UI',10))
        self.duration.pack(side='left',padx=8)
        ttk.Label(settings,text='分钟').pack(side='left')
        self.metrics=tk.StringVar(value='出杆 0    收杆点击 0    鱼获 0')
        ttk.Label(outer,textvariable=self.metrics).pack(anchor='w',pady=(0,10))
        self.log=tk.Text(outer,height=5,width=43,font=('Microsoft YaHei UI',9),bg='white',fg='#475569',
                         relief='flat',padx=10,pady=8,state='disabled',takefocus=False)
        self.log.pack(fill='x')
        ttk.Label(outer,text='保持游戏在前台；F8 或点按钮即可停止。',style='Hint.TLabel').pack(anchor='w',pady=(12,0))
        if observe:ttk.Label(outer,text='测试模式：仅观察，不点击游戏',style='Hint.TLabel').pack(anchor='w')
        self.position()
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(100,self.poll)

    def position(self):
        self.root.update_idletasks()
        try:
            x,y,w,h=DesktopWindow(find_game_window()).bounds()
            px=x+w+16;py=max(20,y)
            if px+self.root.winfo_reqwidth()>self.root.winfo_screenwidth():px=max(0,x-self.root.winfo_reqwidth()-16)
            py=min(py,max(0,self.root.winfo_screenheight()-self.root.winfo_reqheight()-60))
            self.root.geometry(f'+{px}+{py}')
        except Exception:self.root.geometry('+800+120')

    def add_log(self,text):
        self.log.configure(state='normal')
        self.log.insert('end',datetime.now().strftime('%H:%M:%S')+'  '+text+'\n')
        if int(self.log.index('end-1c').split('.')[0])>40:self.log.delete('1.0','2.0')
        self.log.see('end');self.log.configure(state='disabled')

    def toggle(self):
        if self.process is None:self.start()
        else:self.stop()

    def start(self):
        try:
            minutes=float(self.minutes.get())
            if not 1<=minutes<=1440:raise ValueError('运行时长请输入 1～1440 分钟')
            hwnd=find_game_window()
            RUNTIME.mkdir(parents=True,exist_ok=True)
            self.stop_file=RUNTIME/('panel-'+uuid.uuid4().hex+'.stop')
            cmd=[sys.executable,'-u',str(Path(__file__).with_name('desktop.py')),'--hwnd',str(hwnd),
                 '--seconds',str(minutes*60),'--stop-file',str(self.stop_file)]
            if self.observe:cmd.append('--observe')
            env=dict(os.environ,PYTHONIOENCODING='utf-8')
            # The click on Start authorizes focusing the game; later focus loss stops the runner.
            user.SetForegroundWindow(hwnd)
            self.process=subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,encoding='utf-8',errors='replace',bufsize=1,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
            self.counts={'cast':0,'reel':0,'collect':0};self.stopping=False;self.last_error=None;self.started=time.monotonic()
            self.status.set('正在连接游戏…');self.button.configure(text='停止钓鱼',bg='#d54949',activebackground='#b63838')
            self.duration.configure(state='disabled');self.add_log('开始运行'+('（仅观察）' if self.observe else ''))
            threading.Thread(target=self.read_output,args=(self.process,),daemon=True).start()
        except Exception as error:
            self.status.set(friendly_error(str(error)));self.add_log(friendly_error(str(error)))

    def read_output(self,process):
        for line in process.stdout:
            line=line.strip()
            if line:self.queue.put(line)
        process.stdout.close()
        self.queue.put(('exit',process.wait()))

    def stop(self):
        if not self.process or self.stopping:return
        self.stopping=True
        self.last_error=None
        self.stop_file.touch()
        self.status.set('正在停止…');self.button.configure(text='正在停止…',state='disabled')
        self.add_log('已请求停止');self.deadline=time.monotonic()+4

    def handle(self,line):
        if not isinstance(line,str):
            code=line[1];self.process=None;self.stopping=False;self.deadline=None
            if self.stop_file:self.stop_file.unlink(missing_ok=True)
            self.duration.configure(state='normal');self.button.configure(text='开始钓鱼',state='normal',bg='#167dcb',activebackground='#1264a3')
            self.status.set(self.last_error or ('已停止' if code==0 else '运行已停止，请查看下方信息'))
            self.add_log('运行已结束')
            if self.closing:self.root.destroy()
            return
        try:row=json.loads(line)
        except ValueError:
            if line.startswith('ERROR:'):
                if self.stopping:return
                self.last_error=friendly_error(line);self.status.set(self.last_error);self.add_log(self.last_error)
            return
        kind=row.get('event')
        if kind=='state':
            self.status.set(('仅观察 · ' if self.observe else '运行中 · ')+STATES.get(row['state'],row['state']))
        elif kind=='click':
            action=row['action']
            self.counts['cast']=row.get('casts',self.counts['cast'])
            self.counts['reel']=row.get('slider_clicks',self.counts['reel'])
            self.counts['collect']=row.get('rewards',self.counts['collect'])
            self.add_log(ACTIONS.get(action,action))
        elif kind=='stop_unknown':
            self.last_error='尝试点击空白处后仍未恢复，已停止'
            self.add_log(self.last_error)
        self.metrics.set(f"出杆 {self.counts['cast']}    收杆点击 {self.counts['reel']}    鱼获 {self.counts['collect']}")

    def poll(self):
        try:
            while True:self.handle(self.queue.get_nowait())
        except queue.Empty:pass
        if self.closing and self.process is None:return
        if self.process and self.deadline and time.monotonic()>self.deadline:
            self.process.terminate();self.deadline=None
        self.root.after(100,self.poll)

    def close(self):
        if self.process:
            self.closing=True;self.stop()
        else:self.root.destroy()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--observe',action='store_true')
    args=parser.parse_args()
    root=tk.Tk();FishingPanel(root,observe=args.observe);root.mainloop()


if __name__=='__main__':main()
