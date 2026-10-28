# Tata / 塔塔冒险队

本目录按游戏组织功能。目前包含 Windows 官方微信客户端里的[钓鱼大赛自动化](fishing/README.md)。

主线功能已有[本地可视化工作台](mainline/README.md)，双击根目录 `Start-Tata-Mainline.cmd`，或运行 `python run.py tata mainline`。支持手动维护角色池、宠物头像、关卡查看、手动布阵与启发式候选。完整战斗模拟和经过胜负验证的 policy 尚未完成。[离线研究记录](docs/MAINLINE-RESEARCH.md)包含数据来源与限制。

## 启动

双击仓库根目录 `Start-Fishing.cmd` 打开钓鱼控制面板，点击按钮启停。也可从统一入口运行：

```powershell
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
```

账号受限事件的背景和证据边界见[调查记录](docs/FISHING-INVESTIGATION.md)。
