# heka — HEKA Patchmaster `.dat` 读取工具包

读取 HEKA Patchmaster 采集的 bundle 格式 `.dat` 膜片钳数据文件。

## 目录结构

| 文件 | 内容 |
|---|---|
| `reader.py` | 底层解析库（`Bundle` 类），解析 `.pul` 元数据树 + 懒读取 `.dat` 原始数据 |
| `utils.py` | 高层封装 `HekaFile` 类：按标签/序号取数、单位换算 |
| `nanopore.py` | 纳米孔计算：KCl/NaCl/LiCl 电导率表（25 °C）+ 孔径公式 |
| `analysis.py` | 时间序列分析库（纯 numpy）：阈值带+滞回事件检测、直方图、存活函数；GUI 与 notebook 共用同一入口 |
| `test_analysis.py` | `analysis.py` 的无头测试（合成数据，`python3 test_analysis.py` 直接跑） |
| `browser.py` | 交互式 GUI 浏览器（pyqtgraph）：浏览、测量、分布分析、孔径计算 |
| `launcher.py` + `heka_browser.spec` | PyInstaller 打包入口与配置（见第 6 节） |
| `build_mac.sh` / `build_windows.bat` / `build_linux.sh` | 三平台一键构建脚本 |

## 环境要求

- Python 3，numpy
- `browser.py` 额外需要：`pyqtgraph`、PyQt5（`pip install pyqtgraph PyQt5`）

---

## 1. browser GUI 使用方法

### 1.1 启动

```bash
cd experiment
python heka/browser.py        # 任意工作目录直接运行也可以，已内置路径自举
```

### 1.2 操作

1. 点 **打开…**（Load...，界面默认中文，可切英文）选择 `.dat` 文件（只解析头部，秒开）；加载后按钮下方路径栏显示完整路径——可直接鼠标选中复制（Cmd+A 全选 / Cmd+C），路径过长时横向滚动查看
2. 左侧树按 `Pulsed → Group → Series → Sweep → Trace` 层级展示；节点名显示**路径式编号**（Group `G0`、Series `G0 S26`、Sweep `G0 S26 W3`、Trace `G0 S26 W3 T0`），与图例 / 读数里的 `(G#g S#w W#)` 及 `rec.get(N)` 编号一一对应（文件根节点显示 `Pulsed`）
3. **点击任意层级即显示对应数据**：

| 点击节点 | 显示内容 |
|---|---|
| Group | 组内全部 series 的全部曲线 |
| Series | 该 series 下所有 sweep |
| Sweep | 该 sweep 下所有通道 |
| Trace | 单条曲线 |

4. **多选**：`Cmd+点击`（macOS）/ `Ctrl+点击` 追加，`Shift+点击` 选范围；多选结果取并集自动去重
5. 曲线超过 20 条时自动隐藏图例；右下角面板显示选中节点的全部元数据（采样、单位、放大器状态等）。左侧面板最宽 480 px，宽屏时富余空间自动留给绘图区
6. **左列布局**：按钮行（固定）下方是三个**可折叠区块**——`▾ 文件信息`（路径栏 + 元数据树，置顶） / `▾ 文件树` / `▾ 纳米孔计算器`，区块间有分割条可任意拖动分配高度；点击标题折叠/展开（折叠后只剩一行标题）。文件信息可压到很矮（无最小高度限制，适合当紧凑状态条用）；**折叠状态、分割位置与折叠区块的展开高度跨会话记忆**，下次打开自动还原。**全部分割条（左右 / 左列各区 / 主图↔幅度列 / 主图↔Event 面板 / Event 面板左右各列）都是可见的灰色圆角条，悬停变蓝**——直接抓取拖动即可调整大小
7. **配色**：浅色现代主题（米白背景 + 深灰文字），整个应用**强制浅色**（Fusion 样式 + 浅色调色板，不受 macOS 深色模式影响，三平台外观一致）。曲线色环分三档：≤10 条 Tableau 10，11–20 条 Tableau 20（深浅两版），>20 条低饱和金比例色相环（S=.55/V=.78，几百条也柔和可辨，颜色按序号确定不漂移）；十字光标橙色、A/B 标记红/蓝、读数为半透明白底浮框、图例白底。全部颜色集中在 `heka/i18n.py` 的 `THEME` 字典（`browser.py` 顶部导入），想微调只改这一处
8. **缩放与导航**：

