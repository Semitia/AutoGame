"""Join exported mainline stage definitions with waves and units; no combat estimates."""
import argparse
from collections import Counter
import json
from pathlib import Path


def build(data: Path, out: Path):
    def table(name):
        return json.loads((data / 'Config' / f'{name}.json').read_text(encoding='utf-8'))[name+'Table']

    stages, battles, units = table('Stage'), table('StageBattle'), table('Unit')
    out.mkdir(parents=True, exist_ok=True)
    summaries, errors = [], []
    for key, stage in sorted(stages.items(), key=lambda x: int(x[0])):
        try:
            battle = battles[str(stage['BattleID'])]
            name = battle['BattleName']
            if Path(name).name != name or ':' in name or '\\' in name or name in ('.', '..'):
                raise ValueError('Unsafe battle name')
            wave_path = data / 'Config/StageBattle' / f'{name}.json'
            waves = json.loads(wave_path.read_text(encoding='utf-8'))['StageBattle'][name+'Table']
            enemies = Counter()
            frames = []
            for frame, event in waves['Frame'].items():
                frames.append(int(frame))
                for wave in event.get('Waves', {}).values():
                    enemy = str(wave['EnemyID'])
                    if enemy not in units:
                        raise ValueError(f'Missing enemy unit {enemy}')
                    enemies[enemy] += wave['Num']
            detail = dict(stage=stage, battle=battle, waves=waves,
                          enemy_units={k: units[k] for k in enemies},
                          source_paths=['Config/Stage.luae', 'Config/StageBattle.luae',
                                        f'Config/StageBattle/{name}.luae', 'Config/Unit.luae'])
            (out / f'stage-{key}.json').write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding='utf-8')
            summaries.append(dict(id=stage['ID'], name=stage['DisplayName'], battle_name=name,
                                  deploy_limit=waves.get('CanDeployNum'), columns=waves.get('ColumnCount'),
                                  grid_y=waves.get('GridY'), enemies=dict(enemies),
                                  enemy_count=sum(enemies.values()),
                                  first_wave_frame=min(frames) if frames else None,
                                  last_wave_frame=max(frames) if frames else None))
        except (KeyError, ValueError, OSError) as exc:
            errors.append(dict(stage=key, error=str(exc)))
    report = dict(stage_rows=len(stages), joined=len(summaries), unit_rows=len(units), errors=errors,
                  limitation='APK definitions may include unavailable future stages. Frames are not converted to seconds.')
    (out / 'stages.json').write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'dataset-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = build(args.data, args.out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(bool(report['errors']))
