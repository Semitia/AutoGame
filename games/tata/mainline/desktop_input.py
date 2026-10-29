"""Foreground-only mouse transport for the user's standalone Tata automation tool."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import time

user=C.WinDLL('user32',use_last_error=True);kernel=C.WinDLL('kernel32',use_last_error=True)
user.SetProcessDpiAwarenessContext.argtypes=[C.c_void_p];user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
user.GetWindowRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
user.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
user.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
user.GetForegroundWindow.restype=W.HWND
user.GetAncestor.argtypes=[W.HWND,W.UINT];user.GetAncestor.restype=W.HWND
user.WindowFromPoint.argtypes=[W.POINT];user.WindowFromPoint.restype=W.HWND
user.SetCursorPos.argtypes=[C.c_int,C.c_int]
user.IsIconic.argtypes=[W.HWND];user.IsWindowVisible.argtypes=[W.HWND]
user.SetForegroundWindow.argtypes=[W.HWND];user.ShowWindow.argtypes=[W.HWND,C.c_int]
user.GetAsyncKeyState.argtypes=[C.c_int];user.GetAsyncKeyState.restype=C.c_short
kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
kernel.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
kernel.CloseHandle.argtypes=[W.HANDLE]


class MouseInput(C.Structure):
    _fields_=[('dx',W.LONG),('dy',W.LONG),('data',W.DWORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
class InputUnion(C.Union):
    _fields_=[('mi',MouseInput)]
class Input(C.Structure):
    _anonymous_=('u',);_fields_=[('type',W.DWORD),('u',InputUnion)]
user.SendInput.argtypes=[W.UINT,C.POINTER(Input),C.c_int]


class DesktopWindow:
    def __init__(self,hwnd):self.hwnd=hwnd
    def bounds(self):
        text=C.create_unicode_buffer(128);user.GetWindowTextW(self.hwnd,text,128)
        if text.value!='塔塔冒险队' or user.IsIconic(self.hwnd):raise RuntimeError('游戏窗口已关闭或最小化')
        rect=W.RECT()
        if not user.GetWindowRect(self.hwnd,C.byref(rect)):raise C.WinError(C.get_last_error())
        return rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top
    def is_foreground(self):return user.GetAncestor(user.GetForegroundWindow(),2)==self.hwnd
    def emergency_stop(self):return bool(user.GetAsyncKeyState(0x77)&0x8001)


def find_game_window():
    matches=[];callback=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    @callback
    def visit(hwnd,_):
        text=C.create_unicode_buffer(128);user.GetWindowTextW(hwnd,text,128)
        if text.value!='塔塔冒险队' or not user.IsWindowVisible(hwnd):return True
        pid=W.DWORD();user.GetWindowThreadProcessId(hwnd,C.byref(pid));handle=kernel.OpenProcess(0x1000,False,pid.value)
        if handle:
            try:
                path=C.create_unicode_buffer(32768);size=W.DWORD(len(path))
                if kernel.QueryFullProcessImageNameW(handle,0,path,C.byref(size)) and Path(path.value).name.lower()=='wechatappex.exe':matches.append(hwnd)
            finally:kernel.CloseHandle(handle)
        return True
    user.EnumWindows.argtypes=[callback,W.LPARAM];user.EnumWindows(visit,0)
    if len(matches)!=1:raise RuntimeError('需要唯一电脑微信塔塔窗口')
    return matches[0]


class LayoutChanged(RuntimeError):
    def __init__(self,gesture=False):
        super().__init__('窗口正在移动或缩放，当前动作已取消；下次启动会自动识别，无需标点')
        self.gesture=gesture


class GameInput:
    def __init__(self,width,height,adaptive=False):
        self.window=DesktopWindow(find_game_window());self.reference=(width,height)
        self.adaptive=adaptive;self.gesture_bounds=None
        self.initial_dimensions=self.window.bounds()[2:]

    def set_reference(self,width,height):
        if self.window.bounds()[2:]!=(width,height):raise LayoutChanged()
        self.reference=(width,height);self.initial_dimensions=(width,height)

    def focus(self):
        if user.IsIconic(self.window.hwnd):user.ShowWindow(self.window.hwnd,9)
        user.SetForegroundWindow(self.window.hwnd)

    def stop_check(self):
        if self.window.emergency_stop():raise RuntimeError('F8 stop')
        if not self.window.is_foreground():raise RuntimeError('游戏失去前台，停止输入')
        bounds=self.window.bounds()
        if self.gesture_bounds is not None and bounds!=self.gesture_bounds:raise LayoutChanged(gesture=True)
        if not self.adaptive and bounds[2:]!=self.initial_dimensions:raise RuntimeError('游戏窗口尺寸改变，停止输入')

    def point(self,x,y):
        self.stop_check();left,top,width,height=self.window.bounds()
        if self.adaptive and (width,height)!=self.initial_dimensions:raise LayoutChanged()
        if not 0<=x<self.reference[0] or not 0<=y<self.reference[1]:raise ValueError('输入坐标越界')
        p=W.POINT(round(left+x*width/self.reference[0]),round(top+y*height/self.reference[1]))
        if user.GetAncestor(user.WindowFromPoint(p),2)!=self.window.hwnd:raise RuntimeError('游戏被其他窗口遮挡')
        return p

    def button(self,down):
        event=Input();event.type=0;event.mi.flags=2 if down else 4
        if user.SendInput(1,C.byref(event),C.sizeof(Input))!=1:raise RuntimeError('鼠标输入被Windows拒绝')

    def click(self,x,y):
        self.gesture_bounds=self.window.bounds()
        down=False
        try:
            p=self.point(x,y);user.SetCursorPos(p.x,p.y);self.button(True);down=True
            time.sleep(.075);self.stop_check()
        finally:
            if down:self.button(False)
            self.gesture_bounds=None

    def drag(self,from_x,from_y,to_x,to_y):
        self.gesture_bounds=self.window.bounds();down=False
        try:
            start=self.point(from_x,from_y);end=self.point(to_x,to_y)
            user.SetCursorPos(start.x,start.y);time.sleep(.05);self.stop_check();self.button(True);down=True
            time.sleep(.14)
            for i in range(1,25):
                self.stop_check()
                user.SetCursorPos(round(start.x+(end.x-start.x)*i/24),round(start.y+(end.y-start.y)*i/24))
                time.sleep(.018)
            time.sleep(.06)
        finally:
            if down:self.button(False)
            self.gesture_bounds=None


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--width',type=int,required=True);p.add_argument('--height',type=int,required=True)
    p.add_argument('--action',required=True);a=p.parse_args();action=json.loads(a.action)
    game=GameInput(a.width,a.height);kind=action.pop('kind')
    if kind not in ('click','drag'):raise ValueError('不支持的输入动作')
    getattr(game,kind)(**action)


if __name__=='__main__':main()
