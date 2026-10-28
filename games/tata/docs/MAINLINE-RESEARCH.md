# Tata 主线离线模拟调查

调查日期：2026-10-28。目标是用真实关卡、玩家角色池和宠物机制搜索布阵，减少游戏内试错。本阶段仅离线分析公开 APK；没有启动安装包、登录账号、读取进程内存或修改游戏。

## 安装包来源与版本

- 官方网站：https://ttyzd.lilith.com/ （页面 canonical 指向 https://ttmxd.lilith.com/）。
- 官网 `js/config.js` 的 `downloadAndroidUrl` 指向莉莉丝分发页：https://ldp.lilith.com/tracking?r=d&cps_id=98fbe6189b7e11f18abe1211e0661fee 。
- 分发页给出的 APK：https://vda.lilithcdn.com/10090/2/0.50.1/com.lilithgame.pgame.android.cn/pgame_98fbe6189b7e11f18abe1211e0661fee.apk 。
- AndroidManifest 实读：`com.lilithgame.pgame.android.cn`，版本 `0.50.1`，versionCode `4436`。
- TapTap 官方入驻页 https://www.taptap.cn/app/866257 同时报 `0.50.1 (4436)`，更新于 2026-10-22。这是本次官网渠道取得的版本，不保证包含游戏启动后的最新热更新，也未证明与微信小游戏版本完全一致。
- 大小：358,820,065 字节；SHA-256：`281b2645b9e00dfd4ff5b302eeaacc1301d3faa2cee9fb24b34655e559fc5f5e`。
- 本地：`runtime/tata/research/tata-0.50.1.apk`。APK、第三方资源、脚本及分析产物均放在已忽略的 runtime 下，不提交。

## 已实测得到的结构

Unity 版本为 `2022.3.62f3`，由 globalgamemanagers 和 libunity.so 交叉确认。原生代码采用 IL2CPP，还存在 Lua 加载相关接口名称。

`assets/pgame.pkg` 为 18,337,776 字节的脚本/配置集合；`assets/pgame.pkg.bin` 是带解压长度的 LZ4 索引，解压后 334,277 字节。索引前两个 uint32 为包大小、记录数量；每项是 uint32 路径字节数、UTF-8 路径、uint32 内容长度、uint32 内容偏移，均为小端。已验证所有记录恰好覆盖整个包，无缺口、重叠、越界或多余索引字节。

| 路径类别 | 数量 | 证据含义 |
| --- | ---: | --- |
| Config | 3,166 | 配置文件条目，包含大量活动、试验及其他玩法 |
| Src | 2,830 | 客户端脚本条目 |
| Tolua | 41 | Lua 相关库条目 |
| Pb | 1 | 协议资源条目 |
| Config/StageBattle/ | 2,671 | 关卡配置文件；不能等同于 2,671 个正式主线关卡 |
| Src/Battle/Logic/Heroes/ | 143 | 宠物和敌人脚本；不能等同于 143 种宠物 |
| Src/Battle/Logic/Skills/ | 250 | 技能脚本，含其他玩法的专用技能 |

重点条目包括 `Config/Stage.luae`、`StageBattle.luae`、`Formation.luae`、`Unit.luae`、`UnitAttr.luae`、`UnitElement.luae`、`UnitEvolution.luae`，以及 `BattleAI.luae`、`BattleConfigUtils.luae`、`CatIce.luae`、`DuckPear.luae` 等。现已恢复字节码，完成 UnitAttr 单文件反编译；尚未逐项验证战斗公式。

`assets/aa/Android/inpackage_aa_1.lpak` 为 238,832,981 字节，按 UnityFS 头部长度可遍历 4,529 个连续资源包，最后边界准确落在文件末尾。Addressables 的 catalog.bundle 可由 UnityPy 1.25.3 读取；需将 fallback Unity 版本设为上面实测值。目录 TextAsset 为 6,245,824 字节，包含资源路径。全量对象扫描耗时过长、没有产生可用结果，已停止；没有声称所有资源已解析。

