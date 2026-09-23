# 小游戏运行时数据探测

实测日期：2026-09-22。只读探测，没有改游戏数据、注入脚本或开启战斗。

## 正确入口

用户确认：打开哔哩哔哩，点击左上角头像，再点游戏图标进入永远的蔚蓝星球。不能按已安装包名猜测目标。先前误打开 com.yydwlxqcy89.cs 的探测不代表本游戏。

## 实测结果

- MuMu实例1，本次设备 127.0.0.1:16416。必须每次通过 MuMuManager info 确认端口。
- 前台 activity 为 tv.danmaku.bili/com.bilibili.lib.fasthybrid.game.scenarios.game.ui.GameContainerActivity0。
- 游戏所在进程 tv.danmaku.bili:web，本次 PID 4631，PID不可复用。
- UIAutomator 仅提供容器及小游戏中心/更多/关闭按钮，没有游戏内按钮、数值和棋盘节点。
- 普通 shell 的 run-as 被非debuggable限制，maps/mem读取被拒绝；没有发现 DevTools socket。
- MuMu root_permission 配置显示false，但 adb root实际成功；id为uid=0，maps可读。没有修改MuMu配置、重启游戏或安装注入工具。本次adbd保留root状态。
- 从一个已映射可读页读取4096字节成功；这页属于Dalvik空间，只证明进程内存读取能力，不能当成WASM堆或游戏数据。工具不保存原始字节。
- 已下载到 runtime/probe 的当前加载框架包含 wasmMemory、HEAPU8；实例导出 Module.asm.Sr 指向 wasmMemory。确认是Unity WebGL/WASM路线，而非原生libil2cpp路线。
- 当前已加载资源目录 appTempLinks/13346241，小游戏资源标识 biligamec5646e1d746db4f6；基址/目录/导出名都可能随版本变化。
- 尚未定位WASM线性内存基址、玩家体力/金币/关卡、棋盘英雄与阶级字段；没有实现语义数据读取。

## 工具

scripts/probe_game_memory.py：必须显式设备，验证前台小游戏容器、进程名与可读映射；最多读取64KiB，输出长度和哈希，不写进程内存、不自动提权。动态地址必须从当次maps选择。

实测正确映射读取4096字节成功，无效地址0被拒绝。证据 runtime/probe/verified/summary.json。

## 后续路线

1. 固定日常用本地页面状态机：定义已确认的页面锚点、按钮区域、前置条件和下一状态；短暂动画由本地轮询等候；遇未知弹窗停下报告。不要让代理每次点击都参与，也不要盲录坐标宏。
2. 游戏状态读取优先研究当前加载框架和WASM线性内存定位。只读字段需与画面多次交叉验证，必须区分静态配置、缓存和实时对象。
3. 若后续需要运行时挂钩以取得WASM buffer，另行实施并记录；本次没有部署Frida或hook，也没有绕过检测。
4. 现有战斗耗时包含每次点击启动adb进程及召唤后开详情OCR。识别改成局部缓存/事件驱动、输入改为持久连接均可独立改进，尚未实施。

## 2026-09-22 后续实测

- 当前进程4631中发现900MiB匿名rw映射，基址0x4600000000，与框架INITIAL_MEMORY=943718400一致。
- 解压当前WASM代码，解析22294个数据段；选取6个非平凡128字节静态片段，内存base+offset与编译数据全部逐字节一致。证据runtime/probe/wasm-evidence.json。这比仅按映射大小猜测强，但地址仍仅适用于本次进程。
- 解压UnityWebData1.0资源容器，提取11782392字节global-metadata.dat。头部不符合普通metadata头，暂不假定可直接用标准解析器。
- 找到BattleData、currentSummonCount、dicHeroStar等候选名称；名称属于静态线索，不是实时字段值。未得到对象实例与字段偏移。
- 本次没有内存写入、hook、修改资源或启动战斗。仍需定位活跃对象并对多次状态变化进行语义验证。
- 参考方向：Airtest官方文档（图像自动化）、Poco官方仓库（引擎UI层级，需要游戏侧SDK支持）、Frida官方API（读内存/动态观测）、Emscripten官方preamble.js文档（HEAP视图）、mitmproxy官方Features（协议观测）。不把hook视作完全无侵入读取，不将只读自动化默认等同于平台许可。