| 操作 | 行为 |
|---|---|
| **X 轴条**上按住左键拖拽拉范围 | 实时竖直半透明预览，松开**只缩放 X** |
| **Y 轴条**上按住左键拖拽拉范围 | 水平预览，松开**只缩放 Y** |
| 鼠标滚轮 | **图区内 = XY 双轴同步缩放**（以光标为中心）；**X / Y 轴条上 = 仅缩放该轴** |
| 图区内左键拖拽 | 平移视图 |
| **Delete** / **Backspace** | **撤销上一个缩放**（滚轮连续滚动合并为一步；历史用完后再按不动作） |
| **Ctrl/Cmd+Delete 或 Ctrl/Cmd+Backspace** | 通用删除，按当前选中解析对象（详见 1.5：矩形 > 事件行 > Measure 结果；macOS 键盘的 delete 键即 Backspace，两者等效）；文本输入框内不拦截（保留原生删词行为） |
| **Cmd/Ctrl+N** | 新建分析文档 tab（同 [新建] 按钮；现有文档不受影响） |
| **Cmd/Ctrl+S** / **Shift+Cmd/Ctrl+S** | 保存 / 另存为当前分析文档（无打开文档时无动作） |
| **F5** | 手动重新解析当前 .dat（跟随文件的兜底） |
| **Join**（开关按钮） | 多选时把各条曲线按采集顺序首尾拼接成**一条连续曲线**：时间轴无缝递增，sweep 交界画浅灰竖虚线；单选时无效果；状态跨会话记忆 |
| **跟随文件**（开关按钮） | **准实时读取 Patchmaster 正在写的 .dat**：监视文件变化 → 500 ms 防抖 → 自动重新解析并**保持你当前的树选中**（按 sweep 级延迟反馈新数据；F5 随时手动刷新）。读到半截写入会静默跳过、下次变化自动重试。**前提**：Patchmaster 需开启按 sweep 落盘/自动保存（若只在实验结束时写 .pul，则只反映保存后的内容）；新增 sweep 会改变曲线集，此前抓取的旧行会灰显（记录保留）。状态不跨会话记忆（每次启动默认关） |
| 每次切换选中节点 | 坐标轴自动适配新数据 |

**自动按钮（Auto） / 加载曲线的 Y 轴自适应**采用 **1–99 百分位 + 5% 边距**（基于原始数据计算）：每条 sweep 开头的电容充放电尖峰只占极少量采样点，不会压扁 Y 范围，开/闭合电流与 nanopore 事件保持在视野内。Auto 同时清空缩放撤销历史。

> Join 拼接会把选中数据完整复制一份：Series 级（几十 MB）无压力；整 Group（GB 级）内存会翻倍，建议按 Series 拼接。拼接曲线上测量（十字线 / A-B 差值）照常可用，y 读数是真实采样点，`dy/dt` 跨拼接段无物理意义。

9. **Measure 测量** / **Nano 计算器面板** / **幅度列 + Event 事件面板**：见 1.3–1.5 节
10. **界面语言（中/EN）**：顶行右侧「中/EN」按钮切换界面语言（默认中文），**重启后生效**（UI 在启动时整体构建）；数据 schema 词（t_start/dwell/level、检测模式名、单位符号、CSV 列名）两种语言下保持英文原样

### 1.3 Measure 测量模式

按钮行的 **测量（Measure）** 为开关式按钮，开启后进入测量模式。读数**浮动显示在图区左上角**（半透明白底深灰字，锚定视窗左上角跟随缩放，不占布局空间、任意行数完整可见）：

```
cursor: x=460.523 ms, y=460.531 pA [-200mv-kcl (G0 S5 W3)]    ← 光标当前位置
A: x=120.1 ms, y=101.2 pA                                     ← 单击落 A 点后出现
B: x=380.7 ms, y=890.4 pA                                     ← 再单击落 B 点后出现
dt=260.6 ms  dy=789.2 pA  dy/dt=3.028 nA/s                    ← AB 齐后出现
```

- **实时十字线**：鼠标移动时橙色虚线跟随；`cursor` 行显示**光标所在位置的原始坐标**（连续平滑，不吸附采样点）。方括号内为所在拼接段/最近曲线名；**Join 模式下自动显示所在拼接段**（series 标签 + 0 基编号，如 `[-200mv-kcl (G0 S5 W3)]`，与树节点编号对应）
- **两点差值测量（点击）**：单击落 A 点（红圈），再单击落 B 点（蓝圈）——A/B **吸附到真实采样点**（原始数据，不受显示降采样影响），B 锁定与 A 相同的曲线（Join 下同一条拼接曲线）。完成一组后，下一次单击自动开始新的一组
- **自由测距（拖拽）**：Measure 开启时**按住左键拖拽**可测量**任意两点**的 dx / dy / dy/dx——不吸附轨迹，适合量噪声基底到峰顶、两条 trace 间距等场景。拖动时实时显示橙色虚线 + 读数 `drag` 行；松开后结果保留在图上（虚线 + 中点标签），下一次拖拽自动替换。注意：Measure 开启期间图区拖拽被测距接管（不平移），轴条拖拽缩放不受影响，需要平移时取消 Measure 勾选即可
- **清除（Clear）**：清除所有测量标记和读数；**Ctrl(⌘)+Delete** 快捷删除测量结果（详见 1.5 的通用删除）
- 再次点击 **Measure** 关闭模式（十字线隐藏、读数框消失，已落的标记保留到 Clear 或切换节点）

