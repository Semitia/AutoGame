# 运行、恢复与排错

## 启动器

| 文件 | 行为 |
| --- | --- |
| Test-One.cmd | 单局，最多 15 分钟 |
| Farm.cmd | 前台控制台，持续清体力 |
| Start-Hidden.cmd | 隐藏游戏和脚本窗口，持续清体力 |
| Resume.cmd | 从本机运行状态恢复同一局并继续清体力 |
| Stop.cmd | 写 STOP 请求，尝试暂停并显示游戏 |
| Show-Game.cmd | 只显示模拟器窗口 |

首次启动在第 34 关首页。`Resume` 只适用于本项目保存的同一局，不能手动改变阵容或重开后继续使用旧状态。迁移前状态只放入归档，未装载为新项目的活动状态。重复启动有文件锁防护。

模拟器可隐藏，电脑不可休眠；不要同时手动操作游戏。清体力没有总时长/局数上限，自然恢复的体力也会继续消耗，直到首页读数小于 10。脚本不会主动补体力。

## 本机配置

`config/local.json` 不受 Git 跟踪。Python 启动器优先级为 `AUTOGAME_PYTHON`、本机配置、`.venv/Scripts/python.exe`、PATH 的 Python。MuMu 路径可由 `AUTOGAME_ADB`、`AUTOGAME_MUMU_MANAGER`、`AUTOGAME_MUMU_INDEX` 覆盖；设备序列号通过 `--device` 指定。

## 运行产物

`runtime/bilibili_hero_merge/state.json` 是棋盘记录；同目录的 `runs/<时间>/events.jsonl` 是决策日志，`latest.png`、抽样截图与结算截图用于诊断。隐藏启动器的控制台输出在 `runtime/stdout.log` 和 `runtime/stderr.log`。

## 异常行为

- 角色或动作无法确认：开启增量修复，其他可做操作继续。
- 价格读取失败：暂缓消费并重读，不猜价格。
- 未知阶级：保留占位但不合成。
- 文件暂时不可写：重试并延后保存，不因该错误暂停战斗。
- 无法识别的界面、设备异常、其他未捕获异常：仍可能停止，保留日志。
- 不明停止先看 `stopped`、`exception`、`stamina_exhausted`，不能仅凭窗口不动判断体力清完。

迁移没有启动新的刷关或消耗体力。历史现场在 `local_archive/session-2026-09-18/`，原工作目录作为备份保留；今后统一从新项目运行。
