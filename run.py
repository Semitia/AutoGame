"""Entry point: python run.py bilibili_hero_merge [runner options]."""
import argparse
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parent
GAMES={'bilibili_hero_merge': ROOT/'games/bilibili_hero_merge/strategic.py',
       'blue_planet': ROOT/'games/bilibili_hero_merge/tactical.py'}

def main():
    parser=argparse.ArgumentParser(description='AutoGame game runner')
    parser.add_argument('game', choices=GAMES)
    parser.add_argument('runner_args', nargs=argparse.REMAINDER)
    args=parser.parse_args()
    entry=GAMES[args.game]
    sys.path.insert(0,str(entry.parent))
    sys.argv=[str(entry),*args.runner_args]
    runpy.run_path(str(entry),run_name='__main__')

if __name__=='__main__': main()
