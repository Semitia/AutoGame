# AutoGame

以截图、输入和可恢复状态驱动的游戏自动化项目。目前包含 **MuMu +《永远的蔚蓝星球》** 和 **Windows 微信 + Tata（塔塔冒险队）**。蔚蓝星球保留旧目录标识 `bilibili_hero_merge`，原大号第34关入口继续可用，并提供 `blue_planet` 四位置战术入口。

- [双人合作：单局候选版，待实战验收](games/bilibili_hero_merge/COOP.md)
- [Tata 游戏功能与钓鱼工具](games/tata/README.md)
- [游戏接手备忘](docs/BLUE-PLANET-MEMORY.md)
- [四位置战术与单局/循环](docs/TACTICAL-RUNNER.md)
- [本轮工作总结](docs/SESSION-2026-09-18.md)
- [架构及扩展约定](docs/ARCHITECTURE.md)
- [运行与恢复说明](docs/RUNBOOK.md)
- [当前游戏策略](games/bilibili_hero_merge/README.md)

## 环境与启动

**Tata 主线工作台：双击 `Start-Tata-Mainline.cmd`。** Python 3.10+ 环境下，首次自动安装依赖并从仓库自带资源包准备关卡、模拟引擎和基础图片；换电脑无需旧电脑文件。登录新账号后在面板同步角色池，详见[主线说明](games/tata/mainline/README.md)。

**Tata 自动钓鱼：双击 `Start-Fishing.cmd` 打开启停面板。** 先在电脑微信里打开「塔塔冒险队 → 钓鱼大赛」；命令行入口为 `python run.py tata fishing`，详见 [Tata 说明](games/tata/README.md)。

**推荐桌面入口：双击 `Start-GUI.cmd`。** 中文界面支持主线挑战和双人合作（34关直接在主线里选择），自动发现在线设备，提供四位置阵容编辑、配置方案自动缓存、启动/停止和日志。详见 [GUI 使用说明](docs/GUI.md)。

当前实现针对 Windows、MuMu Android 15、1080×1920 Android 分辨率。默认设备为 `emulator-5554`，MuMu 实例索引为 0。

```powershell
py -3 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe run.py bilibili_hero_merge --hide --runs 1 --minutes 15
```

按需将 `config/local.example.json` 复制为 `config/local.json`，修改 Python、ADB 和 MuMuManager 路径。本机迁移版已保留忽略跟踪的本地配置和依赖；不需要重新安装便可使用根目录启动器。优先使用上述虚拟环境作为其他机器的安装方式。

先把游戏留在第 34 关首页，再双击 `Test-One.cmd` 测一局，或 `Start-Hidden.cmd` 后台清体力。`Stop.cmd` 请求停止并显示游戏。清体力模式胜负都继续，首页体力不足 10 时退出，不购买、不看广告补充体力。

## 验证

```powershell
.venv/Scripts/python.exe -m unittest discover -s games/bilibili_hero_merge -p "test_*.py"
```

已有单局满血胜利和跨局连续运行证据。仍是游戏专用原型：阶级主要依赖操作历史，未知弹窗/设备异常可能停止，不保证全胜；没有实测体力耗尽自动停止的最终记录。

## 布局

```text
src/autogame/platforms/   平台协议与 MuMu 截图、触摸、窗口接口
games/bilibili_hero_merge/  识别、策略、状态机、模板及测试
games/tata/              Tata 游戏入口；fishing/ 为钓鱼子功能
config/                  配置示例；local.json 不入库
scripts/                 Windows 启动器
docs/                    工作总结、架构、运行手册和历史文档
runtime/                 当前日志与状态，不入库
local_archive/           迁移前现场、历史日志和采集材料，不入库
.local/                  本机依赖缓存，不入库
```

游戏截图与模板仅用于兼容性验证，相关游戏素材权利属于原权利人。仓库暂未选择代码开源许可证。
