"""Cross-runner, per-device lease independent of account runtime directory."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[3]


def assert_no_legacy_controller(device):
    if os.name!='nt':
        return
    command="Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    output=subprocess.check_output(['powershell','-NoProfile','-NonInteractive','-Command',command],
                                   timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
    rows=json.loads(output.decode('utf-8-sig').strip() or '[]')
    if isinstance(rows,dict):rows=[rows]
    for row in rows:
        cmd=row.get('CommandLine') or ''
        if row['ProcessId'] in (os.getpid(),os.getppid()):continue
        if any(name in cmd for name in ('run.py','strategic.py','tactical.py','coop.py')):
            # Explicitly addressed other devices are allowed. Legacy default
            # invocations are ambiguous and must be stopped before this runner.
            if device in cmd or '--device' not in cmd and '--host-device' not in cmd and '--guest-device' not in cmd:
                raise RuntimeError(f'Possible existing controller PID {row["ProcessId"]} for {device}')


@contextmanager
def device_lease(device, directory=None, check_processes=True):
    if not device or any(c.isspace() for c in device):
        raise ValueError('Explicit ADB serial required')
    root=Path(directory) if directory else ROOT/'runtime'/'device-locks'
    root.mkdir(parents=True,exist_ok=True)
    path=root/(hashlib.sha256(device.encode()).hexdigest()+'.lock')
    with path.open('a+b') as stream:
        if path.stat().st_size==0:
            stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError(f'Device already controlled: {device}') from error
        try:
            if check_processes:assert_no_legacy_controller(device)
            yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)