单位跟随当前曲线轴单位自动换算 SI 前缀（ms / pA / nA 等），6 位有效数字。

> 注：强缩小时曲线显示为 peak 降采样的 min/max 包络，pin/十字线可能与画线在视觉上略有偏差——测量值本身始终是真实采样点，放大后即与画线贴合。

### 1.4 纳米孔计算器（常设面板）

计算器**常驻在左侧栏底部**（树下方，无弹出窗），与测量联动：

**自动填充**：Measure 模式下每落一个测量点，按当前曲线的原生单位自动填入——
- 电压族曲线（V / mV / uV，电流钳数据）→ 自动填入 **Voltage**（换算为 mV）
- 电流族曲线（A / mA / uA / nA / pA，电压钳数据）→ 自动填入 **Current**（换算为 Current 单位框当前选择的 nA / pA）
- 最新一次测量覆盖对应字段（先测电流再测电压时两者各自保留）

| 输入 | 范围 | 默认 |
|---|---|---|
| 溶液 | KCl / NaCl / LiCl | KCl |
| 浓度 | 0.001–5.0 M | 1.0 M |
| 膜厚 | 1–100 nm | 20 nm |
| 电压 | 0.001–10000 mV | 100 mV |
| 电流 | pA / nA 可选 | 1 nA |

输出（任一输入变动实时刷新）：电导率 σ (S/m)、电导 G (nS)、孔径 **d (nm)**。

输入框点击自动全选、直接键入即替换；中文输入法的全角句号/逗号自动转半角；超出范围自动夹取（失去焦点或回车时回写为合法值）。

孔径采用 Kowalczyk 等 (2011) 的接触电阻模型（圆形孔、有效膜厚 L）：

```
G = I/V
d = I/(2σV) × (1 + √(1 + 16σL/(πG)))
```

电导率 σ 按 25 °C 查表（0.001–5 M），超出范围取端点值，表内线性插值。计算接口也可在脚本中直接使用：

```python
from heka import get_conductivity, calculate_pore_diameter

sigma = get_conductivity("KCl", 1.0)          # 11.18 S/m
d = calculate_pore_diameter(1e-9, 0.1,        # I (A), V (V)
                            sigma=sigma, thickness=20e-9)   # → 5.241 nm
```

### 1.5 幅度列（选段看分布）+ Event 事件面板（区域抓取事件 = 分析文档）

**事件面板即多文档编辑器**：面板顶部是文档 **tab 行**（每个打开的 CSV 一个 tab，可关闭 ×）+ **[新建] [保存] [另存为…]**（对应快捷键 `Cmd/N`、`Cmd/S`、`Shift+Cmd/S`，Win/Linux 用 Ctrl）；文档就是那张扁平事件 CSV 本身（v6 = v4 事件表 + `#` 参数头 + `file_hash` 内在指纹列），事件行是内容、矩形/视图只是各 tab 会话内的工具。启动时空面板居中一个 **[新建分析文件]** 按钮；**在主图上画出第一个矩形会自动新建「未命名」文档**；**双击右侧文件列的 CSV = 打开为新文档 tab**（已在 tab 里的路径再打开 = 切换到那个 tab）。**新建/打开不会关掉现有文档**（各自留在自己的 tab 里，无需确认）——只有**关闭脏 tab**（及退出程序）才询问 保存/放弃/取消。**切换 tab = 整个现场切换**：事件行、矩形、参数随 tab 换入换出，显示上下文（溯源 .dat + trace 选择 + Join）自动从行重建——两个文件间的切换走 Bundle 缓存、不重复解析。打开时自动定位溯源 .dat（**v6 起按 `file_hash` 内容指纹匹配——移动/重命名 .dat 都能自动挂上，路径不参与匹配**；v5 旧文件走 CSV 同目录同名同大小 → 手动定位，取消过一次的定位框本会话不再重复弹），选中被引用 trace 所在的**整条 series**（引用按序列级上卷——Join 拼接轴按当前显示的 sweep 集合推进，只选零散 trace 会漏掉没有事件的 sweep、令之后所有接缝前移，事件越靠后偏得越多）、恢复 Join，行立即点亮；源失联则降级为灰行事件表。修改事件（加/删/重抓）后 tab 标题带 **•** 脏标记；**另存为…** 的文件名默认 `<数据文件名>_events.csv`。

