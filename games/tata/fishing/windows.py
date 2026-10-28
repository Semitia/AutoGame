"""Native Windows transport for the user-requested desktop fishing tool."""
import ctypes as C
from ctypes import wintypes as W
import time

import cv2
import numpy as np

user = C.WinDLL('user32', use_last_error=True)
gdi = C.WinDLL('gdi32', use_last_error=True)
user.SetProcessDpiAwarenessContext.argtypes = [C.c_void_p]
user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
user.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
user.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
user.GetForegroundWindow.restype = W.HWND
user.GetAncestor.argtypes = [W.HWND, W.UINT]
user.GetAncestor.restype = W.HWND
user.GetDC.argtypes = [W.HWND]
user.GetDC.restype = W.HDC
user.ReleaseDC.argtypes = [W.HWND, W.HDC]
gdi.CreateCompatibleDC.argtypes = [W.HDC]
gdi.CreateCompatibleDC.restype = W.HDC
gdi.CreateCompatibleBitmap.argtypes = [W.HDC, C.c_int, C.c_int]
gdi.CreateCompatibleBitmap.restype = W.HBITMAP
gdi.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
gdi.SelectObject.restype = W.HGDIOBJ
gdi.BitBlt.argtypes = [W.HDC,C.c_int,C.c_int,C.c_int,C.c_int,W.HDC,C.c_int,C.c_int,W.DWORD]
gdi.DeleteObject.argtypes = [W.HGDIOBJ]
gdi.DeleteDC.argtypes = [W.HDC]


class BitmapHeader(C.Structure):
    _fields_ = [('size', W.DWORD), ('width', W.LONG), ('height', W.LONG),
                ('planes', W.WORD), ('bits', W.WORD), ('compression', W.DWORD),
                ('image_size', W.DWORD), ('xppm', W.LONG), ('yppm', W.LONG),
                ('used', W.DWORD), ('important', W.DWORD)]


gdi.GetDIBits.argtypes = [W.HDC,W.HBITMAP,W.UINT,W.UINT,C.c_void_p,C.POINTER(BitmapHeader),W.UINT]


class MouseInput(C.Structure):
    _fields_ = [('dx',W.LONG),('dy',W.LONG),('data',W.DWORD),('flags',W.DWORD),
                ('time',W.DWORD),('extra',C.c_size_t)]


