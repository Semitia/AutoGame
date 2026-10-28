# 主线数据与离线运行研究

当前已有本地 Tkinter 工作台与启发式布阵基线；同时具备 APK 拆包、全量解码、配置 JSON 导出与关卡关联工具。`probe_headless.py` 可在无 Unity 环境中调用原始战斗字节码的部分方法。完整战斗、胜负校准和基于模拟的 policy 尚未完成。

## 可视化工作台

双击根目录 `Start-Tata-Mainline.cmd`，或 `python run.py tata mainline`。本机数据已准备；新环境需要按下方流程生成数据，面板依赖 Tkinter 与 Pillow。

1. 顶部只编辑一次“共享等级”，所有卡片同步显示相同等级。角色池 schema v2 将其存为顶层 `shared_level`，单只宠物不再保存 level。
2. “塔塔图鉴 / 角色池”默认列出所有宠物图片；按原游戏职业、元素筛选，可组合搜索中文名、形态名、英文代号和编号，或只看已拥有。卡片底部快速收入/移出，点击图片编辑，进化阶段通过形态缩略图切换。当前数据包含 68 种 Enable=true、UnitType=1 的宠物。
3. 本机保存 `runtime/tata/mainline/roster.json`，上次版本备份为 `roster.previous.json`，支持 JSON 导入/导出。旧 v1 的等级一致时自动迁移；不一致时弹出共享等级输入框，需要用户确认，取消则保留原文件并禁止覆盖。属性可留空，装备暂以备注记录。
4. “地图布阵”：输入关卡名称如 `1-1`、`11-26` 或数字 ID。按 StageBattle.ResID → StageBattleRes.BackgroundRes 加载实际贴图。上方按波次配置 Cols 汇总各列可能出现的敌人图标，并显示敌人等级；不是逐帧波次回放。
5. 从已拥有图片区拖到格子上阵，地图内拖动移动/交换；拖回图片区或右键下阵。也支持点卡片再点格子。约束检查与 UI 分离，非法拖放不修改原方案。布局适配原贴图，逻辑 x/y 保持原值，UI 像素映射不是原 Unity 相机坐标。
6. 可生成候选、手动调整，再保存布阵。方案附带角色池快照、数据版本、策略来源及 `simulated:false`。地图上的宠物目前用原头像图，不是 Spine 动画。

启发式 v1 使用有界束搜索选择宠物，每种至多一只，遵守可用宠物及上阵数量限制。偏好分 = 单宠物之和（2 × 稀有度编号 + 3 × 按敌人数加权的克制覆盖 − 2 × 弱势覆盖）+ 0.5 × 元素种类数。等级为共享字段，不用于宠物间排名。进化用于查当前稀有度；这是人工设定的搜索基线，**不是伤害公式、胜率或全局最优证明**。位置顺序填充，没有优化前后排、射程或弹道；星级、技能等级、装备和面板属性目前只保存。空 GridY 等未知约束明确拒绝生成位置。

角色池及图标均位于已忽略的 runtime。可选的本机头像提取：

```powershell
python -m pip install UnityPy==1.25.3
python games/tata/mainline/extract_icons.py runtime/tata/research/inpackage_aa_1.lpak --out runtime/tata/mainline/icons
python games/tata/mainline/extract_icons.py runtime/tata/research/inpackage_aa_1.lpak --data runtime/tata/research/data-bytecode-0.50.1 --out runtime/tata/mainline/art
```

扩展提取遍历 4,529 个 UnityFS bundle，得到 1,006 张本地图片，无解析错误，95 个引用资源未找到，清单见 `art/icon-report.json`。包括原宠物/敌人头像、职业/元素图标、品质框与第一章三张地图。其他章地图未包含于本次 APK 资源包，显示缺失提示和原逻辑格子，不拿其他地图替代；取得对应 PNG 后按引用文件名放入 art 即可加载。游戏资源不随仓库分发。

## 交互原则与客户端内嵌