## 当前进度：解码、数据关联与无界面运行验证（2026-10-28）

用户已要求继续。**旧国际服路线有效：当前国服 0.50.1 的全部 6,038 个内容块已解码，6,037 个为 Lua 5.4 字节码，另外 1 个为 Pb 协议资源，解码错误为 0。** 正式工具已复跑确认，证据：`runtime/tata/research/decoded-0.50.1/decode-report.json`。

本轮新增验证：

- unluac 为 6,037 个文件全部生成文本，工具未报告异常；但 Lua 5.4 再编译检查只有 **5,979 个通过，58 个失败**，包括 `Src/game_battle.lua` 的 goto 标签作用域错误。因此“生成文件成功”不等于“可运行源码”。报告：`runtime/tata/research/source-validation.json`。
- **6,037 个原始字节码全部可由 lupa.lua54 加载校验**，无需修补反编译文本。报告：`runtime/tata/research/bytecode-validation.json`。
- 配置原始字节码和反编译文本分别导出：均得到 **3,122 / 3,166 个配置文件**，两条路线的 3,122 个 JSON 逐项相等。44 个配置需要额外环境或包含函数，隔离导出器明确报错，未伪造空表。报告：`runtime/tata/research/data-bytecode-0.50.1/export-report.json`、`comparison.json`。
- Stage 表共 6,400 行、StageBattle 表共 6,400 行、Unit 表共 223 行；关卡 → 战斗 → 波次 → 敌人定义全量关联成功，无缺失。包括未开放/未来关卡的可能性未排除，223 个单位也含敌人，不能当作宠物数量。输出：`runtime/tata/research/dataset-bytecode-0.50.1/`。
- 第一关 `1-1` 对应 `May1_N1_0`：CanDeployNum=3、ColumnCount=5、GridY={3}；Frame 8、40、60 各含 1 个 1101 敌人，合计 3 个。保留原始 Frame，暂未将它换算成秒。

### 战斗核心已找到，并完成局部无界面执行

核心并非缺失：它合并在 `Src/game_battle.luae`，捕获到 50 个模块初始化函数，包含 BattleEngine、UnitComponent、ProjectileComponent、SkillComponent、EnemyWave、BattleEndCheckSystem、PetAttribs 等。BattleRandom 则在 `Src/game_base1.luae` 的 `Src_Tools_BattleRandom` 中。

`probe_headless.py` 在电脑 Lua 5.4 VM 中直接加载解码后的原始字节码，捕获初始化函数而不自动执行整包；只初始化版本、数学、基础模块、战斗模块和引擎。实测 battleCheckVersion=500029，BattleModule.OnInit 的默认 dt=0.25、timeScale=2，数学函数 sin(90°)=1。这些是局部实测，不能据此推断所有模式最终 tick 参数。

真实 `BattleEngine.Tick` 在记录调用的系统替身上运行后，次序为：IncreaseTicks → 操作 → 单位 → 更新事件 → 出怪 → 地图 → 调度 → 延迟弹道激活 → 广播 → 胜负检查。未启用 LuckyDefense 可选分支。**这是主循环调度验证，没有模拟单位、伤害或胜负。** 证据：`runtime/tata/research/headless-probe.json`。

反编译文本中可定位防御减伤、元素效果、随机伤害浮动及增减伤分支：例如 UnitComponent.TakeDamage 中存在正伤害乘攻击者 ATK / (ATK + 3 × 目标 DEF) 的防御分支。尚未通过该完整方法的字节码执行或实战校准，不能当成完整通用伤害公式。CatIce 脚本可见技能等级检查、额外弹道生成和穿透参数，也尚未校准实战。

### 国际服和旧版证据

