# 主线数据与离线运行研究

当前已有 Tkinter 工作台、已登录角色池只读同步、原始 Lua 战斗引擎的实验性本地运行，以及按模拟结果搜索阵容/站位的工具。11-26 已搜索出本地模拟通过候选，尚待用户实战校准。原生寻路与宿主接口适配仍有未验证差异，不保证实战通关。

新增 adaptive-v2：工作台点“经验搜索阵容”。默认自动保存/读取本机经验，显示复用数与学习比较数；下方给出各路对位和光环覆盖理由。职业与 Front/Back 只作为弱提示，实际射程、养成耐久、元素、技能及玩家阵型参与候选生成。动画工作暂停。

## 策略与经验积累

1. **机制和玩家先验**：用原 PetData 当前技能、CalcSkillGrids 范围、实际重算属性构建分路；考虑水舞蝶三阶同排联动、星兔/火蝶周围覆盖。人工核验的11-11/11-21社区站位及低权重路线搭档提供其他起点，不将职业或强度榜固定为答案。出处、访问状态、版本疑点见 [community_knowledge.json](community_knowledge.json) 和 [POLICY-MEMORY.md](../docs/POLICY-MEMORY.md)。
2. **原逻辑验证**：替换、移位、整路/整排交换后实际模拟。候选池按先验+在线学习偏好排序，25%候选选择忽略该排序，另有15%重新生成起点。结果以模拟胜负/击杀等评分选择，不把先验分伪装成胜率。
3. **持久学习**：`runtime/tata/mainline/experience.sqlite3` 存失败与成功证据、上下文和版本指纹。同关卡/养成/种子下，结果确有差异的父子阵容用于有界在线成对排序学习，更新下一轮和下次运行的候选偏好。不是每关重新清零，也不是已成熟的强化学习模型；不保证每次运行都进步。
4. **跨关复用**：检索同关及相似敌方元素/地图/角色池的历史布阵，修复不可用宠物和非法格子后重新模拟。只复用起点，不沿用旧胜率。引擎/配置指纹改变后旧模型与旧胜负隔离；特征语义改变需升级 FEATURE_VERSION。
5. **实战反馈**：打开新版方案、按其阵型在游戏试打，再点“记实战通过/未通过”。只允许原关卡、原角色池及报告中的获选阵型；反馈独立保存为 user_report，影响未来案例选择，不冒充受控模拟标签或校准完成。其他候选或改动阵容需重新搜索为获选方案才能记录。

同账号、小样本初测：统一当前模拟器/评分、同种子，各40候选，旧搜索复核0/3，新版第23个候选获得模拟通关、复核3/3。再次运行和迁移11-27时，第一个历史起点均通过。只说明这次复用有效，不证明跨账号/版本普遍提升。三个固定复核种子重复使用后不再是永久独立测试集。

```powershell
python games/tata/mainline/search_policy.py --capture runtime/tata/mainline/combat-capture.json --stage 11-26 --budget 40 --out runtime/tata/mainline/adaptive-result.json
# 不读取、不写入历史经验，用于冷启动对照（仍保留机制与社区先验）
python games/tata/mainline/search_policy.py --capture runtime/tata/mainline/combat-capture.json --stage 11-26 --budget 40 --no-experience --out runtime/tata/mainline/cold-result.json
```

## 可视化工作台

双击根目录 `Start-Tata-Mainline.cmd`。需要已安装 Python 3.10+（含 Tkinter）；首次启动会安装缺少的 Python 依赖，并从 Git 中的 `assets/mainline-0.50.1.zip` 自动恢复公共配置、原始字节码、关卡和基础图片到 `runtime/tata/`，显示准备进度。换电脑无需拷贝旧电脑的数据，也无需重新下载 APK。已有环境也可运行 `python run.py tata mainline`。

换账号后在电脑微信登录游戏，工作台后台自动识别游戏 UID、角色池和主线关卡；也可点“从已登录游戏同步”立即刷新。启动后自动同步，之后每 30 秒检查一次，不切换前台、不发送游戏输入。读取失败时保留本地数据与上次关卡。资源包仅含固定版本 0.50.1 的公共内容，部分章节图片需打开游戏下载后点“同步本机资源”补充；不保证与后续热更新完全一致。

