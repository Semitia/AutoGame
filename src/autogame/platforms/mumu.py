"""ADB capture/input and MuMu window control; coordinates are Android pixels."""
import json
import os
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[3]

class MuMuPlatform:
    def __init__(self, device='emulator-5554'):
        config = REPO / 'config/local.json'
        local = json.loads(config.read_text(encoding='utf8')) if config.exists() else {}
        cfg = local.get('mumu', {})
        install = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'NetEase/MuMu/nx_main'
        self.adb = os.environ.get('AUTOGAME_ADB', cfg.get('adb', str(install / 'adb.exe')))
        self.manager = os.environ.get('AUTOGAME_MUMU_MANAGER', cfg.get('manager', str(install / 'MuMuManager.exe')))
        self.index = str(os.environ.get('AUTOGAME_MUMU_INDEX', cfg.get('index', 0)))
        self.device = device

    def screenshot(self):
        return subprocess.check_output([self.adb, '-s', self.device, 'exec-out', 'screencap', '-p'], timeout=12)

    def shell(self, *args):
        return subprocess.check_output([self.adb, '-s', self.device, 'shell', *map(str, args)], timeout=12)

    def tap(self, x, y):
        return self.shell('input', 'tap', x, y)

    def swipe(self, x1, y1, x2, y2, duration_ms=650):
        return self.shell('input', 'swipe', x1, y1, x2, y2, duration_ms)

    def _window(self, operation):
        return subprocess.run([self.manager, 'control', '-v', self.index, operation], check=True, capture_output=True, timeout=12)

    def hide(self):
        return self._window('hide_window')

    def show(self):
        return self._window('show_window')
