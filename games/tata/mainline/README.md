# 主线数据与离线运行研究

当前已有 Tkinter 工作台、已登录角色池只读同步、原始 Lua 战斗引擎的实验性本地运行，以及按模拟结果搜索阵容/站位的工具。11-26 已搜索出本地模拟通过候选，尚待用户实战校准。原生寻路与宿主接口适配仍有未验证差异，不保证实战通关。

## 可视化工作台

双击根目录 `Start-Tata-Mainline.cmd`，或 `python run.py tata mainline`。本机数据已准备；新环境需要按下方流程生成数据，面板依赖 Tkinter 与 Pillow。

1. 顶部只编辑一次“共享等级”，所有卡片同步显示相同等级。角色池 schema v3 将其存为顶层 `shared_level`，单只宠物不保存 level。
2. “塔塔图鉴 / 角色池”默认列出所有宠物图片；按原游戏职业、元素筛选，可组合搜索中文名、形态名、英文代号和编号，或只看已拥有。卡片底部快速收入/移出，点击图片编辑，进化阶段通过形态缩略图切换。当前数据包含 68 种 Enable=true、UnitType=1 的宠物。
3. 星级不再要求玩家输入总数：点“按星星 / 月亮图案选星级”，从原游戏图案中选择。每个形态的最低星级和下次进化门槛来自该宠物的 UnitEvolutionTrial；未完成试炼时可能保留较低形态，可勾选显示门槛后的图案。属性改为攻击/防御/生命的 E、D、C、B、A、S、SS、SSS 字母评级，选项按各宠物 UnitFeedLevel、当前星级及 PetFeedLevel 限制生成，保存时检查评级组合是否可达。只保留可能的养成状态，不把字母评级虚构成精确属性。
4. 本机保存 `runtime/tata/mainline/roster.json`，上次版本备份为 `roster.previous.json`，支持 JSON 导入/导出。旧 v1 等级冲突时弹框确认，取消则保留原文件并禁止覆盖。旧 v1/v2 数值属性归档到 legacy_stats；与形态不符的旧星级转为未知并保留 migration_notes，待按图案确认。未知星级/评级可留空，装备暂以备注记录。
5. “地图布阵”：输入关卡名称如 `1-1`、`11-26` 或数字 ID。按 StageBattle.ResID → StageBattleRes.BackgroundRes 加载实际贴图。上方按波次配置 Cols 汇总各列可能出现的敌人图标，并显示敌人等级；不是逐帧波次回放。部署几何已对照原字节码：GridY 实际设置横向边界，空值回退 1–5 列；纵向部署范围来自 BattleMode.DeployGrids。1-1 是中央 1 列 × 5 行，1-10 是 3 列 × 5 行，11-26 是 5 列 × 5 行；不能用 ColumnCount=5 或 GridY 的名字猜布局。
6. 从已拥有图片区拖到格子上阵，地图内拖动移动/交换；拖回图片区或右键下阵。也支持点卡片再点格子。非法拖放不修改原方案。浅色格子是部署区，远端淡格子是战场。逻辑坐标保持原值，UI 像素映射不是原 Unity 相机坐标。
7. 可生成候选、手动调整，再保存布阵。方案附带角色池快照、数据版本、策略来源及 `simulated:false`。地图上的宠物目前用原头像图，不是 Spine 动画。

启发式 v1 使用有界束搜索选择宠物，每种至多一只，遵守可用宠物及上阵数量限制。偏好分 = 单宠物之和（2 × 稀有度编号 + 3 × 按敌人数加权的克制覆盖 − 2 × 弱势覆盖）+ 0.5 × 元素种类数。共享等级不用于宠物间排名。进化用于查当前稀有度；这是人工设定的搜索基线，**不是伤害公式、胜率或全局最优证明**。星级、属性评级、技能和装备尚未进入评分，位置尚未优化。

角色池及图标均位于已忽略的 runtime。可选的本机头像提取：