- 当前国际服：`com.farlightgames.pgame.gp`，0.50.1 / 4435。来源：https://apkpure.net/pets-knight/com.farlightgames.pgame.gp/download/0.50.1 。本地 `runtime/tata/research/tata-overseas-0.50.1.xapk`，SHA-256 `3ac2c0ecfbc3dbdaeba4fb824671ad84b455aacf06425050e8395f3fa2b695b0`。
- 当前国际服与国服的 `pgame.pkg`、`pgame.pkg.bin`、`global-metadata.dat`、`libigame.so` **逐字节相同**；`libil2cpp.so` 不同。这不证明微信小游戏或热更新与它们一致。
- 旧国际服：同一包名，0.31.11 / 2321。来源：https://apkpure.net/pets-knight/com.farlightgames.pgame.gp/download/0.31.11 。本地 `runtime/tata/research/tata-overseas-0.31.11.xapk`，SHA-256 `55d99255b0ac6eea36f3d6611625ba162be378649686b99ea20952e6f12ac345`。
- 旧版未发现 `libNetHTProtect`，metadata 为标准 `AF1BB1FA` / version 31；ARM32 `libigame.so` 可静态分析。**旧版脚本仍加密，但解码实现容易分析，且可解当前版。** 当前版 metadata 仍是 HTPX，未解开；这已不阻碍 Lua 包提取。
- 查看过的“破解版”网页存在失效占位下载链接、版本信息混杂，未取得可验证的破解样本，未安装或运行。不能由此推断所有破解版真伪；本次突破不依赖破解版。

### 已验证的解码方法

参考库：`runtime/tata/research/overseas-0.31.11/libigame.so`，SHA-256 `79a1028da49a1b639f964176127f1e1aaeddd0abbe8429387cc95c8956892dc5`。以下偏移仅适用于这个确切文件，不能直接用于其他版本。

1. 旧库函数 `0x42a47c` 构造 Blowfish 密钥：从文件偏移 `0x111070` 读取 44 个小端 uint32，筛选值 `>= 0x30`，保留低 8 位，得到 32 字节密钥。已保存于同目录 `blowfish-key.bin`，无需公开或提交密钥。
2. 每块前 4 字节 `FFFFFFFF`，之后小端 uint32 为有效解密长度 n；从偏移 8 开始为 Blowfish ECB 密文。
3. 输入按每 4 字节翻转，标准 Blowfish ECB 解密，再每 4 字节翻转，截取前 n 字节。
4. 从结果开头读取小端 uint32，令 skip = 此值 + 4，跳过自定义元数据头。
5. 对余下内容使用带长度前缀的 `lz4.block.decompress`，得到 Lua 字节码或协议资源。

静态调用链线索：包索引解析 `0x5c3934`、内容读取 `0x5c4638`、调用者 `0x592f18`、解码包装 `0x42acb0`、实际解码 `0x42a6f4`、密钥初始化 `0x42a47c`、LZ4 包装 `0x4208e0`。先前发现的 AES 函数不是本脚本包的解密路线。

### 本机复现和产物

- 早期研究原型：`.local/tata_decode_all.py`，保留本机。正式工具已整理为 `games/tata/mainline/decode_package.py`，验证参考库哈希并派生密钥，校验包索引、解密长度、解压上限及输出路径；无需单独保存密钥作为输入。
- 全量输出：`runtime/tata/research/decoded-0.50.1/`，保留原 `.luae` 文件名，但内容已是 Lua 5.4 字节码（头 `1b4c756154`）；`Pb/pgame.pbe` 不是 Lua。
- 反编译工具：`.local/unluac.jar`，来自 https://sourceforge.net/projects/unluac/files/latest/download ，已验证支持本次 Lua 5.4 样本。
- `Config/UnitAttr.luae` 可读到 `config.UnitAttrHeaderTable` 字段 Attr/Icon/GS/IconBig，以及 ATK、DEF、HP、CRIT、CRITP、COUNT 行。GS 中 ATK=1、DEF=1、HP=0.2；**未验证 GS 含义，不可当作伤害公式。** 已完成批量反编译，限制见本节开头。
- 旧版 IL2CPP 元数据亦已由 Il2CppDumper 导出：`.local/Il2CppDumper-framework/dump.cs`、`script.json`、`DummyDll/` 等。生成完成，程序最终因无控制台执行 ReadKey 报错，不代表导出失败。
- 第三方工具与下载/生成产物均在已忽略的 `.local/` 或 `runtime/` 下，不纳入第三方包、游戏源码或密钥。自行编写的正式研究工具位于 `games/tata/mainline/`。

