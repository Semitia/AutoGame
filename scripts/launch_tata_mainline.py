"""Visible first-run dependency setup; keep normal workbench launches quiet."""
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    try:
        options=sys.argv[1:]
        assistant=bool(options and options[0]=='--assistant')
        if assistant:options=options[1:]
        feature='assistant' if assistant else 'mainline'
        missing = []
        for module in ('PIL', 'lupa', 'google.protobuf', 'cv2', 'numpy'):
            try:
                found = importlib.util.find_spec(module)
            except ModuleNotFoundError:
                found = None
            if found is None:
                missing.append(module)
        if missing:
            print('首次启动：正在安装塔塔辅助器依赖，请保持此窗口打开…', flush=True)
            requirements=['-r',str(ROOT / 'games/tata/mainline/requirements.txt')]
            if assistant:requirements+=['-r',str(ROOT / 'games/tata/requirements.txt')]
            subprocess.run([sys.executable, '-m', 'pip', 'install', *requirements], check=True)
        executable = Path(sys.executable)
        windowless = executable.with_name('pythonw.exe')
        subprocess.Popen([str(windowless if windowless.exists() else executable),
                          '-X', 'utf8', str(ROOT / 'run.py'), 'tata', feature, *options], cwd=ROOT)
    except Exception as exc:
        print(f'塔塔工具启动失败：{exc}', flush=True)
        input('按回车关闭；可以复制上面的错误信息。')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
