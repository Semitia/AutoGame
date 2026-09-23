# 双人合作脚本：可进入实战验收的候选版

更新：2026-09-23。**完整单局代码链路已接通，84项离线测试通过；尚无此版本独立通关证据，不标记为稳定挂机版。** 本轮没有连接MuMu或开启新局。

## 可用流程

- 两设备精确组队、复核双方身份与层数、房主只开一局；不自动重开、不重复花合作券。
- 432×768布局坐标，截图归一化到1080×1920识别，点击和拖动换算回原生尺寸。
- 按实际格子底座模板发现左右棋盘与扩格，区分空格/占用格；两次连续稳定观察才决策。格子候选坐标不是已开放格，也不会盲点候选区域。
- 同屏双方名字/层数/波次核验；实机确认**蓝色为自己、红色为伙伴**，原颜色判断已修正，地址配反会停止。
- **累计确认召唤不足5次只召唤，钱不足等待。满5次后按下一次召唤费∶强化费≈1∶2选择。** 不是累计花费比或购买次数比。
- 复用单人 `policy.price_action` / `merge_pair`：辅助冗余先合、优先低阶，输出有空位保留，满格需要召唤时才考虑合输出。
- 召唤验证价格上涨和唯一新占用格，点开详情确认英雄，再以已确认动作记录1阶；不会凭购买日志计数。
- 合成验证来源空了、目标仍在、详情英雄匹配配置，再记录原阶级+1，允许结果变成另一个英雄。未知阶级不合成。
- 奖励先于选卡、选卡先于购买。待确认购买可跨奖励/选卡保留；模态卡住、动作没生效、OCR/棋盘长期不稳定均有停止上限。
- 单侧入口只实例化该侧设备/Reader/锁。两侧独立输出目录；一侧异常通知另一侧停止。
- 合作与两个单人入口共用按ADB序列号的设备锁，锁目录不依赖账号runtime；Windows启动时还检查旧runner进程。必须使用同一设备的统一序列号，锁不解析不同ADB别名是否指向同一物理实例。

## 启动

使用已配置Python；本机没有旧交接中的`.venv`：

```powershell
$py = (Get-Content config/local.json | ConvertFrom-Json).python
$env:PYTHONPATH = '.local/python-deps'
```

先只读查询MuMu实例及当前ADB地址，并核对两号实际四英雄阵容。没有默认套用 `beginner.json` 或 `veteran.json`。下面的地址及profile变量须先设置为实际值：

```powershell
& $py run.py bilibili_hero_merge_coop --host-device $hostDevice --guest-device $guestDevice --host-tactics $hostProfile --guest-tactics $guestProfile --stage 2 --minutes 20
```

无 `--battle-only` 时，从合作页面自动组队并开一局；需要双方正确账号已进入游戏。加 `--battle-only` 跳过组队，用于刚开局的空棋盘。**新接管必须同时识别到空棋盘和免费召唤**；历史截图中房主空棋盘但召唤费190，不能视为新局。

仅操作访客：

```powershell
& $py run.py bilibili_hero_merge_coop --battle-only --only-side guest --guest-device $guestDevice --guest-tactics $guestProfile --stage 2
```

`runtime/coop/STOP`存在时拒绝启动，程序不自动删除。运行中创建该文件会停止两个worker。停止脚本不等于游戏暂停；合作模式不自动点击未经验证的暂停位置。

### 阵容配置

沿用现有四位置tactics格式。新增可选 `hero_definitions` 对象，键为自定义英雄key，值包含确切 `name` 和 `buff_keywords` 字符串数组；可为新英雄配置 `slots`、职业职责、保留数和 `buff_priority`，无需修改共享英雄目录。

真实两号四英雄配置仍需在实战前从详情/阵容界面核实。图像不能可靠确定全员名字，未杜撰配置。识别到不匹配英雄或选卡无任何阵容关键词时保存现场并停止。

## 记录与恢复

每侧目录包含 `latest.png`、每次动作前图、详情图、确认/停止图、`events.jsonl`、`observations.jsonl`及原子写入的`state.json`。后者保存设备、账号、层数、阵容指纹、计数、棋子、待确认动作；写入失败不执行下一次输入。