“本地账号”列表保存多个游戏账号，可改名；各账号的角色池、备注、上次关卡和地图布阵独立保存在 `runtime/tata/mainline/accounts/<UID哈希>/`。同等级、同宠物不会被当成同一账号。旧单账号文件会复制为“原本地角色池（未绑定账号）”，原文件保留，不凭等级猜归属。切换微信时，只有一个游戏会话则自动跟随；同时登录多个游戏账号时显示列表，由用户选择，手动选择后暂停后台自动同步，重新勾选即可恢复。搜索或自动推关期间不会自动切换正在编辑的账号。

默认勾选“跟随游戏”，读取 StageModel 的实际主线进度，账号启动时先恢复上次关卡，再后台刷新。手动输入并加载关卡会关闭跟随，避免自动刷新覆盖正在编辑的地图；重新勾选可恢复。经验库仍按版本/养成隔离并可跨账号借用起点，不沿用旧胜率。

公共资源包和来源/校验清单纳入 Git；下载包与生成的运行目录仍忽略。维护者可安装 `requirements.txt` 与 `UnityPy==1.25.3` 后执行 `python games/tata/mainline/rebuild_resources.py`，从固定 SHA-256 的原始安装包重建资源包。构建器明确允许公共资源路径，排除账号、截图、日志和校准。恢复使用 Python 标准库，不需要反编译工具或 Java。

1. 顶部只编辑一次“共享等级”，所有卡片同步显示相同等级。角色池 schema v3 将其存为顶层 `shared_level`，单只宠物不保存 level。
2. “塔塔图鉴 / 角色池”默认列出所有宠物图片；按原游戏职业、元素筛选，可组合搜索中文名、形态名、英文代号和编号，或只看已拥有。卡片底部快速收入/移出，点击图片编辑，进化阶段通过形态缩略图切换。当前数据包含 68 种 Enable=true、UnitType=1 的宠物。
3. 星级不再要求玩家输入总数：点“按星星 / 月亮图案选星级”，从原游戏图案中选择。每个形态的最低星级和下次进化门槛来自该宠物的 UnitEvolutionTrial；未完成试炼时可能保留较低形态，可勾选显示门槛后的图案。属性改为攻击/防御/生命的 E、D、C、B、A、S、SS、SSS 字母评级，选项按各宠物 UnitFeedLevel、当前星级及 PetFeedLevel 限制生成，保存时检查评级组合是否可达。只保留可能的养成状态，不把字母评级虚构成精确属性。
4. 本机按账号保存 `runtime/tata/mainline/accounts/<UID哈希>/roster.json`，同目录上次版本备份为 `roster.previous.json`，支持 JSON 导入/导出。旧根目录 roster.json 保留作迁移备份；显式 `--state` 仍支持独立单文件工作区。旧 v1 等级冲突时弹框确认，取消则保留原文件并禁止覆盖。旧 v1/v2 数值属性归档到 legacy_stats；与形态不符的旧星级转为未知并保留 migration_notes，待按图案确认。未知星级/评级可留空，装备暂以备注记录。
5. “地图布阵”：输入关卡名称如 `1-1`、`11-26` 或数字 ID。按 StageBattle.ResID → StageBattleRes.BackgroundRes 加载实际贴图。上方按波次配置 Cols 汇总各列可能出现的敌人图标，并显示敌人等级；不是逐帧波次回放。部署几何已对照原字节码：GridY 实际设置横向边界，空值回退 1–5 列；纵向部署范围来自 BattleMode.DeployGrids。1-1 是中央 1 列 × 5 行，1-10 是 3 列 × 5 行，11-26 是 5 列 × 5 行；不能用 ColumnCount=5 或 GridY 的名字猜布局。
6. 从已拥有图片区拖到格子上阵，地图内拖动移动/交换；拖回图片区或右键下阵。也支持点卡片再点格子。非法拖放不修改原方案。浅色格子是部署区，远端淡格子是战场。逻辑坐标保持原值，UI 像素映射不是原 Unity 相机坐标。
7. 可生成候选、手动调整，再保存布阵。方案附带角色池快照、数据版本、策略来源与模拟标记。地图使用已有静态预览，缺失时回退原头像，不是完整动画。