```powershell
python -m pip install UnityPy==1.25.3
python games/tata/mainline/extract_icons.py runtime/tata/research/inpackage_aa_1.lpak --out runtime/tata/mainline/icons
python games/tata/mainline/extract_icons.py runtime/tata/research/inpackage_aa_1.lpak --data runtime/tata/research/data-bytecode-0.50.1 --out runtime/tata/mainline/art
```

APK 提取得到 1,006 张图片；进一步只读塔塔小游戏自己的缓存中 1,774 个 Unity bundle，补得 41 张图，包含第十一章沙漠地图、24 张星级图标、字母评级等；无解析错误。当前本地共 1,047 张图，地图有第一章三张和第十一章一张。资源来源及 bundle SHA-256 见 `art/cache-art-report.json`，不记录用户目录标识。

面板“同步本机资源”会读取本机塔塔 applet 的 `__GAME_FILE_CACHE` 中 Unity bundle，补充缺失图片，不读聊天/语音、账号存档或执行脚本。游戏里下载过其他地图后可再同步；不承诺当前缓存已包含所有章节。也可用命令行明确指定缓存目录：

```powershell
python games/tata/mainline/extract_cached_art.py --cache-root "塔塔的 __GAME_FILE_CACHE 目录" --data runtime/tata/research/data-bytecode-0.50.1 --out runtime/tata/mainline/art
```

APK 和微信缓存的 FlatBuffers 资源目录均已解析，定位到 27 个战斗背景资源地址与对应 bundle；`inspect_catalog.py` 可查询这些依赖。目录有记录不代表文件已下载；直接猜 CDN 路径的尝试返回 404，尚未还原完整远程下载流程。缺图仍明确提示。所有游戏图片留在本机，不随仓库分发。

```powershell
python games/tata/mainline/inspect_catalog.py runtime/tata/research/catalog-content.bin --out runtime/tata/research/android-map-locations.json
python games/tata/mainline/verify_rules.py --source runtime/tata/research/decoded-0.50.1 --data runtime/tata/research/data-bytecode-0.50.1 --dataset runtime/tata/research/dataset-bytecode-0.50.1 --out runtime/tata/research/rules-verification.json
```

规则对照报告验证了 6,400 个关卡的 field/deploy 矩形和 85 种星级表示，与原始字节码匹配，错误为 0。星级图案每 6 级换资源层，普通图案按新/旧颜色混排；73–78、79–84 为两组特殊图标，不能简单画 N 个同色星星。进化门槛例：11 号塔塔为 3/6/24，12 号为 6/18/30；原逻辑还有进化试炼，不能用星级唯一推断已完成的形态。

## 自动同步已登录角色池

工作台点击“从已登录游戏同步”：在电脑微信打开塔塔并完成登录，角色模型加载后即可读取，窗口可放后台或最小化。本机实测最小化状态约 6 秒读到共享 Lv.234、68 只已拥有角色，全部星级/形态/喂养等级通过当前配置校验。此结果是本次实测，不保证其他微信版本始终兼容。

读取内容包括角色编号、共享等级、星级、进化形态、精确喂养等级/进度及游戏中的 gs 原值；字母评级按对应 UnitFeedLevel 与 PetFeedAttrRank 推导。没有把 gs 当作伤害公式。角色列表来自实际 ed.PetModel.pets，并检查 isGet、数量、逐只等级和喂养归属；不是通过图鉴存在与否猜拥有状态。

同步成功后更新本机 roster.json，保留已有备注，原文件备份为 roster.previous.json。完整白名单观测保存在 runtime/tata/mainline/live-capture.json；每只的 game_observed 带读取时间，并随角色池导入/导出保留。手动编辑不会改写上次观测，后续计算须区分当前编辑值与历史观测。读取失败、模型变化、多窗口或配置不匹配时保留原角色池。

实现仅使用 Windows 的进程查询与 ReadProcessMemory 读取权限，动态定位 WebGL 内存、Lua 短字符串与表结构，再验证 class.__cname == ed.PetModel；不使用固定 PID/地址，不写内存、不注入、不发送游戏协议。读取过程中不保存整块内存，只输出允许的角色字段。不需要开启微信调试或重新登录。目前针对 Lua 5.4 wasm32 的已验证布局，更新改变布局时可能需要适配。不要在同步期间切换账号或进行养成；读取会比较两次角色观测拒绝不一致结果。

