"""Window-local mouse messages and PrintWindow capture; never moves the cursor."""
import ctypes as C
from ctypes import wintypes as W
import queue
import threading
import time
from PIL import Image,ImageStat
import numpy as np
import hunt_paths
from desktop_input import user,LayoutChanged,GameInput
from hunt_input import HuntInput
from window_binding import owner_pid

gdi=C.WinDLL('gdi32',use_last_error=True)
user.GetDC.argtypes=[W.HWND];user.GetDC.restype=W.HDC
user.ReleaseDC.argtypes=[W.HWND,W.HDC]
user.PrintWindow.argtypes=[W.HWND,W.HDC,W.UINT]
user.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
user.ScreenToClient.argtypes=[W.HWND,C.POINTER(W.POINT)]
user.GetClientRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
gdi.CreateCompatibleDC.argtypes=[W.HDC];gdi.CreateCompatibleDC.restype=W.HDC
gdi.CreateCompatibleBitmap.argtypes=[W.HDC,C.c_int,C.c_int];gdi.CreateCompatibleBitmap.restype=W.HBITMAP
gdi.SelectObject.argtypes=[W.HDC,W.HGDIOBJ];gdi.SelectObject.restype=W.HGDIOBJ
gdi.DeleteObject.argtypes=[W.HGDIOBJ];gdi.DeleteDC.argtypes=[W.HDC]


class BitmapHeader(C.Structure):
    _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),
        ('bits',W.WORD),('compression',W.DWORD),('image_size',W.DWORD),('xppm',W.LONG),
        ('yppm',W.LONG),('used',W.DWORD),('important',W.DWORD)]


gdi.GetDIBits.argtypes=[W.HDC,W.HBITMAP,W.UINT,W.UINT,C.c_void_p,C.POINTER(BitmapHeader),W.UINT]


class CaptureFrameError(RuntimeError):pass


def validate_frame(image):
    content=np.asarray(image.crop((0,round(image.height*.07),image.width,image.height)))
    if max(ImageStat.Stat(image).stddev)<3 or np.mean(content.max(axis=2)<8)>.35:
        raise CaptureFrameError('后台截图出现黑屏或不完整帧，停止输入')


def print_window(hwnd,size):
    width,height=size
    screen=user.GetDC(None)
    if not screen:raise RuntimeError('无法创建后台截图上下文')
    memory=bitmap=original=None
    try:
        memory=gdi.CreateCompatibleDC(screen)
        if not memory:raise RuntimeError('无法创建后台截图缓冲')
        bitmap=gdi.CreateCompatibleBitmap(screen,width,height)
        if not bitmap:raise RuntimeError('无法创建后台截图位图')
        original=gdi.SelectObject(memory,bitmap)
        if not user.PrintWindow(hwnd,memory,2):raise RuntimeError('当前微信版本不支持后台截图')
        data=C.create_string_buffer(width*height*4)
        header=BitmapHeader(C.sizeof(BitmapHeader),width,-height,1,32,0,width*height*4,0,0,0,0)
        if gdi.GetDIBits(memory,bitmap,0,height,data,C.byref(header),0)!=height:
            raise RuntimeError('后台截图数据不完整')
        image=Image.frombytes('RGB',(width,height),data.raw,'raw','BGRX')
        validate_frame(image)
        return image
    finally:
        if original:gdi.SelectObject(memory,original)
        if bitmap:gdi.DeleteObject(bitmap)
        if memory:gdi.DeleteDC(memory)
        user.ReleaseDC(None,screen)