分析功能分两处：**幅度列**（主图右侧 `»` 可折叠列，默认收起，**展开宽度默认 = 窗口宽度的 15%**——拖分割条可调、位置跨会话记忆，主图吸收全部富余空间）看幅度分布，**Event 事件面板**（主图下方 `▾ 事件` 可折叠面板）抓取事件。**激活 = 最后点击的区域**：点击幅度列任意处 → 幅度模式（Shift+横向拖拽选段）；点击 Event 面板任意处 → 事件模式（Shift+拖拽画矩形，启动默认即此模式）；主图/左列点击不改模式（共享画布）。**激活状态高亮可见**：当前持手势一侧的面板提示文字显示为**蓝色加粗标签（浅蓝底 pill）**，对应**区块标题（`»` / `▾` 折叠条）文字也染蓝**——一眼看出 Shift+拖拽会画出什么。**折叠幅度列 = 清除全部区域并回落事件模式**；折叠 Event 面板 = 矩形冻结但**记录保留**。分析永远基于**每条曲线的原始采样数组**（Join 时基于拼接连续轴），由纯 numpy 库 `analysis.py` 完成——GUI 与脚本共用同一入口（批量/全数据检测用 notebook 直接调这个库，GUI 专注逐个甄别采集）：

```python
from heka.analysis import detect_events, detect_events_segments, slice_segments, all_point_histogram
```

**手势约定**（分析选择与浏览互不干扰）：

| 手势 | 行为 |
|---|---|
| X / Y 轴条拖拽、滚轮 | 缩放（永远可用） |
| 图区普通左键拖拽 | 平移（永远可用） |
| Measure 开启 + 拖拽 | 两点测距 |
| **幅度模式（最后点击幅度列）+ Shift+横向拖拽** | 框选时间区域 |
| **事件模式（最后点击 Event 面板）+ Shift+拖拽** | 画出 XY 矩形（X 幅度 < 视图宽度 1% 或 Y 幅度 < 视图高度 3% 视为误操作忽略）；拖已抓矩形内部 = 平移、拖四边中点 = 改范围（松手整组重抓） |

**幅度列 — 选段看分布**

1. **点击幅度列任意处即激活**（点 `»` 展开列也算），然后在主图内 **Shift+横向拖拽**框选时间区域（可框多个，颜色轮换）；**切回事件模式或折叠幅度列即删除全部区域**
2. 每个区域一条**水平直方图**（**纵轴 = 电流/电压，与主图 Y 轴对齐同步缩放**；横轴 = 占区域样本 %），多区域叠加、共用 bin 边界；区域列表（色块 + `×` 单删）在直方图上方
3. **[峰标尺]**：直方图上放置两条可拖**横线** A/B，实时读出两峰位置与差值 **Δ**（如两台电平差 → ΔI）
4. bin 数默认 Freedman–Diaconis（clamp 32–256），取消 `自动 bins`（auto bins）手动指定（**输入后按回车生效**）；bin 范围默认 p0.5–p99.5，勾选 `范围 = 视图Y`（range = view Y）跟随主图 Y 缩放；范围外样本计入 out-of-range 不丢弃；面板底部逐区域统计 N / mean / σ / p1–p99。

**Event 面板 — 区域抓取事件（一行一个甄别事件）**

工作流：圈一段 → 范围内检测 → **每个检出事件一行**（dwell 即该事件持续时间）→ 逐个甄别删留 → 导出给 notebook。参数快速调优也是抓一下试一下（0 个事件有红字提示，拖大矩形即可）。

