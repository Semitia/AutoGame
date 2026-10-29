"""Visible first-run dependency setup; keep normal workbench launches quiet."""
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    try:
        missing = []
        for module in ('PIL', 'lupa', 'google.protobuf', 'cv2'):
            try:
                found = importlib.util.find_spec(module)
            except ModuleNotFoundError:
                found = None
            if found is None:
                missing.append(module)
        if missing:
            print('首次启动：正在安装主线工作台依赖，请保持此窗口打开…', flush=True)
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r',
                            str(ROOT / 'games/tata/mainline/requirements.txt')], check=True)
        executable = Path(sys.executable)
        windowless = executable.with_name('pythonw.exe')
        subprocess.Popen([str(windowless if windowless.exists() else executable),
                          str(ROOT / 'run.py'), 'tata', 'mainline', *sys.argv[1:]], cwd=ROOT)
    except Exception as exc:
        print(f'主线工作台启动失败：{exc}', flush=True)
        input('按回车关闭；可以复制上面的错误信息。')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