`--host-state` / `--guest-state` 配合 `--battle-only` 可读取120秒内同身份且无待确认动作的检查点。价格、格子、占用及英雄须重新匹配，波次不能倒退；**恢复的旧棋子阶级先降为0，再默认尝试视觉补齐**。2026-09-23用户授权救急识别：格内自相似优先，未知时头部模板兜底，候选可用于合成；日志 `visual_tier_recovery` 和 `tier_source` 保留来源。`--no-visual-tiers` 可关闭。仍识别不出的保持0，满格可能停止；不承诺任意中途局无损接管，不新增无检查点的任意占用棋盘接管。旧截图/别局状态不能启动为可信满阶棋盘。详细算法与测试见 `docs/HANDOFF-20260923-HERO-GUI-TIER-VISION.md`。

## 离线验证

无需游戏进程运行：

```powershell
& $py -m unittest discover -s games/bilibili_hero_merge -p 'test_*.py'
& $py run.py bilibili_hero_merge_coop --inspect-image docs/evidence/coop-20260923/dual-battle-guest-1080.png --only-side guest --runtime runtime/coop-offline
& $py games/bilibili_hero_merge/coop_replay.py docs/evidence/coop-20260923/synthetic-replay.jsonl --tactics games/bilibili_hero_merge/tactics/veteran.json --side host
```

`--inspect-image`输出框选棋盘PNG与JSON，不创建平台或OCR实例。`coop_replay.py`支持回放worker实际写出的`observations.jsonl`。该回放仅检验观察→决策，不能验证真实输入效果。

84项测试覆盖真实截图左右7空格/9占用格、扩格/装饰平台区分、1440×2560换算、双方标签、奖励叠选卡、首次5召唤→强化→选卡→结算模拟全程、失败动作、换英雄合成、记录失败、设备锁及组队后单次开局。真实截图重新OCR得到双方价格分别600/190/3.8K与100/10/5.6K；第1层的`第I层`识别问题有专门修正和回归。

## 实战验收剩余项

2026-09-23监督测试已验证双设备组队、身份/第2层核验与单次开局。Windows进程扫描已显式使用UTF-8，解决中文命令行导致启动解码失败。实机识别证据见 `docs/evidence/coop-20260923-live/`。房主初始召唤费10、访客免费；自动初始化仅允许免费空棋盘或第1波7空格且费用10。用户明确确认从未操作的空棋盘可用 `--battle-only --adopt-empty`，仍要求7空格和初始费用，不能接管已有棋子。

实战中怪物/特效遮挡格子使正式runner停止；已加入一次无输入短时连续取帧：每个格子至少两帧明确一致才采纳，空/占用冲突仍不执行动作，不沿用旧帧占用状态；战斗内等待特效上限60秒，未知界面仍20秒。原有两次稳定观察及合成结果验证保留。89项离线测试通过，新增取帧机制尚待下一局实测。

本局中途用临时监督脚本处理召唤、强化、选卡和奖励，用户也手动操作访客，最终第2层第10波失败。最后合成尝试后已到结算，无法确认合成生效。不是完整脚本自动通关证据，不自动重开。

1. 原生ADB截图下模板阈值、动态攻击/召唤光效和更多扩格排列；当前模板来自用户双窗口截图，尚未覆盖完整扩格轨迹。
2. 英雄详情沿用单人版的名字裁剪与空白处关闭动作，合作UI一致性需实测。阶级来自确认动作历史或标明来源的救急视觉候选，不是阶级OCR；视觉接入待实战验证。
3. 初次免费召唤及其后价格上涨、新格出现、合成动画、4阶额外选卡、最终结算的真实时序。
4. 两号当前阵容和角色buff关键词；本轮不自动沿用过时配置。

异常会保存证据并停止。后续实战应持续观察到结算，发现视觉差异就用新证据修正，不能仅凭单测通过宣称可稳定挂机。

## 证据来源

原始失败交接：[HANDOFF](../../docs/HANDOFF-COOP-2026-09-23.md)。用户补发原图、两侧裁图、来源JSON、OCR标签均保存于`docs/evidence/coop-20260923/`，格子模板带`assets/coop/source.json`来源记录。`synthetic-replay.jsonl`是构造用例，不是真实战斗录像。