1. **点击 Event 面板任意处即激活**（启动默认即事件模式），在主图内 **Shift+拖拽画 XY 矩形**——X = 分析时间范围，Y = 事件判定带（一个手势同时给出范围与带）；松开即检测：**范围内每个检出事件成为列表一行**（`# / t_start / dwell / level / 噪声`，**一行 = 一个事件**：dwell 列即该事件持续时间；**噪声列 = 该事件的分位包络，±电流/电压原生单位**——事件跨度内 90% 采样所在的波动带半宽（p5–p95，围绕事件电平），**含 spike 穿刺与慢纹波**（spike 链污染的段数值必然显著变大），孤立单点毛刺（<5% 样本）被折价；逐事件独立计算）。同一矩形抓出的事件为一**组**（同色、共用参数快照与来源标注）
2. **排序与编号**：列表默认按 `t_start` 升序，**点击 `t_start / dwell / level / 噪声` 任一列头循环：升 → 降 → 回默认**（按原始数值比较）；`#` 列是**当前显示顺序的名次**——删除自动补位、清空后从 1 重新开始、排序/整组重抓后重排，永不累计；`组#n` 同理显示组排名。数据列随树宽**自动铺满**。列表下方**两行统计行**对全部行（含跨数据灰显行）实时汇总：第一行 `N · 均 dwell/level/噪声`，第二行 `中位 dwell/level/噪声`
3. **0 个事件**：矩形**保留**并可继续拖边——多数是事件被边缘切断（红字显示边界丢弃数），把边缘拖离事件即可收全；**>500 个事件**拒绝入列并提示收小范围（本页用于逐个甄别，批量分析请用 notebook + `analysis.py`）
4. **矩形可编辑（整组重抓）**：拖**四边中点**改范围、拖**内部**平移，拖动中 150 ms 防抖预览事件数，松手按**当前参数**重新检测并**整组替换**该矩形的全部行（⚠ 手动删过的行会回来——整组重抓的复活语义）；**点一下矩形即选中它**（笔画加粗）。点列表行 = 左侧放大视图切换到该事件（**统一窗口**：X 宽 = 2×全体在屏事件的平均 dwell、以事件中点居中；Y 宽 = 2×在屏事件的平均区域跨度——区域 = 事件视窗内显示数据的 min–max（含两态整体摆幅），中心 = 该事件自己区域的中点——窗口宽度跨事件恒定、整体形貌完整可见，便于对比每个峰的相对大小）、**双击行主图跳转**；每行 `×` 单删（**删一行只删一行**：连点/双击有 250 ms 护栏不会误删多行，删除后选中落在接替该位置的那一行），**组内最后一行删掉时矩形一并移除**，[清空] 全删。**Ctrl(⌘)+Delete = 通用删除**，按"当前选中"解析对象：**选中的矩形 > 选中的事件行 > Measure 结果**（矩形连其全部行一并删除，带行时先弹确认；Measure 结果一键清空）；文本输入框内不拦截（保留原生的 Ctrl+Delete 删词），裸 Delete 仍是缩放撤销。**绿色高亮默认只画选中的那一个事件**（主图与放大视图一致）——选中即唯一绿段，方便在密集事件中定位。按钮行首位 **[显示全部]** 为审计模式：**主图保持当前缩放不变**，把**所有仍对应当前显示数据的事件**全部绿显——包括矩形组的事件**和导入 CSV 中 trace 正在显示的行**（选中的加粗；数据不在屏上的行无曲线可画）——快速检查所有方块里有没有选进不要的内容；再点一下回到只显示选中事件
5. **边缘语义**：被矩形边缘切断的事件（进入或离开发生在范围外）按**边界事件丢弃**并计数显示——dwell 不含半截事件；想收全某个事件，把矩形边缘拖离它即可
6. **独立参数**：模式（inside 带内=事件，默认）/滞回 k·σ/最短 ms/合并 s/忽略开头 ms/检测平滑 ms/带内占比（悬停每个参数有详细中文说明——两态数据 spike 密集时开 1–2 ms 平滑）；参数在**抓取/改边时快照**进组，之后改参数不回溯已存行，[全部重算] 才用当前参数整组重跑所有同源记录
7. **记录是分析日志**：换树选择/文件后**行保留**（dwell/level/σ 是快照），来源不同的行灰显、矩形自动从主图摘除；切回同一数据（文件+Join 状态+曲线一致）矩形自动恢复、可继续编辑
8. **[保存] / [另存为…]（v6，默认 `<数据文件名>_events.csv`）**：**扁平事件表 + `#` 参数头**——一行一个事件、全部行（含灰显）按 t_start 统一排序合并，共 18 列、两层（文件头 `#` 注释行说明单位/轴语义/检测参数，重开文档时参数自动恢复；`np.genfromtxt(..., names=True, comments='#')` 直接读）。**分组只是会话内的选取工具，不进文件**：矩形/组统计都属于过程，最终交付物就是这张合并事件表。v5/v4/v3 旧文件照常打开（缺参数头 = 沿用当前参数，缺 `file_hash` 列 = 走旧版路径/同名同大小溯源）
   - **① 事件数据（1–6 列）**：`event_id, t_start, t_end, dwell, y_level, noise_sigma`——`event_id` 是本次导出的名次（删行会移位，**不可当键**）；跨文件合并时用自然键 `(source_file, trace_g/s/w/t, t_start)` 对齐同一事件
   - **② 轴语义 + 溯源（7–18 列）**：`join`（True = t 列在拼接连续轴上，False = sweep 原生轴——解释时间列必看）+ `source_file` + 每事件 trace 指纹（`trace_g/s/w/t` 树路径——**事件归属哪个 sweep**，Join 下也按接缝反查填了；`trace_n/trace_dt/trace_yunit` 点数/采样间隔/单位——y 列的权威单位）+ `file_size/file_hash/file_mtime`（`file_hash` = 溯源 .dat 的**内在内容指纹**——sha256 前 4 MiB，移动/重命名/跨机器不变、跟随模式追加写入也不变，**行挂载只看它、与路径无关**；其余两列咨询性）
