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

1. 点 **Load...** 选择 `.dat` 文件（只解析头部，秒开）；加载后按钮下方路径栏显示完整路径——可直接鼠标选中复制（Cmd+A 全选 / Cmd+C），路径过长时横向滚动查看
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
6. **左列布局**：按钮行（固定）下方是三个**可折叠区块**——`▾ File tree` / `▾ Nanopore calculator` / `▾ File info`（路径栏 + 元数据树），区块间有分割条可任意拖动分配高度；点击标题折叠/展开（折叠后只剩一行标题）。默认 File info 最矮（约 150 px）；**折叠状态与分割位置跨会话记忆**，下次打开自动还原
7. **配色**：浅色现代主题（米白背景 + 深灰文字），整个应用**强制浅色**（Fusion 样式 + 浅色调色板，不受 macOS 深色模式影响，三平台外观一致）。曲线色环分三档：≤10 条 Tableau 10，11–20 条 Tableau 20（深浅两版），>20 条低饱和金比例色相环（S=.55/V=.78，几百条也柔和可辨，颜色按序号确定不漂移）；十字光标橙色、A/B 标记红/蓝、读数为半透明白底浮框、图例白底。全部颜色集中在 `browser.py` 顶部 `THEME` 字典，想微调只改这一处
8. **缩放与导航**：

| 操作 | 行为 |
|---|---|
| **X 轴条**上按住左键拖拽拉范围 | 实时竖直半透明预览，松开**只缩放 X** |
| **Y 轴条**上按住左键拖拽拉范围 | 水平预览，松开**只缩放 Y** |
| 鼠标滚轮（图区或轴条上均可） | XY 双轴同步缩放，以光标为中心 |
| 图区内左键拖拽 | 平移视图 |
| **Delete** / **Backspace** | **撤销上一个缩放**（滚轮连续滚动合并为一步；历史用完后再按不动作） |
| **Stitch**（开关按钮） | 多选时把各条曲线按采集顺序首尾拼接成**一条连续曲线**：时间轴无缝递增，sweep 交界画浅灰竖虚线；单选时无效果；状态跨会话记忆 |
| 每次切换选中节点 | 坐标轴自动适配新数据 |

**Auto 按钮 / 加载曲线的 Y 轴自适应**采用 **1–99 百分位 + 5% 边距**（基于原始数据计算）：每条 sweep 开头的电容充放电尖峰只占极少量采样点，不会压扁 Y 范围，开/闭合电流与 nanopore 事件保持在视野内。Auto 同时清空缩放撤销历史。

> Stitch 拼接会把选中数据完整复制一份：Series 级（几十 MB）无压力；整 Group（GB 级）内存会翻倍，建议按 Series 拼接。拼接曲线上测量（十字线 / A-B 差值）照常可用，y 读数是真实采样点，`dy/dt` 跨拼接段无物理意义。

9. **Measure 测量** / **Nano 计算器面板** / **Distribution 分布面板**：见 1.3–1.5 节

### 1.3 Measure 测量模式

按钮行的 **Measure** 为开关式按钮，开启后进入测量模式。读数**浮动显示在图区左上角**（半透明白底深灰字，锚定视窗左上角跟随缩放，不占布局空间、任意行数完整可见）：

```
cursor: x=460.523 ms, y=460.531 pA [-200mv-kcl (G0 S5 W3)]    ← 光标当前位置
A: x=120.1 ms, y=101.2 pA                                     ← 单击落 A 点后出现
B: x=380.7 ms, y=890.4 pA                                     ← 再单击落 B 点后出现
dt=260.6 ms  dy=789.2 pA  dy/dt=3.028 nA/s                    ← AB 齐后出现
```

- **实时十字线**：鼠标移动时橙色虚线跟随；`cursor` 行显示**光标所在位置的原始坐标**（连续平滑，不吸附采样点）。方括号内为所在拼接段/最近曲线名；**Stitch 模式下自动显示所在拼接段**（series 标签 + 0 基编号，如 `[-200mv-kcl (G0 S5 W3)]`，与树节点编号对应）
- **两点差值测量（点击）**：单击落 A 点（红圈），再单击落 B 点（蓝圈）——A/B **吸附到真实采样点**（原始数据，不受显示降采样影响），B 锁定与 A 相同的曲线（Stitch 下同一条拼接曲线）。完成一组后，下一次单击自动开始新的一组
- **自由测距（拖拽）**：Measure 开启时**按住左键拖拽**可测量**任意两点**的 dx / dy / dy/dx——不吸附轨迹，适合量噪声基底到峰顶、两条 trace 间距等场景。拖动时实时显示橙色虚线 + 读数 `drag` 行；松开后结果保留在图上（虚线 + 中点标签），下一次拖拽自动替换。注意：Measure 开启期间图区拖拽被测距接管（不平移），轴条拖拽缩放不受影响，需要平移时取消 Measure 勾选即可
- **Clear**：清除所有测量标记和读数
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