启发式 v1 使用有界束搜索选择宠物，每种至多一只，遵守可用宠物及上阵数量限制。偏好分 = 单宠物之和（2 × 稀有度编号 + 3 × 按敌人数加权的克制覆盖 − 2 × 弱势覆盖）+ 0.5 × 元素种类数。共享等级不用于宠物间排名。进化用于查当前稀有度；这是人工设定的搜索基线，**不是伤害公式、胜率或全局最优证明**。星级、属性评级、技能和装备尚未进入评分，位置尚未优化。

角色池位于已忽略的 runtime，基础图标由 Git 中的公共资源包恢复。可选的额外本机头像提取：

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

APK 和微信缓存的 FlatBuffers 资源目录均已解析，定位到 27 个战斗背景资源地址与对应 bundle；`inspect_catalog.py` 可查询这些依赖。目录有记录不代表文件已下载；直接猜 CDN 路径的尝试返回 404，尚未还原完整远程下载流程。缺图仍明确提示。基础图片随公共资源包管理，额外缓存图片留在本机。

```powershell
python games/tata/mainline/inspect_catalog.py runtime/tata/research/catalog-content.bin --out runtime/tata/research/android-map-locations.json
python games/tata/mainline/verify_rules.py --source runtime/tata/research/decoded-0.50.1 --data runtime/tata/research/data-bytecode-0.50.1 --dataset runtime/tata/research/dataset-bytecode-0.50.1 --out runtime/tata/research/rules-verification.json
```

规则对照报告验证了 6,400 个关卡的 field/deploy 矩形和 85 种星级表示，与原始字节码匹配，错误为 0。星级图案每 6 级换资源层，普通图案按新/旧颜色混排；73–78、79–84 为两组特殊图标，不能简单画 N 个同色星星。进化门槛例：11 号塔塔为 3/6/24，12 号为 6/18/30；原逻辑还有进化试炼，不能用星级唯一推断已完成的形态。

## 自动同步已登录角色池

工作台点击“从已登录游戏同步”：在电脑微信打开塔塔并完成登录，角色模型加载后即可读取，窗口可放后台或最小化。本机实测最小化状态约 6 秒读到共享 Lv.234、68 只已拥有角色，全部星级/形态/喂养等级通过当前配置校验。此结果是本次实测，不保证其他微信版本始终兼容。

读取内容包括角色编号、共享等级、星级、进化形态、精确喂养等级/进度及游戏中的 gs 原值；字母评级按对应 UnitFeedLevel 与 PetFeedAttrRank 推导。没有把 gs 当作伤害公式。角色列表来自实际 ed.PetModel.pets，并检查数量、逐只等级和喂养归属；isGet 若存在则校验，新登录尚未打开图鉴时这个标记可以不存在，拥有状态由已验证的 PetModel.pets 成员关系确认；不是通过图鉴存在与否猜拥有状态。

同步成功后更新对应账号目录的 roster.json，保留该账号已有备注，原文件备份为 roster.previous.json。完整白名单观测保存在该账号目录的 live-capture.json；每只的 game_observed 带读取时间，并随角色池导入/导出保留。后台检测到游戏养成未变化时，不覆盖本地手动修改。读取失败、模型变化或配置不匹配时保留原角色池；同一账号存在多个有效会话时拒绝合并。UID、昵称与 StageModel._stageID 和角色池从同一游戏堆连续读取两次校验，只保存白名单字段，不读微信账号令牌或聊天。

实现仅使用 Windows 的进程查询与 ReadProcessMemory 读取权限，动态定位 WebGL 内存、Lua 短字符串与表结构，再验证 class.__cname == ed.PetModel；不使用固定 PID/地址，不写内存、不注入、不发送游戏协议。读取过程中不保存整块内存，只输出允许的角色字段。不需要开启微信调试或重新登录。目前针对 Lua 5.4 wasm32 的已验证布局，更新改变布局时可能需要适配。不要在同步期间切换账号或进行养成；读取会比较两次角色观测拒绝不一致结果。

命令行仅生成并验证观测文件，不覆盖编辑角色池：

```powershell
python games/tata/mainline/live_roster.py
```

## 实验性自动布阵与连续推关

工作台新增“自动布阵并推关”和“停止自动推关”，可以设置本次最多挑战多少关。可从主线章节地图、布阵页或已确认的胜利页启动；章节地图会自动识别宽幅黄色开始按钮，进入布阵后重新定位控制器、核对实际关卡，再分析与布置。点击启动后会把游戏置于前台。运行期间保持游戏前台，不要同时操作鼠标；F8、停止按钮、失去前台、鼠标动作中移动/缩放窗口或状态校验失败都会停止工具输入。游戏自身已经开始的战斗会继续结算。只读同步角色池仍可后台进行，自动鼠标布阵需要前台。

