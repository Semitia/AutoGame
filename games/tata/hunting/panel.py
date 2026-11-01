"""Embedded or standalone hunt controls. Loading the panel never touches the game."""
from datetime import datetime
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk
import uuid
from hunt_paths import HERE,ROOT,RUNTIME
from hunt_policy import Options
from model import write_json

LABELS={'initializing':'正在连接围猎','enter':'正在进入场地','next':'选择下一场地','previous':'选择上一场地',
    'lock_requested':'已点锁定，等待实际目标确认','rage_requested':'已点狂暴，等待生效',
    'exit_requested':'已点退出，正在确认离场','exit_reward_closed':'已关闭本局奖励页',
    'room_exited':'已确认退出房间','finished':'本次运行完成','stopped':'已停止',
    'observation':'只读检查成功','error':'运行停止'}


class HuntPanel:
    def __init__(self,root,*,embedded=False,before_start=None):
        self.root=root;self.before_start=before_start;self.process=None;self.stop_file=None
        self.queue=queue.Queue();self.observing=False;self.closing=False;self.error=None
        if not embedded:
            root.title('塔塔冒险队 · 围猎');root.geometry('640x690')
            root.protocol('WM_DELETE_WINDOW',self.close)
        box=ttk.Frame(root,padding=24);box.pack(fill='both',expand=True)
        ttk.Label(box,text='围猎臭臭',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        ttk.Label(box,text='低倍攒道具 → 200倍等萨满 → 锁定 → 目标结束立即退出',wraplength=850).pack(anchor='w',pady=(8,20))
        settings={}
        try:settings=json.loads((RUNTIME/'options.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        self.fields={}
        form=ttk.Frame(box);form.pack(anchor='w',fill='x')
        rows=[('stock','攒够多少个锁定再去200倍场',10),('low','低倍场倍率（1、2、5）',1),
              ('minutes','本次运行时长（分钟）',60),('rounds','本次最多围猎轮数',10),('reserve','保留金猎币',0)]
        for i,(key,label,value) in enumerate(rows):
            ttk.Label(form,text=label).grid(row=i,column=0,sticky='w',pady=6,padx=(0,16))
            variable=tk.StringVar(master=root,value=str(settings.get(key,value)));self.fields[key]=variable
            ttk.Entry(form,textvariable=variable,width=10).grid(row=i,column=1,sticky='w')
        self.rage=tk.BooleanVar(master=root,value=settings.get('rage',True))
        ttk.Checkbutton(box,text='低倍场有狂暴就使用；200倍场仅使用锁定',variable=self.rage).pack(anchor='w',pady=14)
        bar=ttk.Frame(box);bar.pack(fill='x',pady=6)
        self.start_button=ttk.Button(bar,text='开始围猎',command=self.start);self.start_button.pack(side='left',padx=(0,10))
        self.stop_button=ttk.Button(bar,text='停止并退出围猎',command=self.stop,state='disabled');self.stop_button.pack(side='left',padx=(0,10))
        self.observe_button=ttk.Button(bar,text='后台只读检查',command=lambda:self.start(True));self.observe_button.pack(side='left')
        self.status=tk.StringVar(master=root,value='请先打开围猎选场页或围猎房间，运行时保持游戏前台。F8立即停止输入。')
        ttk.Label(box,textvariable=self.status,wraplength=900).pack(anchor='w',pady=(16,8))
        self.metrics=tk.StringVar(master=root,value='锁定 —    狂暴 —    金猎币 —    已完成 0 轮')
        ttk.Label(box,textvariable=self.metrics).pack(anchor='w',pady=(0,10))
        self.log=tk.Text(box,height=8,width=65,wrap='word',state='disabled',font=('Microsoft YaHei UI',9))
        self.log.pack(fill='both',expand=True)
        ttk.Label(box,text='自动运行需保持游戏前台。F8立即停止工具输入；游戏已生效的锁定可能仍需手动退出。',
                  wraplength=900).pack(anchor='w',pady=10)
        self.root.after(100,self.poll)

    def add_log(self,line):
        self.log.configure(state='normal');self.log.insert('end',datetime.now().strftime('%H:%M:%S')+'  '+line+'\n')
        if int(self.log.index('end-1c').split('.')[0])>80:self.log.delete('1.0','2.0')
        self.log.see('end');self.log.configure(state='disabled')

    def options(self):
        values={k:v.get() for k,v in self.fields.items()}
        option=Options(int(values['stock']),int(values['low']),self.rage.get(),int(values['rounds']),
                       float(values['minutes'])*60,int(values['reserve'])).validate()
        write_json(RUNTIME/'options.json',dict(values,rage=self.rage.get()))
        return option

    def start(self,observe=False):
        if self.process is not None:return
        try:
            if not observe and self.before_start:self.before_start()
            options=self.options();RUNTIME.mkdir(parents=True,exist_ok=True)
            self.stop_file=RUNTIME/('panel-'+uuid.uuid4().hex+'.stop')
            if not observe:(RUNTIME/'STOP').unlink(missing_ok=True)
            self.run_dir=RUNTIME/'runs'/uuid.uuid4().hex
            args=[sys.executable,'-X','utf8','-u',str(HERE/'desktop.py'),
                  '--stock',str(options.stock),'--low',str(options.low_multiplier),'--rounds',str(options.rounds),
                  '--seconds',str(1 if observe else options.seconds),'--reserve',str(options.reserve),
                  '--run-dir',str(self.run_dir),'--stop-file',str(self.stop_file)]
            args+=['--observe'] if observe else ['--run','--activate']
            if not options.use_rage:args+=['--no-rage']
            self.process=subprocess.Popen(args,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,encoding='utf-8',errors='replace',env=dict(os.environ,PYTHONIOENCODING='utf-8'),
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.observing=observe;self.error=None
            self.start_button.configure(state='disabled');self.observe_button.configure(state='disabled');self.stop_button.configure(state='normal')
            self.status.set('后台只读检查中，不激活游戏…' if observe else '围猎启动中…')
            threading.Thread(target=self.read_output,args=(self.process,),daemon=True).start()
        except Exception as exc:self.status.set(str(exc));self.add_log(str(exc))

    def read_output(self,process):
        for line in process.stdout:
            try:self.queue.put(json.loads(line))
            except ValueError:pass
        process.stdout.close();self.queue.put(dict(event='_exit',code=process.wait()))

    def stop(self):
        if self.process is None:return
        self.stop_file.touch();self.status.set('正在停止射击并退出当前围猎房间…')
        self.stop_button.configure(state='disabled')

    def poll(self):
        try:
            while True:
                row=self.queue.get_nowait();event=row.get('event')
                if event=='_exit':
                    self.process=None;self.stop_file.unlink(missing_ok=True)
                    self.start_button.configure(state='normal');self.observe_button.configure(state='normal');self.stop_button.configure(state='disabled')
                    if row['code'] and not self.error:self.status.set('进程退出，请查看 '+str(self.run_dir/'events.jsonl'))
                    if self.closing:self.root.destroy();return
                    continue
                text=row.get('reason') or LABELS.get(event,event)
                if event=='error':self.error=text
                self.status.set(text)
                if event!='state':self.add_log(text)
                if 'locks' in row:
                    self.metrics.set(f'锁定 {row["locks"]}    狂暴 {row.get("rage","—")}    金猎币 {row.get("bullets","—")}    已完成 {row.get("completed",0)} 轮')
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def close(self):
        if self.process is not None:self.closing=True;self.stop()
        else:self.root.destroy()


def main():
    root=tk.Tk();HuntPanel(root);root.mainloop()


if __name__=='__main__':main()
