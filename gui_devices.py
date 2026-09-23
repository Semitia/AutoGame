"""Read-only discovery: match ADB transports to MuMu windows by live boot identity."""
from concurrent.futures import ThreadPoolExecutor
import json
import re
import subprocess

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
BOOT_FILE = '/proc/sys/kernel/random/boot_id'
UUID = r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}'


def run_text(args, timeout=8):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=timeout, creationflags=NO_WINDOW)
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or '设备查询失败')
    return result.stdout


def parse_online(raw):
    return list(dict.fromkeys(line.split()[0] for line in raw.splitlines()
                             if len(line.split()) > 1 and line.split()[1] == 'device'))


def parse_boots(raw):
    """MuMu sh output uses one '### mumu-N ###:' header per instance."""
    return {index: boot.lower() for index, boot in
            re.findall(r'###\s*mumu-(\d+)\s*###:\s*(' + UUID + r')\b', raw)}


def match_names(serials, instances, instance_boots, serial_boots):
    labels, identities = {}, {}
    for serial in serials:
        boot = serial_boots.get(serial, '')
        matches = [index for index, value in instance_boots.items()
                   if boot and value == boot and index in instances]
        # Cloned/ambiguous identities must never be assigned by list order or emulator port.
        if len(matches) != 1:
            continue
        index = matches[0]
        name = instances[index].get('name') or 'MuMu'
        labels[serial] = f'{name} · 实例 {index}（{serial}）'
        identities[serial] = index
    return labels, identities


def discover_devices(adb, manager):
    raw = run_text([adb, 'devices', '-l'], 15)
    serials = parse_online(raw)
    result = dict(raw=raw, serials=serials, labels={}, identities={}, note='')
    if not serials or not manager:
        return result
    try:
        info = json.loads(run_text([manager, 'info', '-v', 'all']))
        instances = {str(v.get('index', key)): v for key, v in info.items()
                     if isinstance(v, dict) and v.get('is_android_started')
                     and re.fullmatch(r'\d+', str(v.get('index', key)))}
        if not instances: return result
        boot_raw = run_text([manager, 'sh', '-v', ','.join(instances), '-c', 'cat ' + BOOT_FILE])
        instance_boots = parse_boots(boot_raw)

        def read_boot(serial):
            try:
                value = run_text([adb, '-s', serial, 'shell', 'cat', BOOT_FILE], 4).strip().lower()
                return serial, value if re.fullmatch(UUID, value) else ''
            except (OSError, ValueError, subprocess.TimeoutExpired):
                return serial, ''

        with ThreadPoolExecutor(max_workers=min(4, len(serials))) as pool:
            serial_boots = dict(pool.map(read_boot, serials))
        result['labels'], result['identities'] = match_names(serials, instances, instance_boots, serial_boots)
        if len(result['labels']) < len(serials):
            result['note'] = '部分设备未能核对模拟器名称，保留原编号'
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
        result['note'] = '模拟器名称暂不可用：' + str(error)
    return result
