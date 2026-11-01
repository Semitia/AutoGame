"""Only real Windows mouse gestures, sharing mainline foreground/resize guards."""
import hunt_paths
from desktop_input import GameInput,user


class HuntInput(GameInput):
    def __init__(self):
        super().__init__(400,750,adaptive=True);self.firing=False

    def start_fire(self,point):
        if self.firing:return
        self.gesture_bounds=self.window.bounds()
        try:
            p=self.point(*point);user.SetCursorPos(p.x,p.y);self.button(True);self.firing=True
        except Exception:
            self.gesture_bounds=None;raise

    def release(self):
        try:
            if self.firing:self.button(False)
        finally:self.firing=False;self.gesture_bounds=None