未在战斗中的残留控制器不再被当作“控制器已切换”错误。章节地图通过原 WorldMapView 生命周期和 StageModel 引用确认，地图和布阵分开识别；存在活动中的其他关卡控制器或多个有效地图时仍停止，不把未知界面当章节地图。新电脑已从8-19章节地图启动，完成自动进入布阵、原请求顺序核验、实际通关和单关上限停止；本机证据在 `autoplay-ui/dee63e227a004ac1be9f4cb21ed17baa/`。

每关重新读取已拥有角色、共享等级、进化/星级/喂养及徽章。“模拟复核”用于搜索和自动推关，默认“轻量”：训练胜利后只额外模拟1次，布阵后按实际入场顺序预检1次。可选“关闭”：训练胜利即可使用，不再做额外模拟或开战前模拟；可选“完整”：搜索时3个种子×最多3种顺序（重复顺序合并），开战前4个种子。GUI启动任务时保存设置；命令行两入口均支持 `--review light|none|full`，默认light。现阵复用按同一设置评估，勾选“找到通过方案即结束”时可以直接复用。

脚本按元素筛选实际 `_filterList`，点卡片自动上阵，再从回读的实际格子拖到目标格。三档均核对角色、格子、养成和实际入场序列；入场顺序会影响随机数消耗及目标选择。横向卡片列表可滚动到已校准的两端，滚动不能改变已选阵容，点击后仍核验角色编号。输入使用独立 Windows 鼠标脚本，不写游戏内存。实战胜负单独存为 `live_observation`，不冒充玩家报告或模拟校准。

胜利时服务器先修改 StageModel，原战斗仍停在结算。循环以 BattleModule.battleID、state 和对应布阵对象共同判断切关完成；继续按钮之后重新定位对象，不能仅凭关卡编号增加就开下一局。实战失败、预算内无复核通过方案、陌生界面或超时均停止。OS 文件锁防止本工具的两个连续推关进程同时操作；不要同时启动钓鱼或其他输入程序。

默认自动识别窗口与当前画面，不需要手工标点，也不要求本机已有校准文件。原地图图像配准结合当前 StageBattleController 的战场偏移计算格子投影；开始/继续、清空、元素栏及卡片边框按实际画面定位。卡片滚动后用原头像特征和当前 `_filterList` 确认可见列，不再依赖旧电脑保存的末页坐标。每次启动重新识别，窗口移动使用当前窗口原点；尺寸或卡片行数变化后重新计算投影。正在一次鼠标按住/拖动动作时移动或缩放窗口，会释放鼠标并取消该动作，再次启动仍自动识别，不要求标点。

“检查游戏布局”是后台只读检查，不激活、移动游戏或发送输入；游戏被遮挡时会提示当前无法取得完整画面。主动点“自动布阵并推关”才将游戏切至前台并开始输入。自动识别缓存写到 `runtime/tata/mainline/autoplay-geometry.json`，无需在电脑之间迁移。旧手工配置只在显式使用 CLI `--geometry 路径` 时启用。识别证据不足、缺地图原图、多个有效对象、账号切换或输入回读不一致时，保留现场停止，不猜坐标；地图缺图可先点“同步本机资源”。已做原图/实际截图匹配与多比例回归；共享 Lv154 账号在新电脑实际完成 15 宠自动布阵并通过 8-6、8-7、8-8，跨关绿色继续按钮与按上限停止均已验证。更多窗口布局、地图和账号仍待验证；少数关卡实测不证明全部引擎机制已校准。

```powershell
python games/tata/mainline/autoplay.py --stages 5 --budget 40
```

证据位于 `runtime/tata/mainline/autoplay-runs/<运行编号>/`：逐关角色观测、模拟方案、输入核验事件及原进程结算与开战前顺序复核。停止文件是 `runtime/tata/mainline/AUTOPLAY-STOP`，GUI 的启动按钮会清除旧停止请求；命令行需要先确认并自行清除。所有这些文件不入库。

