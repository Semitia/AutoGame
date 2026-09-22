# 蔚蓝星球：战术与运行

真实游戏名已确认是《永远的蔚蓝星球》，保留旧目录名以兼容旧入口。新入口 `run.py blue_planet` 使用通用战术；旧 `bilibili_hero_merge` 仍使用原第34关配置。

## 指定四个位置

编辑 `games/bilibili_hero_merge/tactics/beginner.json`（新号）或复制一份。`veteran.json` 是原大号阵容。`slots` 顺序默认也是角色 buff 优先级；同一英雄内部可设置 `buff_order`。新增英雄只需在 `heroes.json` 加名称和 buff 关键词。

| 字段 | 含义 |
| --- | --- |
| `hero` | `heroes.json` 中的英雄标识 |
| `role: damage` | 有空位保留，满格且需要召唤时才参与合成 |
| `role: control/support` | 默认保留阈值2，超出时优先合成低阶 |
| `reserve` | 控制/辅助合成触发阈值，可覆盖默认值；因合成随机变角色，不保证合成后的数量 |
| `min_remaining` | 合成消耗两只后仍至少保留几只同角色；默认0，小炮配置为1 |
| `buff_order` | 这个英雄内部的可选强化顺序；不设置则同角色左侧优先 |
| `buff_priority` | 可选，覆盖四位置默认优先级；必须列齐4个角色 |
| `price_ratio` | 下一次强化费与下一次召唤费比值，默认2:1；相等召唤 |

支持1输出3辅助、3输出1辅助等组合，不按英雄名字固定职责。低阶合成优先；未知阶级不合成；四阶额外选卡也按关键词优先级。开局先召唤5次以解锁强化。每5次召唤新增格子需要图像确认。

## 运行

以下用 `python` 代指项目配置的 Python，需已有仓库依赖。新号当前设备实测 `emulator-5556`，不能默认用旧大号的 `emulator-5554`；每次运行前用 ADB devices 确认。

```powershell
# 从指定关卡首页打一局，停在结算页
python run.py blue_planet --device emulator-5556 --stage 2 --tactics games/bilibili_hero_merge/tactics/beginner.json --start-home --runs 1

# 同一关循环三局（总时间上限30分钟）
python run.py blue_planet --device emulator-5556 --stage 2 --tactics games/bilibili_hero_merge/tactics/beginner.json --start-home --runs 3 --minutes 30

# 清体力，低于10停止；仍有120分钟总上限，不补体力
python run.py blue_planet --device emulator-5556 --stage 2 --tactics games/bilibili_hero_merge/tactics/beginner.json --start-home --until-stamina --minutes 120

# 从同一局暂停状态恢复：使用该次日志目录中的准确文件路径
python run.py blue_planet --device emulator-5556 --stage 2 --tactics games/bilibili_hero_merge/tactics/beginner.json --resume-state runtime/bilibili_hero_merge/runs/<本局目录>/state.json
```

`--empty-board` 可从当前关卡空阵容接管。`--stop-on-loss` 可让循环在首次失败后结束。单局是默认行为。循环会返回同关；若首页自动前进一关，尝试可见左箭头选回并重新核对。复杂选关、教程、未知弹窗停止后由上层处理，不盲点。自动后退选关目前需更多实测。

停止：创建 `runtime/bilibili_hero_merge/STOP`；脚本在可确认的战斗画面暂停并保存。再次启动前检查停止原因，确认继续再删除这个文件。手动暂停也会停止脚本。原启动器仍指向旧入口，尚未改成新号入口。

## 状态与验证边界

每次运行独立写入 `runtime/bilibili_hero_merge/runs/<时间>/`，包含 `events.jsonl`、`state.json`、`latest.png`、抽样和结算图。与旧大号根目录状态隔离，仍共用运行锁防止同时操作。恢复核对设备、关卡、战术指纹，拒绝已结算状态；不得手动改变棋盘后恢复旧状态。战术变更应在下一局使用。

费用以OCR为准；小额战斗币用多裁剪一致性复核，修复90误读9的问题。英雄阶级依赖已验证动作，不是独立视觉模型。不要把单局通过当成长期无人值守已验证。循环次数、体力不足、错误关卡、恢复隔离有单元测试；实战证据与账号状态见 `docs/BLUE-PLANET-MEMORY.md`。