### 1.5 Distribution 分布面板（选段看分布 / 事件检测）

主图下方是可折叠的 `▾ Distribution` 面板，*Amplitude*（选段看幅度分布）与 *Events*（事件检测）两个标签页，**所有开关和参数都在 tab 里**（左上按钮行没有相关按钮）。分析永远基于**每条曲线的原始采样数组**（per-trace，不是拼接显示曲线），由纯 numpy 库 `analysis.py` 完成——GUI 与脚本共用同一入口：

```python
from heka.analysis import detect_events, detect_events_segments, all_point_histogram
```

**Amplitude 页 — 选段看分布**

1. 点 **[添加区域]**（按钮保持按下；与 Measure 互斥，两者都接管图区左键拖拽）
2. 在主图内**左键拖拽**框选时间区域（可框多个，颜色轮换，边缘可拖动微调）
3. 每个区域一条直方图（横轴 = 占区域样本 %，纵轴 = 电流/电压，**与主图 Y 轴联动**——直方图峰与主图电流水平线同高），区域列表（色块 + `×` 单删）显示在直方图上方

参数：bin 数默认 Freedman–Diaconis（稳健 IQR，clamp 32–256），取消 `auto bins` 可手动指定；bin 范围默认稳健百分位 p0.5–p99.5，勾选 `range = view Y` 后跟随主图 Y 缩放（拉到哪算到哪）；范围外样本计入 out-of-range 统计，不静默丢弃；多区域**共用同一套 bin 边界**（按合并数据计算），同一物理水平不会错位。面板底部逐区域统计 N / mean / σ / p1–p99。

**Events 页 — 事件检测（阈值带 + 滞回）**

工作流从上到下：

1. **[启用检测]**（跨会话记忆；启用时若面板折叠会自动展开）——主图出现**青色 Y 范围带**
2. **Y 范围**：拖主图上带子的两条线，或直接在 `lo` / `hi` 数值框输入——**两者双向同步**。带子应圈住**事件电流水平**（分布尾部），不要圈基线；自动放置也是这个逻辑（比较分布上/下尾，带子放更重的一侧 [p75, p99] 或 [p1, p25]）
3. **边沿判定**：事件 = 信号进入带沿到离开带沿（边界按相邻采样线性插值，亚采样精度）。默认 `inside` 模式（带内=事件，不假定基线）；`outside`（带外=事件，上下双向尖峰）、`below` / `above`（单阈值）下拉切换。**滞回 k·σ**：信号须明确离开带宽 k·σ 才算事件结束，防止噪声在带沿反复进出把一个事件拆成多个（σ 自动稳健估计，k=0 即纯进出语义）；**最短时长（点）**去毛刺；**合并 (s)** 把间隙小于该值的事件并回一个
4. **结果**：头条显示 `发现 N 个事件 · 速率`；主图上事件段**绿色高亮**；dwell 直方图（**对数 bin**）+ 事件内绝对平均电平直方图；勾选 `1-CDF (log-log)` 切换存活函数视图（判幂律/多指数）
5. **事件表 / 导出 CSV**：事件表列出全部事件的 sweep/t_start/t_end/dwell/level（表格最多显示 1000 行），**双击一行主图跳转到该事件**；CSV 导出全量
6. 底部统计：dwell 中位数/均值、电平中位数、实际 h 与 σ、**边界事件**（跨数据首尾、进/出未被观测到）自动丢弃并注明数量

> - 事件数 > 5 万时头条会提示"带子可能贴着基线/噪声"——先检查 Y 范围。
> - Stitch 拼接只是显示行为：同一 Series 的多个 sweep 时间轴重叠，检测/直方图始终按原始 per-trace 数据运行。
> - 带子可见但检测关闭时不做任何计算；拖带子实时刷新（拖动中抽样预览、松手全量重算）。

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