2026-10-29 本机以更新后的共享 Lv.235、68 宠完成 15 宠脚本布阵并实际通过 11-27、11-28、11-29；其中 11-27 模拟 82.75 秒、实战 81.5 秒。11-30实战失败后停止；已复现一项原因：同样的格子、宠物和随机种子，换成实际请求的入场序列后，模拟也在91.5秒失败，与实战一致。现已增加实际顺序预检，但搜索尚不能完全预知部署后Lua表的遍历布局，可能需要重新搜索或调整布阵。单账号几局吻合不等于引擎完全校准，路径平局、场地技能和不同版本的限制仍保留。

## 搜索时长、退出提示与续搜

在“地图布阵”页设置“候选上限”和“每关时长（分钟）”。两个上限独立，先达到哪个就结束；0表示该项不限。GUI会记住本机设置。若想搜索一晚上：候选上限填0，时长填480（8小时）或720（12小时），取消“找到通过方案即结束”，点击“经验搜索阵容”。这是纯本地搜索，不操作游戏，可在后台运行。勾选该项则找到符合当前复核设置的通过候选就提前结束。即使耗尽预算，也不代表已证明全局最优。

“停止搜索并保存”会在当前一次VM模拟结束后停止。每30秒保存续搜进度，正常结束或主动停止时再次保存；内存中的候选池和事件日志有界。点击“继续已保存搜索”，选择`.checkpoint.json`，将继承精英候选、已试集合、随机数进度和系统替换检查进度，并获得新的本轮时间/候选额度。关卡、养成、引擎及顺序复核设置不匹配时拒绝续搜，原文件不变。时长限制在两次VM模拟之间检查，不强杀正在结算的单次模拟。

运行状态持续显示本轮/累计候选、用时、模拟次数、最佳击杀和复核通过数。结束时明确区分：找到通过候选、时长到期、候选数量用尽、主动停止、游戏识别失败和实际顺序复核失败。没找到方案仍保存最佳候选；主动取消不会自动覆盖用户正在编辑的地图。“运行详情”包含原因代码、输出目录及日志，初始化失败也会产生状态文件，不再只提示“查看日志”。

当前搜索adaptive-v3交替执行系统单宠替换和探索：检查当前基准阵容中每个位置的所有已拥有合法替代，不按职业或战力硬排除；完成后若最优阵型改变，会以新基准继续检查。训练胜利的候选立即复核，稳定胜利优先于单种子下的快速胜利。它仍是有界启发式搜索，不是全局最优证明。`player_hypotheses.json`单独保存玩家待验证建议；11-30的“火蜥换电鹿”会在两者拥有状态允许时优先尝试，结果由当前养成模拟判断，不直接标为通关经验。

多种顺序采样不等于完全还原部署后的Lua表布局；自动推关按所选方式检查游戏当前真实请求顺序，“关闭”时只核对阵型、不做模拟。长时间搜索后再次读取养成，发现变化就保留结果并停止布阵。自动推关的时长限制是每关计算上限；鼠标输入阶段仍需要游戏前台。

```powershell
# 8小时纯本地优化；不会输入游戏。capture和initial来自此前本机保存的观测/方案。
python games/tata/mainline/search_policy.py --capture runtime/tata/mainline/combat-capture.json --stage 11-30 --initial runtime/tata/mainline/search-11-30.json --budget 0 --seconds 28800 --review light --out runtime/tata/mainline/overnight/result.json
# 恢复时需要同一角色池、关卡、引擎及复核设置；改变复核方式需新建搜索，新额度从本轮开始计。
python games/tata/mainline/search_policy.py --capture runtime/tata/mainline/combat-capture.json --stage 11-30 --budget 0 --seconds 28800 --review light --resume runtime/tata/mainline/overnight/result.checkpoint.json --out runtime/tata/mainline/resumed/result.json
```

## 战斗模拟细节

地图布阵页新增“模拟当前布阵”“搜索阵容与站位”“打开模拟方案”“播放 / 暂停回放”。先重新同步角色池，以读取准确的等级进度、徽章加成和喂养状态；手动编辑后若与观测不同，暂停模拟并要求重同步。GUI默认候选数不限、每关搜索10分钟、轻量复核，找到通过候选即结束；均可修改。最佳候选和复核进度写入 .progress.json，结束时写入结果，错误不覆盖地图。更换角色池/关卡期间得到的旧结果只保存，不自动应用。

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