9. **打开 CSV = 打开文档（文件浏览器双击，见第 10 条）**：载入 v6/v5/v4/v3 导出的 CSV（**v3 旧格式自动兼容**——stitch 列静默映射为 join），**按行原样恢复，不重检测、不恢复矩形/分组**（分组是选取工具，想重新甄别就重新画框），然后**自举恢复现场**——加载溯源 .dat（v6 按 `file_hash` 内容指纹定位，路径无关）、选中被引用 trace 所在的 series（Join 拼接轴不缺 sweep）、恢复 Join。**逐行匹配**：每行带自己的 trace 指纹——指纹哈希不符（不是同一采集）或找不到的行灰显保留（选中该行会提示要显示哪条 trace / 匹配哪种 Join 状态才亮），**对应 trace 被显示出来的行立即点亮**。**v2 分组格式（含 group_id 列）导入时明确拒绝**；打开 = 新 tab（现有文档不受影响），关闭脏 tab 才确认；摘要弹窗按行统计（已挂到当前显示 / 在当前文件但未显示 / 来自其他数据），全部干净挂上则静默
10. **文件浏览器（Event 面板最右列，可折叠）**：MATLAB 式当前目录浏览器——列表原生实时监听文件系统，导出/同步盘落盘的 CSV 即时出现；**加载 .dat 后文件列自动定位到该文件所在目录**（F5 / 跟随刷新不挪动）；**双击 CSV = 直接导入**（v4 校验/替换确认/逐行匹配/报告一个不少，导入是文件列的专属入口）；列表**目录置顶、名称排序（数字感知：a2.csv < a10.csv）**；**双击目录进入**、`↑` 返回上级（到文件系统根后禁用）；**选中一项按 回车 / F2 = 重命名**（文件与目录均可；重命名打开中的文档 tab 或已加载的 .dat 会自动跟上新路径，保存不会再写回旧文件名；与目标重名、含 `/` 或为空则提示并还原）；`仅 CSV` 过滤开关（开 = 只显示 *.csv，目录始终显示；关 = 全部文件）、`↻` 强制刷新兜底；`»` 头部按钮可把整列折成右侧细条（`«` 展开）；当前目录与开关跨会话记忆（`explorer/*`，目录跟随最后一次加载的 .dat）
11. 参数与左右分割条跨会话记忆（`grab/*`、`layout/grabsplit`）；幅度列的折叠态与分割位也记忆（`layout/collapsed/amp` 默认收起、`layout/ampsplit`）；**记录本身不持久化**，关应用即清（导出 CSV 保结果，导入 CSV 恢复现场）

**跨 sweep 的长事件（重要）**：同一 Series 的多个 sweep 时间轴互相重叠，per-trace 检测会把跨越 sweep 边界的态驻留切碎成边界事件丢弃。要分析**持续时间超过单次 sweep 的两态驻留**，请**开启 Join**——检测会自动改跑拼接后的连续时间轴（每条 sweep 的开头瞬态照常切掉），事件在真实实验时间轴上完整检出（Grab 页同理：开 Join 抓的矩形在拼接轴上）。

> - 「检测平滑」只作用于检测层（显示不变）；dwell/边界精度受窗宽限制（如 1 ms 窗 → 1 ms 粒度）。
> - Amplitude 区域坐标跟随当前显示轴：开 Join 后区域/直方图都在拼接时间轴上。

### 1.6 性能说明

已开启 `peak` 模式降采样 + 视口裁剪：选整个 Group（数百条、全文件 460 MB）也能流畅缩放，且降采样不丢失 spike 尖峰。注意选 Group 会把全部数据载入内存（约 1.6 GB），日常按 Series/Sweep 浏览更轻量。

---

## 2. 导入方法（HekaFile 使用第一步）

本包不是安装包，需要先把**包的父目录**（即 `experiment/`）加入 `sys.path`：

```python
import os
import sys
sys.path.insert(0, os.path.abspath("../.."))   # 路径按你的运行位置调整

from heka import HekaFile
```

`os.path.abspath` 的参数写法取决于你在哪里运行：

