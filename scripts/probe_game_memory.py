"""Read-only Bilibili mini-game process probe. Never enables root or writes memory."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def run(adb, device, *args):
    result = subprocess.run([adb, '-s', device, *args], capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace').strip())
    return result.stdout


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--device', required=True)
    p.add_argument('--adb', default='C:/Program Files/NetEase/MuMu/nx_main/adb.exe')
    p.add_argument('--read-address', type=lambda x: int(x, 0))
    p.add_argument('--size', type=int, default=4096)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    if not 1 <= args.size <= 65536:
        p.error('size must be 1..65536')
    def shell(command):
        return run(args.adb, args.device, 'shell', command).decode('utf-8', 'replace')
    focus = shell('dumpsys window')
    if not re.search(r'mCurrentFocus=.*tv\.danmaku\.bili/.*GameContainerActivity', focus):
        raise RuntimeError('Foreground is not the Bilibili mini-game container')
    pids = shell('pidof tv.danmaku.bili:web').split()
    if len(pids) != 1 or not pids[0].isdigit():
        raise RuntimeError('Expected one live Bilibili game process')
    pid = int(pids[0])
    cmdline = run(args.adb, args.device, 'exec-out', f'cat /proc/{pid}/cmdline').split(b'\0')[0]
    if cmdline != b'tv.danmaku.bili:web':
        raise RuntimeError('Process identity changed')
    maps = shell(f'cat /proc/{pid}/maps')
    if not re.search(r'^[0-9a-f]+-[0-9a-f]+ ', maps, re.M):
        raise RuntimeError('Memory maps unavailable; root was not enabled by this tool')
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'maps.txt').write_text(maps, encoding='utf-8')
    summary = {'process':'tv.danmaku.bili:web', 'pid':pid, 'maps_readable':True,
               'root':shell('id -u').strip() == '0', 'semantic_fields_verified':False}
    if args.read_address is not None:
        start = args.read_address
        valid = False
        for line in maps.splitlines():
            fields = line.split()
            lo, hi = [int(x,16) for x in fields[0].split('-')]
            if fields[1].startswith('r') and lo <= start and start + args.size <= hi:
                valid = True
                break
        if not valid:
            raise RuntimeError('Requested range is not inside a readable mapping')
        # Page-sized seek avoids traversing the whole address space.
        page = start // 4096
        offset = start % 4096
        count = (offset + args.size + 4095)//4096
        data = run(args.adb, args.device, 'exec-out',
                   f'dd if=/proc/{pid}/mem bs=4096 skip={page} count={count} 2>/dev/null')
        data = data[offset:offset+args.size]
        if len(data) != args.size:
            raise RuntimeError('Short memory read')
        summary.update(read_address=hex(start), bytes_read=len(data), sha256=hashlib.sha256(data).hexdigest())
        # Intentionally do not persist or print raw process memory.
    (args.out/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
