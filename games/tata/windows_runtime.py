"""Shared window binding and background transports for Tata feature workers."""
from pathlib import Path
import sys
import json
import ctypes

HERE=Path(__file__).resolve().parent


def prepare():
    for folder in (HERE/'hunting',HERE/'mainline'):
        if str(folder) not in sys.path:sys.path.insert(0,str(folder))


def background_input(hwnd,width=400,height=750,adaptive=True):
    prepare()
    from background_input import BackgroundHuntInput
    return BackgroundHuntInput(hwnd,width,height,adaptive)


def window_pids(hwnd):
    prepare()
    from window_binding import bound_renderers
    return bound_renderers(hwnd)


def window_identity(hwnd):
    prepare()
    from live_battle import LiveBattle
    from live_session import session_fields
    live=LiveBattle(pids=window_pids(hwnd))
    try:
        first=session_fields(live.heap,live.refs)['account']
        second=session_fields(live.heap,live.refs)['account']
        if first['key']!=second['key']:raise RuntimeError('读取中账号已切换')
        return dict(key=first['key'],name=first['name'])
    finally:live.close()


def pid_running(pid):
    if type(pid) is not int or pid<=0:return False
    prepare()
    from desktop_input import kernel,W
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:return False
    try:
        kernel.GetExitCodeProcess.argtypes=[W.HANDLE,ctypes.POINTER(W.DWORD)]
        code=W.DWORD()
        return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
    finally:kernel.CloseHandle(handle)


def job_status(feature,hwnd):
    path=HERE.parents[1]/'runtime/tata'/feature/'windows'/str(hwnd)/'status.json'
    try:value=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return None
    return value


def external_job(feature,hwnd):
    value=job_status(feature,hwnd)
    if not value:return None
    if value.get('event') in ('finished','stopped','error'):return None
    return value if pid_running(value.get('pid')) else None


def stop_external(feature,hwnd):
    value=external_job(feature,hwnd)
    if not value or not value.get('stop_file'):return
    root=(HERE.parents[1]/'runtime/tata').resolve();path=Path(value['stop_file']).resolve()
    if not path.is_relative_to(root):raise RuntimeError('任务停止文件不在本机运行目录内')
    path.parent.mkdir(parents=True,exist_ok=True);path.touch()


class FishingBackgroundWindow:
    def __init__(self,hwnd,account_key=None):
        prepare()
        from live_battle import LiveBattle
        from live_session import session_fields
        self.controls=background_input(hwnd)
        self.live=LiveBattle(pids=window_pids(hwnd))
        self.key=session_fields(self.live.heap,self.live.refs)['account']['key']
        if account_key and self.key!=account_key:
            self.live.close();raise RuntimeError('所选钓鱼账号已切换，未开始输入')

    def verify(self):
        from live_session import session_fields
        self.controls.stop_check()
        if session_fields(self.live.heap,self.live.refs)['account']['key']!=self.key:
            raise RuntimeError('钓鱼账号已切换，停止后台输入')

    def grab(self):
        import time,cv2,numpy as np
        self.verify();start=time.perf_counter();image=self.controls.capture()
        self.controls.set_reference(*image.size)
        return cv2.resize(cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR),(400,750)),start

    def click(self,x=200,y=620):
        self.verify();width,height=self.controls.reference
        self.controls.click(x*width/400,y*height/750)

    def emergency_stop(self):return self.controls.window.emergency_stop()

    def close(self):
        try:self.controls.release()
        finally:self.live.close()