| 运行位置 | 相对路径 | 说明 |
|---|---|---|
| `experiment/data/26-09-14-cbd/vis.ipynb` | `"../.."` | 上两级回到 `experiment/` |
| `experiment/` 下的脚本 | `"."` 或 `os.path.dirname(os.path.abspath(__file__))` | 就在本目录 |
| 其他任意位置 | 绝对路径，如 `"/Users/xxx/experiment"` | 最稳妥 |

也可以完全绕开相对路径，直接写绝对路径：

```python
import sys
sys.path.insert(0, "/Users/zhenyuwei/nutstore/paper/25-12-spike-transport/experiment")
from heka import HekaFile
```

判断标准：`sys.path` 里的目录下必须能找到 `heka/` 这个文件夹。

---

## 3. HekaFile 使用方法

### 3.1 构造与查看目录

```python
rec = HekaFile("data.dat")   # 只解析头部，约 1 秒，不读采样数据
rec.list()                   # 打印全部 series 的序号/标签/sweep数/采样率
```

输出示例：

```
[ 0] '100mv': 10 sweeps, 200000 pts, dt=5e-05s, Y=A
[ 5] '-200mv-kcl': 21 sweeps, 200000 pts, dt=5e-05s, Y=A
...
```

### 3.2 两种定位 series 的模式

| 模式 | 写法 | 说明 |
|---|---|---|
| **标签模式** | `rec.get("-200mv-kcl", ...)` | 按名称匹配，直观 |
| **顺序模式** | `rec.get(5, ...)` | 直接用 `list()` 打印的序号 |

标签有重名时（如本数据 `'100mv'` 出现 7 次），用 `occurrence` 选第几个匹配（从 0 数）：

```python
rec.get("100mv", sweep=0, occurrence=1)   # 第 2 个叫 '100mv' 的 series
```

### 3.3 核心方法

```python
t, y = rec.get(label, sweep=0, trace=0, occurrence=0, group=0, unit="A")
```

| 参数 | 含义 |
|---|---|
| `label` | 字符串=标签模式 / 数字=顺序模式 |
| `sweep` | 该 series 下第几次重复采集（0 起） |
| `trace` | 记录通道号（本数据每 sweep 只有 `Imon-4` 一个通道，保持 0） |
| `occurrence` | 重名标签消歧 |
| `unit` | `"A"`(默认) / `"pA"` / `"nA"` / `"mA"` / `"uA"`；电压族 `"V"` / `"mV"` / `"uV"`，同族自动换算 |

返回 `(t, y)`：时间轴数组（秒）+ 信号数组（按 `unit`）。电压钳通道原生单位 A，电流钳通道原生 V——`unit` 必须与原生同族（如电流钳数据传 `unit="mV"` / `"V"` 均可），跨族会报 `ValueError`。每次调用只读这一条数据（懒加载）。

```python
n = rec.n_sweeps(label, occurrence=0, group=0)   # 该 series 有多少个 sweep
```

### 3.4 完整示例（notebook）

```python
import os
import sys
sys.path.insert(0, os.path.abspath("../.."))

import matplotlib.pyplot as plt
from heka import HekaFile

rec = HekaFile("data.dat")
rec.list()

# 单条记录
t, y = rec.get("-200mv-kcl", sweep=5, unit="pA")
plt.figure()
plt.plot(t, y)
plt.xlabel("Time (s)")
plt.ylabel("Imon (pA)")
plt.show()

# 电流钳 series（原生单位 V）: 电压族单位换算
t, v = rec.get(23, sweep=15, unit="mV")          # 伏特 -> 毫伏
plt.plot(t, v)
plt.xlabel("Time (s)")
plt.ylabel("Vm (mV)")
plt.show()

# 整个 series 的所有 sweep 叠加
plt.figure()
for w in range(rec.n_sweeps("-200mv-kcl")):
    t, y = rec.get("-200mv-kcl", sweep=w, unit="pA")
    plt.plot(t, y, lw=0.5, alpha=0.6)
plt.xlabel("Time (s)")
plt.ylabel("Imon (pA)")
plt.show()
```

### 3.5 常见报错

| 报错 | 原因 |
|---|---|
| `KeyError: no series labeled '...'` | 标签写错，先 `rec.list()` 核对 |
| `IndexError: '...' has N matches, occurrence=... out of range` | 重名 series 的 occurrence 越界 |
| `ValueError: unsupported unit` | `unit` 拼写错误（如 `"PA"`），或与原生单位跨族（电压钳通道用 A 族、电流钳通道用 V 族），可用值见 3.3 |
| `ModuleNotFoundError: No module named 'heka'` | `sys.path` 路径不对，见第 2 节 |

