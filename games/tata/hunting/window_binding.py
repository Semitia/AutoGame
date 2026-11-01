"""Bind one game window to renderer descendants of its owning WeChat process."""
import ctypes
from ctypes import wintypes as W
import json
import subprocess
import hunt_paths
from desktop_input import find_game_window,game_windows,user,DesktopWindow


def owner_pid(hwnd):
    pid=W.DWORD()
    if not user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid)):raise RuntimeError('游戏窗口已关闭')
    return pid.value


def renderer_descendants(rows,parent):
    family={parent}
    while True:
        expanded=family|{r['ProcessId'] for r in rows if r['ParentProcessId'] in family}
        if expanded==family:break
        family=expanded
    return [r['ProcessId'] for r in rows if r['ProcessId'] in family and r['Renderer']]


def bound_renderers(hwnd):
    find_game_window(hwnd)
    pid=owner_pid(hwnd)
    if sum(owner_pid(h)==pid for h in game_windows())!=1:
        raise RuntimeError('同一微信进程存在多个塔塔窗口，无法唯一绑定账号，未开始操作')
    command="Get-CimInstance Win32_Process -Filter \"Name='WeChatAppEx.exe'\" | Select-Object ProcessId,ParentProcessId,@{Name='Renderer';Expression={$_.CommandLine -match '--type=renderer'}} | ConvertTo-Json -Compress"
    run=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
        capture_output=True,text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if run.returncode:raise RuntimeError('无法绑定所选微信游戏进程')
    rows=json.loads(run.stdout.strip() or '[]')
    if isinstance(rows,dict):rows=[rows]
    result=renderer_descendants(rows,pid)
    if not result:raise RuntimeError('所选窗口的游戏渲染进程尚未就绪')
    return result


def window_choices():
    result=[]
    for hwnd in game_windows():
        rect=W.RECT()
        if user.GetWindowRect(hwnd,ctypes.byref(rect)):
            result.append((hwnd,(rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top)))
    return result