class KeyboardInput(C.Structure):
    _fields_ = [('vk',W.WORD),('scan',W.WORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]


class InputUnion(C.Union):
    _fields_ = [('mi',MouseInput),('ki',KeyboardInput)]


class Input(C.Structure):
    _anonymous_ = ('u',)
    _fields_ = [('type',W.DWORD),('u',InputUnion)]


user.SendInput.argtypes = [W.UINT,C.POINTER(Input),C.c_int]
user.SetCursorPos.argtypes = [C.c_int,C.c_int]
user.GetAsyncKeyState.argtypes = [C.c_int]
user.GetAsyncKeyState.restype = C.c_short


class DesktopWindow:
    def __init__(self, hwnd, title='塔塔冒险队'):
        self.hwnd = int(hwnd)
        self.title = title
        self.screen = self.memory = self.bitmap = self.original = None
        self.dimensions = None

    def bounds(self):
        text = C.create_unicode_buffer(512)
        user.GetWindowTextW(self.hwnd,text,512)
        if text.value != self.title or user.IsIconic(self.hwnd):
            raise RuntimeError('Game window closed, minimized, or renamed.')
        rect = W.RECT()
        if not user.GetWindowRect(self.hwnd,C.byref(rect)):
            raise C.WinError(C.get_last_error())
        return rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top

    def is_foreground(self):
        return user.GetAncestor(user.GetForegroundWindow(),2) == self.hwnd

    def grab(self):
        x,y,w,h = self.bounds()
        if not self.is_foreground():
            raise RuntimeError('Game is no longer foreground. Input stopped.')
        if self.dimensions != (w,h):
            self.close()
            self.screen = user.GetDC(None)
            self.memory = gdi.CreateCompatibleDC(self.screen)
            self.bitmap = gdi.CreateCompatibleBitmap(self.screen,w,h)
            self.original = gdi.SelectObject(self.memory,self.bitmap)
            self.buffer = C.create_string_buffer(w*h*4)
            self.header = BitmapHeader(C.sizeof(BitmapHeader),w,-h,1,32,0,w*h*4,0,0,0,0)
            self.dimensions = (w,h)
        t = time.perf_counter()
        if not gdi.BitBlt(self.memory,0,0,w,h,self.screen,x,y,0x00CC0020):
            raise C.WinError(C.get_last_error())
        if gdi.GetDIBits(self.memory,self.bitmap,0,h,self.buffer,C.byref(self.header),0) != h:
            raise RuntimeError('Screen capture failed.')
        frame = np.frombuffer(self.buffer,np.uint8).reshape(h,w,4)[:,:,:3]
        return cv2.resize(frame,(400,750)), t

    def click(self,x=200,y=620):
        if not self.is_foreground():
            raise RuntimeError('Refusing input outside the selected game window.')
        left,top,w,h = self.bounds()
        # Do not click a floating window that happens to cover the game button.
        point=W.POINT(round(left+x*w/400),round(top+y*h/750))
        if user.GetAncestor(user.WindowFromPoint(point),2) != self.hwnd:
            raise RuntimeError('Game button is covered by another window.')
        user.SetCursorPos(point.x,point.y)
        inputs=(Input*2)()
        inputs[0].type=inputs[1].type=0
        inputs[0].mi.flags=0x0002
        inputs[1].mi.flags=0x0004
        if user.SendInput(2,inputs,C.sizeof(Input)) != 2:
            raise RuntimeError('Windows rejected mouse input.')

    def close(self):
        if self.memory:
            gdi.SelectObject(self.memory,self.original)
            gdi.DeleteObject(self.bitmap)
            gdi.DeleteDC(self.memory)
            user.ReleaseDC(None,self.screen)
        self.screen=self.memory=self.bitmap=self.original=None
        self.dimensions=None

    @staticmethod
    def emergency_stop():
        return bool(user.GetAsyncKeyState(0x77)&0x8000)  # F8


user.WindowFromPoint.argtypes=[W.POINT]
user.WindowFromPoint.restype=W.HWND
user.SetForegroundWindow.argtypes=[W.HWND]
user.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
user.IsWindowVisible.argtypes=[W.HWND]
user.IsIconic.argtypes=[W.HWND]
kernel=C.WinDLL('kernel32',use_last_error=True)
kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD]
kernel.OpenProcess.restype=W.HANDLE
kernel.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
kernel.CloseHandle.argtypes=[W.HANDLE]


def is_wechat_game(hwnd):
    pid=W.DWORD();user.GetWindowThreadProcessId(hwnd,C.byref(pid))
    process=kernel.OpenProcess(0x1000,False,pid.value)
    if not process:return False
    try:
        path=C.create_unicode_buffer(32768);size=W.DWORD(len(path))
        return bool(kernel.QueryFullProcessImageNameW(process,0,path,C.byref(size))) and path.value.lower().endswith('\\wechatappex.exe')
    finally:kernel.CloseHandle(process)


def find_game_window():
    matches=[]
    callback=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    @callback
    def visit(hwnd,_):
        text=C.create_unicode_buffer(512)
        user.GetWindowTextW(hwnd,text,512)
        if text.value=='塔塔冒险队' and user.IsWindowVisible(hwnd) and is_wechat_game(hwnd):matches.append(int(hwnd))
        return True
    user.EnumWindows.argtypes=[callback,W.LPARAM]
    user.EnumWindows(visit,0)
    if len(matches)!=1:raise RuntimeError(f'Open exactly one 塔塔冒险队 window; found {len(matches)}.')
    return matches[0]