用户要求优先复用原游戏已有的资源、布局和操作习惯，新增分析功能应建立在熟悉的图鉴、筛选、地图布阵之上，已写入仓库 AGENTS.md。共享等级已在 `Src/game_base1.lua` 的 PetModel.GetPetLevel → `_level` 读取逻辑中核实；该文件的反编译源码只用于定位，字节码仍是运行基准。

“脚本包解开”不代表完整客户端运行环境恢复。资源复用、原 Lua 逻辑复用和运行完整 Unity/微信客户端是三个层次。目前实现前两者中的资源 UI 与局部逻辑探测。完整客户端还依赖 native runtime、Unity 类型、Spine/动画与资源加载、平台桥接和账号服务；嵌入窗口本身也不会提供角色池数据接口。这些依赖未验证前不承诺可内嵌游戏或自动同步账号。

## 研究工具

完整证据、版本来源与限制见 [MAINLINE-RESEARCH.md](../docs/MAINLINE-RESEARCH.md)。下载包、参考库、密钥、游戏源码和数据输出均保留于忽略目录，不入库。以下命令从仓库根目录运行，Python 3.10+；批量反编译另需 JDK 17 和本地 unluac.jar。

```powershell
python -m pip install -r games/tata/mainline/requirements.txt
python games/tata/mainline/inspect_apk.py runtime/tata/research/tata-0.50.1.apk --out runtime/tata/research/inventory --extract
python games/tata/mainline/decode_package.py runtime/tata/research/tata-0.50.1.apk --reference-lib runtime/tata/research/overseas-0.31.11/libigame.so --out runtime/tata/research/decoded-0.50.1

javac -cp .local/unluac.jar -d .local games/tata/mainline/DecompileBatch.java
java -Xmx1500m -cp ".local;.local/unluac.jar" DecompileBatch runtime/tata/research/decoded-0.50.1 runtime/tata/research/source-0.50.1
python games/tata/mainline/verify_lua.py runtime/tata/research/source-0.50.1 --out runtime/tata/research/source-validation.json
python games/tata/mainline/verify_lua.py runtime/tata/research/decoded-0.50.1 --out runtime/tata/research/bytecode-validation.json

python games/tata/mainline/export_config.py runtime/tata/research/decoded-0.50.1 --out runtime/tata/research/data-bytecode-0.50.1
python games/tata/mainline/build_dataset.py runtime/tata/research/data-bytecode-0.50.1 --out runtime/tata/research/dataset-bytecode-0.50.1
python games/tata/mainline/probe_headless.py runtime/tata/research/decoded-0.50.1 --out runtime/tata/research/headless-probe.json
python -m unittest discover -s games/tata/mainline -p "test_*.py" -v
```

`verify_lua.py` 只编译校验，不执行 chunk。反编译器退出码成功不保证源码语法/语义正确，应以原始字节码作为运行基准。

`export_config.py` 支持 `.luae` 字节码或 `.lua` 文本，单独的 Lua VM 限制内存与指令数，只提供 `config` 环境；这是研究隔离措施，不是针对恶意 Lua/VM 漏洞的安全边界。无法转换成纯数据的配置会记录错误，最终返回非零；可用输出仍保留。数值/布尔键转为字符串，空表保留为 `{}`，不猜测数组；遇到键冲突、函数等拒绝转换。当前 44 个非纯数据/需要其他环境的配置未导出，不能默认为空配置。

`build_dataset.py` 输出 `stages.json` 汇总、每个关卡的 `stage-ID.json` 及缺失关联报告，保留原始字段与源路径。Frame 保持配置值，没有假设它与秒之间的换算，也没有为缺失格子信息猜测默认值。

`probe_headless.py` 捕获合并包里的模块初始化函数，跳过整包的自动初始化，仅运行版本、数学、基础模块、战斗模块和引擎初始化。它使用最小 class 适配器与记录调用的系统替身，只验证真实 Tick 的调度次序；没有生成战斗结果。