命令行仅生成并验证观测文件，不覆盖编辑角色池：

```powershell
python games/tata/mainline/live_roster.py
```

## 实验性战斗模拟、搜索与回放

地图布阵页新增“模拟当前布阵”“搜索阵容与站位”“打开模拟方案”“播放 / 暂停回放”。先重新同步角色池，以读取准确的等级进度、徽章加成和喂养状态；手动编辑后若与观测不同，暂停模拟并要求重同步。搜索预算默认 120 次，成功后自动显示方案；中间最优方案写入 .progress.json，错误不覆盖地图。更换角色池/关卡期间得到的旧结果只保存，不自动应用。

模拟执行解码后的原始 BattleEngine、单位、AI、技能、弹道、Buff、出怪、胜负检查和随机数，而非把稀有度偏好分冒充胜率。headless.lua 提供类/表扩展/配置加载及图形事件宿主桥接；配置、PetData、PetAttribs 与战斗方法来自原始字节码。native BattleAStar/Data 接口目前由占格表和原包保留的 Lua A* 版本桥接，**路径平局选择与原生版本尚未校准**。场地初始 NPC/技能通过原 ClientBattleBuilder 生成；额外战斗专用温泉/场地技能尚未同步，报告明确保留限制。

本机观测的 68 只塔塔，用原始 PetAttribs 重算 gs，68/68 与游戏读数完全相等。当前游戏内存中 Battle_826 的全部 44 个出怪事件也与本地配置逐字段相等。这些校验不能替代实战时序/胜负校准。

搜索 v1：以旧启发式、实测战力排序和不同站位为起点，在有界候选池中执行换宠物、交换格子、移动空格的局部搜索；每个候选都用同一个原始随机种子模拟比较，最终三个候选再用 701/2029/8191 三个独立种子复核。失败局按击杀率优先、伤害和时长次之；通过局优先。这是预算内候选搜索，不是全局最优证明。

11-26 本次结果：180 个候选，从旧方案击杀 26/50 提升到 50/50；搜索种子 123456 及三个复核种子都模拟通过（94 秒）。本机结果 runtime/tata/mainline/search-11-26.json 带初始布阵、帧轨迹、各候选结果及观测指纹；formation-11-26.png 是交给用户试打的带头像、元素、星级的布阵图。**实战验证仍待用户反馈。**

```powershell
python games/tata/mainline/live_roster.py --out runtime/tata/mainline/combat-capture.json
python games/tata/mainline/combat.py --capture runtime/tata/mainline/combat-capture.json --stage 11-26
python games/tata/mainline/search_policy.py --capture runtime/tata/mainline/combat-capture.json --stage 11-26 --budget 180 --out runtime/tata/mainline/search-11-26.json
python run.py tata mainline --stage 11-26 --simulation runtime/tata/mainline/search-11-26.json
```

敌人预览改为分列圆头像，右上叠原元素图标；悬停显示元素与克制关系。地图改为裁剪视口，取消默认铺满格子线，拖入时或勾选“显示布阵格”才显示全部真实部署格。回放画出原始逻辑得到的位置与血条，尚未实现 Spine 动画和所有粒子效果。

render_unit_art.py 只读取对应游戏缓存，按原始网格/UV、Idle 动画元数据、RGB24 顶点索引贴图、RGBAHalf 位置与 R8 双组 alpha 贴图，还原静态待机帧。已补充 48 个形态的本机预览；资源缺失/格式不支持时仍用原头像。资源留本机，不随仓库分发。它不是完整原客户端或动画播放器。提取依赖 UnityPy、numpy、opencv-python；面板加载已有 PNG 不依赖这些包。

```powershell
python games/tata/mainline/render_unit_art.py --capture runtime/tata/mainline/combat-capture.json
```

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
