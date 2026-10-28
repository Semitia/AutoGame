"""Dispatch Tata game features: python run.py tata fishing [options]."""
import argparse
from pathlib import Path
import runpy
import sys

FEATURES = {name: Path(__file__).resolve().parent / name for name in ('fishing', 'mainline')}


def main():
    parser = argparse.ArgumentParser(description='Tata / 塔塔冒险队 game features')
    parser.add_argument('feature', choices=FEATURES)
    parser.add_argument('feature_args', nargs=argparse.REMAINDER,
                        help='Fishing options; put --panel first to open the control panel')
    args = parser.parse_args()
    options = args.feature_args
    panel = bool(options and options[0] == '--panel')
    if panel:
        options = options[1:]
    entry = FEATURES[args.feature] / ('panel.py' if panel or args.feature == 'mainline' else 'desktop.py')
    sys.path.insert(0, str(entry.parent))
    sys.argv = [str(entry), *options]
    runpy.run_path(str(entry), run_name='__main__')


if __name__ == '__main__':
    main()