```powershell
C:/Users/Winslow/miniforge3/python.exe .local/tata_decode_all.py
java -jar .local/unluac.jar runtime/tata/research/decoded-0.50.1/Config/UnitAttr.luae
```

### 仍未完成 / 后续工作顺序

1. 扩展原始字节码模块加载器，优先复用原始 class、IOC、表扩展、随机数和配置读取逻辑；隔离 Display/Unity 初始化，不能用空实现替代会影响战斗的接口。
2. 创建真实 BattleEngine，接通实际 Unit/Projectile/Skill/EnemySpawn/EndCheck 系统和宠物数据；明确出生位置、动画事件与出手时机是否还依赖资源数据。当前最小 class 适配器仅用于局部探测，未证明完整兼容。
3. 建立单关完整运行与固定随机种子回放，核对伤害、索敌、帧序和胜负后再测本地吞吐。当前没有可信的完整战斗性能数据。
4. 手动角色池、关卡查看、手动布阵与启发式 v0 已接入本地 Tkinter 工作台；支持角色池/布阵 JSON，使用本机提取的宠物头像。基线仅按稀有度、等级与元素覆盖选宠物，位置顺序填充，不能预测胜负。**目前没有完整离线战斗模拟器或经过胜负验证的 policy。** 下一步将真实模拟器作为候选评价器接入，并纳入星级、技能、装备与位置效果。
5. 核对微信小游戏实际规则和热更新；APK 脚本一致性不能代替该验证。新工具运行方法见 `games/tata/mainline/README.md`。研究工具、角色池/候选测试及隔离配置下的面板集成测试共 15 项通过；原有研究工具已提交 d969382。

## 从真实数据到 policy 的验收路径

1. **数据层**：提取关卡地图、波次/出怪时间/路线、单位属性成长、技能参数、元素关系和布阵限制。每项保留版本、源路径与字段来源，未知字段报缺失而非填猜测默认值。
2. **规则层**：优先复用可恢复的纯逻辑脚本；若必须重实现，明确 tick 顺序、目标选择、碰撞、弹道、状态叠加、召唤物、随机数与胜负条件。
3. **校准层**：以小量实战回放验证相同阵容的伤害轨迹、击杀时刻、漏怪和胜负。匹配之前不把模拟排名用于自动挑战。
4. **搜索层**：输入当前关卡及用户真实角色池（等级、进化、技能解锁、装备等），搜索合法宠物选择及位置。先用束搜索/局部替换构建基线；有随机机制则用共同随机种子比较多局胜率，再对候选做独立种子验证。报告预算内最优候选和不确定性；只有完整穷举或有上界证明时才声称全局最优。
5. **执行层**：将确定阵容交给单独的游戏操作适配器；搜索过程完全本地运行，仅少量候选在游戏中复核。

目前不应开始强化学习训练：状态转移规则和奖励计算都没有还原，训练速度再快也会优化错误模型。

## 可复现提取

Python 依赖：`lz4`（现有环境已安装）。无需启动游戏。

```powershell
python games/tata/mainline/inspect_apk.py runtime/tata/research/tata-0.50.1.apk --out runtime/tata/research/inventory --extract
python -m unittest discover -s games/tata/mainline -p "test_*.py" -v
```

输出 `report.json`、`apk-files.json`、`pkg-index.json` 和 `encrypted/` 内容块。该工具仅拆包，明确标记 `decoded: false`，不执行 APK 或导出的脚本。