class BackgroundHuntInput(HuntInput):
    def __init__(self,hwnd,width=400,height=750,adaptive=True):
        GameInput.__init__(self,width,height,adaptive=adaptive,hwnd=hwnd)
        self.firing=False;self.owner=owner_pid(hwnd);self.held_point=None
        self.last_pulse=float('-inf')

    def focus(self):raise RuntimeError('后台模式不激活游戏窗口')

    def stop_check(self):
        if self.window.emergency_stop():raise RuntimeError('F8 stop')
        if owner_pid(self.window.hwnd)!=self.owner:raise RuntimeError('所选游戏窗口已被其他进程替换')
        bounds=self.window.bounds()
        if self.gesture_bounds is not None and bounds!=self.gesture_bounds:raise LayoutChanged(gesture=True)

    def point(self,x,y):
        self.stop_check();left,top,width,height=self.window.bounds()
        if (width,height)!=self.initial_dimensions:raise LayoutChanged()
        if not 0<=x<self.reference[0] or not 0<=y<self.reference[1]:raise ValueError('输入坐标越界')
        point=W.POINT(round(left+x*width/self.reference[0]),round(top+y*height/self.reference[1]))
        if not user.ScreenToClient(self.window.hwnd,C.byref(point)):raise C.WinError(C.get_last_error())
        client=W.RECT()
        if not user.GetClientRect(self.window.hwnd,C.byref(client)):raise C.WinError(C.get_last_error())
        if not 0<=point.x<client.right or not 0<=point.y<client.bottom:raise ValueError('输入不在游戏客户区')
        return point

    def post(self,message,keys,point):
        packed=(point.x&65535)|((point.y&65535)<<16)
        if not user.PostMessageW(self.window.hwnd,message,keys,packed):raise C.WinError(C.get_last_error())

    def click(self,x,y):
        self.gesture_bounds=self.window.bounds();down=False;point=None
        try:
            point=self.point(x,y);self.post(0x200,0,point)
            self.post(0x201,1,point);down=True
            time.sleep(.035);self.stop_check()
        finally:
            try:
                if down and owner_pid(self.window.hwnd)==self.owner:self.post(0x202,0,point)
            finally:self.gesture_bounds=None

    def start_fire(self,point):
        if self.firing:
            current=self.point(*point);self.post(0x200,1,current);self.held_point=current;return
        self.gesture_bounds=self.window.bounds()
        try:
            current=self.point(*point);self.post(0x200,0,current)
            self.post(0x201,1,current);self.held_point=current;self.firing=True
        except Exception:
            self.gesture_bounds=None;raise

    def drag(self,from_x,from_y,to_x,to_y):
        self.gesture_bounds=self.window.bounds();down=False;point=None
        try:
            start=self.point(from_x,from_y);end=self.point(to_x,to_y)
            point=start;self.post(0x200,0,start);self.post(0x201,1,start);down=True
            time.sleep(.09)
            for i in range(1,13):
                self.stop_check()
                point=W.POINT(round(start.x+(end.x-start.x)*i/12),round(start.y+(end.y-start.y)*i/12))
                self.post(0x200,1,point);time.sleep(.01)
            time.sleep(.02)
        finally:
            try:
                if down and owner_pid(self.window.hwnd)==self.owner:self.post(0x202,0,point)
            finally:self.gesture_bounds=None

    def release(self):
        try:
            if self.firing and owner_pid(self.window.hwnd)==self.owner:self.post(0x202,0,self.held_point)
        finally:self.firing=False;self.held_point=None;self.gesture_bounds=None

    def fire_at(self,point,interval=.33):
        # Window-local click pulses do not depend on the user's physical
        # button state while working in another app. Respect the native rate.
        if time.monotonic()-self.last_pulse<interval:return
        self.release();self.click(*point);self.last_pulse=time.monotonic()

    def capture(self):
        self.stop_check();bounds=self.window.bounds();result=queue.Queue(maxsize=1)
        def work():
            try:
                for attempt in range(4):
                    try:
                        image=print_window(self.window.hwnd,bounds[2:]);break
                    except CaptureFrameError:
                        if attempt==3:raise
                        time.sleep(.03)
                result.put((True,image))
            except Exception as exc:result.put((False,exc))
        threading.Thread(target=work,daemon=True).start()
        try:ok,value=result.get(timeout=3)
        except queue.Empty:raise RuntimeError('后台截图超时，停止输入') from None
        if not ok:raise value
        self.stop_check()
        if self.window.bounds()!=bounds:raise LayoutChanged()
        return value
