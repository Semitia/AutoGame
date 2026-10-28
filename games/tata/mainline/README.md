# 主线数据与离线运行研究

当前已有本地 Tkinter 工作台与启发式布阵基线；同时具备 APK 拆包、全量解码、配置 JSON 导出与关卡关联工具。`probe_headless.py` 可在无 Unity 环境中调用原始战斗字节码的部分方法。完整战斗、胜负校准和基于模拟的 policy 尚未完成。

## 可视化工作台

双击根目录 `Start-Tata-Mainline.cmd`，或 `python run.py tata mainline`。本机数据已准备；新环境需要按下方流程生成数据，面板本身仅依赖 Python 标准库和 Tkinter。

1. “我的角色池”：搜索中文名、英文代号或编号，在下拉框选择宠物；填等级、进化阶段等，点击保存。点击已拥有列表可编辑。进化阶段可用值会显示在详情中。
2. 本机自动保存 `runtime/tata/mainline/roster.json`，支持 JSON 导入/导出。每种宠物一条记录。面板属性可留空，未知属性不会猜算；装备目前用备注记录。
3. “关卡与布阵”：输入名称如 `1-1`、`2-21` 或关卡数字 ID，加载后显示上阵限制、敌人和已确认的格子。当前 APK 包含 68 种 Enable=true、UnitType=1 的宠物。
4. 生成候选，或在下拉框选宠物后点格子手动放置；选择“清空格子”可移除。相同宠物会移动到新格子。保存布阵会附带角色池快照、数据版本、策略来源及 `simulated:false`。

启发式 v0 使用有界束搜索选择宠物，每种至多一只，遵守可用宠物及上阵数量限制。偏好分 = 单宠物之和（2 × 稀有度编号 + log2(1+等级) + 3 × 按敌人数加权的克制覆盖 − 2 × 弱势覆盖）+ 0.5 × 元素种类数。进化用于查当前稀有度；这是人工设定的搜索基线，**不是伤害公式、胜率或全局最优证明**。位置顺序填充，没有优化前后排、射程或弹道；星级、技能等级、装备和面板属性目前只保存。空 GridY 等未知约束明确拒绝生成位置。

角色池及图标均位于已忽略的 runtime。可选的本机头像提取：

```powershell
python -m pip install UnityPy==1.25.3
python games/tata/mainline/extract_icons.py runtime/tata/research/inpackage_aa_1.lpak --out runtime/tata/mainline/icons
```

本次遍历 4,529 个 UnityFS bundle，提取 562 张宠物头像，无解析错误；程序根据 UnitRes.IconName 匹配，找不到则显示文字。游戏资源不随仓库分发。

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