---

## 4. 底层接口 `reader.Bundle`

`HekaFile` 不够用时可直接用底层 API：

```python
from heka import Bundle

b = Bundle("data.dat")
pul = b.pul                      # 元数据树
tr = pul[0][5][0][0]             # [group][series][sweep][trace]
y = b.data[0, 5, 0, 0]           # 原始数据（单位 A）

tr.DataPoints                    # 点数
tr.XInterval, tr.XUnit           # 采样间隔、时间单位
tr.YUnit                         # 数据单位
tr.Label                         # 通道名（如 'Imon-4'）
tr.RsValue, tr.CSlow, ...        # 放大器状态、密封质量等全套元数据
```

## 5. 数据层级速查

| 层级 | 含义 | 本数据（26-09-14-cbd） |
|---|---|---|
| Group | 实验组 | 1 个（`E-1`） |
| Series | 一个实验条件 | 27 个（−350 ~ +300 mV 各种电压/KCl 条件） |
| Sweep | 同条件下的重复采集 | 每系列 1–67 次，每次 10 s |
| Trace | 记录通道 | 每 sweep 1 个（`Imon-4`） |
| 采样率 | — | 20 kHz（前 14 系列）/ 100 kHz（后续） |
| 单位 | — | 电压钳系列安培（A），画图建议 `unit="pA"`；电流钳系列（如 series 23）原生伏特（V），读取时传 `unit="V"` / `"mV"` / `"uV"` |

## 6. 打包为可执行文件（PyInstaller）

无需安装 Python、双击即用的独立程序（onedir 模式，含浅色主题）。**PyInstaller 不支持交叉编译**——每个平台的产物必须在对应系统上构建。

| 平台 | 构建命令（在对应系统上跑） | 产物（自动打 zip） |
|---|---|---|
| macOS | `bash build_mac.sh`（本机已验证：启动 ~0.1–1 s） | `dist/HekaBrowser.app` + `HekaBrowser-mac.zip`（~35 MB） |
| Windows | 双击 `build_windows.bat`（需先装一次 [Python 3.12](https://www.python.org/downloads/)，勾选 Add to PATH） | `dist/HekaBrowser/` → `HekaBrowser-windows.zip` |
| Linux | `bash build_linux.sh`（**在 Ubuntu 22.04 等最老目标系统上构建**，glibc 向后兼容） | `dist/HekaBrowser/` → `HekaBrowser-linux.zip` |

脚本会自动创建独立构建环境（`hekabuild` conda env / `build-venv`，Python 3.12 + pip 版 PyQt5/PyInstaller），不影响日常实验环境。

**为什么用 onedir 而不是单文件**：onefile 每次启动都要把 ~150 MB 解压到随机临时目录并重新链接全部 Qt 动态库（冷启动 2–8 s，且 macOS 弃用该模式）；onedir 文件就地存放，启动稳定在 **0.1–1 s**、冷热一致。分发时把产物打成 zip（脚本自动完成），接收方解压后双击里面的 `HekaBrowser.app` / `HekaBrowser.exe` / `HekaBrowser`。

**日常使用建议**：把 `HekaBrowser.app` 拷贝到 `/Applications`（或 `~/Applications`）使用——一是离开坚果云等同步文件夹（避免打开时等同步/下载），二是 Gatekeeper 对路径+签名缓存后不再重复扫描。

**接收方首次放行（未签名应用）**

| 平台 | 提示 | 处理 |
|---|---|---|
| macOS | 「无法验证开发者」 | 右键 App → 打开；或终端 `xattr -cr /path/HekaBrowser.app` |
| Windows | SmartScreen 蓝色警告 | 「更多信息」→「仍要运行」 |
| Linux | 无执行权限 | `chmod +x HekaBrowser`（解压后执行） |

**排障**

| 症状 | 原因/处理 |
|---|---|
| Linux 报 `GLIBC_2.xx not found` | 构建机 glibc 太新——换更老的系统（如 Ubuntu 22.04 容器）重新构建 |
| Windows 杀软报毒 | PyInstaller 打包常见误报，加白名单即可 |
| 双击 mac App 一闪而过 | 先在终端跑 `dist/HekaBrowser.app/Contents/MacOS/HekaBrowser` 看报错 |
| Linux 双击无反应 | 确认 `chmod +x`；桌面环境不同双击行为各异，可终端运行 |

## 出处

`reader.py` 与 `browser.py` 源自 [campagnola/heka_reader](https://github.com/campagnola/heka_reader)（Luke Campagnola，2015），在本项目中已适配 Qt5/PyQt5 并扩展了层级多选显示功能。
