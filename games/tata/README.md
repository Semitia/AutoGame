# Tata / 塔塔冒险队

本目录提供 Windows 官方微信客户端里的塔塔冒险队辅助器，将[主线工作台](mainline/README.md)、[钓鱼大赛](fishing/README.md)和[围猎臭臭](hunting/README.md)放在同一个窗口。

新增[围猎臭臭](hunting/README.md)：低倍攒锁定、可用狂暴提速，200倍等待萨满并锁定，跟踪目标结束即退出。工作台默认后台、按窗分账号页签，可同时辅助不同内容，游戏窗口不可最小化；双开时不会猜选账号。已实测200倍萨满、后台2倍鱼怪完整循环及后台1倍补锁定。1倍瞄准密集怪群、可开狂暴；现有锁定用完才回1倍补到10个。主线/钓鱼新后台接口仅完成离线验证，狂暴补货和长期稳定性继续观察。实际自动操作由用户主动启动。

主线功能已有[本地可视化工作台](mainline/README.md)，双击根目录 `Start-Tata-Mainline.cmd`，或运行 `python run.py tata mainline`。支持原游戏图鉴/地图、共享等级、角色池只读同步、拖放布阵、原 Lua 战斗模拟与经验搜索，以及实验性自动布阵和连续推关。默认按当前窗口与原图自动识别布局，详情及模拟限制见主线说明。[离线研究记录](docs/MAINLINE-RESEARCH.md)包含数据来源与限制。

## 启动

双击仓库根目录 **`Start-Tata.cmd`**，或运行 `python run.py tata`。总览、主线工作台、自动钓鱼和围猎臭臭使用左侧导航切换，页面保留已输入内容、阵容和任务状态。主线继续使用已有账号档案、共享等级、原图图鉴与地图拖放；小游戏提供启停、设置、计数和日志。

顶部“停止全部任务”请求停止自动推关、钓鱼、围猎和当前本地搜索，也向单独启动的 Tata 自动操作发送停止信号。关闭窗口仅停止本窗口启动的任务，等待搜索保存进度后退出。已开始的主线战斗会自行继续结算，围猎会请求退出。三个模块的自动输入共用窗口控制锁，即使从旧入口启动也不能同时控制同一窗口；本地搜索可和小游戏同时运行。总览只展示本窗口管理的任务，不会接管已有独立面板。

旧入口 `Start-Tata-Mainline.cmd`、`Start-Fishing.cmd` 和原命令仍可用：

```powershell
python run.py tata assistant --page mainline
python run.py tata fishing --panel
python run.py tata fishing --activate --casts 10 --seconds 600
python run.py tata fishing --observe --seconds 30
```

Windows 环境依赖 Python 3.10+、Tkinter（控制面板）及以下库：

```powershell
python -m pip install -r games/tata/requirements.txt
```

## 目录

```text
games/tata/
  run.py                 游戏功能分发入口
  assistant.py           统一窗口、功能导航、任务状态与停止协调
  requirements.txt       Tata 所需依赖
  fishing/               钓鱼控制面板、识别、预判、输入和测试
    assets/              识别模板，纳入版本控制
    testdata/            回归测试使用的截图，纳入版本控制
  docs/                  游戏相关调查与说明
runtime/tata/fishing/     日志、截图、采样和停止信号，不入库
```

新增 Tata 功能时在本目录建立独立子目录，并在 `run.py` 注册。旧运行证据仍留在本机 `runtime/fishing-desktop/`，无需迁移或提交。

验证命令（仅回放截图和模拟输入接口，不操作游戏）：

```powershell
python -m unittest discover -s games/tata/fishing -p "test_*.py" -v
python -m unittest discover -s games/tata -p "test_assistant.py" -v
```

账号受限事件的背景和证据边界见[调查记录](docs/FISHING-INVESTIGATION.md)。
