# AGENTS.md — heka（HEKA .dat 读取 + pyqtgraph 浏览器）

## 运行与构建

- 日常开发/运行：conda env `experiment`（`/Users/zhenyuwei/Program/anaconda3/envs/experiment/bin/python3`，Python 3.14 + PyQt5 + pyqtgraph 0.14）。在本目录 `python browser.py` 即可启动，改代码即时生效。
- **不要主动打包。只在用户明确要求时才运行 `bash build_mac.sh`**（Windows/Linux 对应 `build_windows.bat` / `build_linux.sh`）。
- 打包用独立 conda env `hekabuild`（Python 3.12 + pip 版 PyQt5/PyInstaller，脚本自动创建）。**绝不能从 `experiment` env 打包**（conda Qt + PyInstaller 是雷区）。产物：`dist/HekaBrowser.app` + zip，onedir 模式（别改回 onefile）。
- 本目录**是 git 仓库**（2026-09 初始化，baseline 在首次提交）；commit 用 `-c user.name/user.email` 显式指定身份。

## 架构要点

- `browser.py` 没有函数式入口：整个 UI 在**模块级**构建，文件末尾 `if sys.flags.interactive == 0: app.exec_()` 进入事件循环。
- 所有颜色集中在 `browser.py` 顶部 `THEME`；应用强制浅色（Fusion + QPalette，与 macOS 深色模式解耦），改配色只动 THEME。
- 单位换算按族（`utils.py` 的 `_UNIT_FAMILIES`）：跨族必须 raise、同单位直通。电压钳数据原生 A、电流钳原生 V；`get()` 默认 `unit="A"` 是用户明确保留的决定。
- 左列三个可折叠区块（`sec_tree` / `sec_nano` / `sec_info`）在垂直 QSplitter 里，折叠靠 `setMaximumHeight` 技巧（QSplitter 会保留隐藏控件的空间）。右侧是 `dist_split`（主图 + `sec_dist` Distribution 面板）。
- 树节点文本是路径式编号 `G0 S26 W3 T0`（对应图例 `(G#g S#w W#)` 和 `rec.get(N)`）；选中/绘图逻辑全部走 `item.index`，不要解析节点文本。
- 分析库 `analysis.py` **纯 numpy、零 Qt**（GUI / notebook / 测试共用）；GUI 侧 `replot()` 把每条显示曲线的原始数组缓存进 `last_data = [(x, y, label, trace)]`，检测/直方图**永远按 per-trace 跑**（sweep 时间轴重叠，绝不能在拼接曲线上检测）。
- Distribution 面板控件全在 tab 内（顶部按钮行无相关按钮）：Amplitude = 「添加区域」开关（**互斥 Measure**，图区左键拖拽归属其一）+ 区域列表（色块+×）；Events = 「启用检测」开关 + Y 范围 lo/hi 数值框（**单位自动取 SI 前缀**，与主图青色带双向同步，`_band_syncing` 防回环，`_yunit_scale` 缓存换算系数）+ 事件表（双击跳转）/CSV。
- 事件带**自动放置必须放尾部（事件侧）**：`detect_toggled` 比较上/下尾取 [p75,p99] 或 [p1,p25]——inside 模式带子放基线上会把半条曲线判成事件（G0 S19 绿色冲刷事故的根因）。事件边界插值 frac 夹取 [0,1]（`analysis._cross_time`），否则滞回缓冲区退出会外推出**负 dwell**。
- 「启用检测」**不持久化**（幽灵状态事故：持久化 + 哨兵带 (0,1)A → 每次启动全图铺绿）。`_band_placed` 标志：启用时无数据则等 replot 有数据后再补放带。
- **Stitch 联动检测**：`_stitch_active` 时 `analysis_segments` 返回拼接连续轴单段（跨 sweep 态驻留才能完整检出），否则按 per-trace。`_prepped`/`_stitch_cache` 以 `(id(last_data), head_s, smooth_ms)` 为键缓存；拼接轴累加必须用**抽稀后的实测间距**（用 `trace.XInterval` 会把时间轴压缩 w 倍）。平滑 = 不相交窗中位数压缩（`dist/smooth`），spike 密集两态数据配 1–2 ms + duty_min=0.5 用；`t_min` 按原始采样率计、内部除以窗宽换算。
- overlay 曲线有点数护栏（全量 >2M 采样时按 stride 抽稀，仅视觉层；检测/统计永远全分辨率）；事件数 >5 万时头条警告带子可能贴基线/噪声。

## 测试（无正式测试套件）

- 快速语法门：`python3 -m py_compile <file>`。
- 分析库测试：`python3 test_analysis.py`（合成数据，确定性，无需 GUI/pytest）。
- GUI 冒烟测试模式：`QT_QPA_PLATFORM=offscreen`；exec `browser.py` 源码并把 `if sys.flags.interactive == 0:` 替换为 `if False:`（跳过事件循环），然后直接调用模块全局里的函数/控件。
- **QSettings('heka','browser') 跨运行持久化**（`stitch`、`last_dir`、`layout/hsplit`、`layout/vsplit`、`layout/distsplit`、`layout/collapsed/*`、`dist/*`（mode/k/t_min/merge/head/smooth/duty/ccdf，**不含启用开关**）、`amp/bins*`、`amp/follow`，测试和真实 .app 都会写）。断言默认布局/状态前必须先 `settings.clear()`/`remove(...)`，且要在 **exec 之前** clear（模块级 setChecked 会触发 toggled 处理器写回）。
- 现成的完整冒烟脚本在 `/var/folders/ts/jr156kps24x69kvjj0fkmp580000gn/T/opencode/`（临时目录，丢了就按上述模式重建）：`smoke_test.py`（树编号、折叠布局+持久化、Measure A/B+拖拽测距、Nano 自动填充、单位、主题、Stitch、百分位拟合）和 `dist_smoke.py`（添加区域+区域列表、启用检测+Y 范围双向同步+SI 单位、尾部自动放带、Stitch 联动跨缝事件、duty 过滤碎片链、事件表+CSV、滞回报错路径、互斥、持久化差异；注入 last_data 需带 `XInterval` stub，改 last_data 后依赖 `_prep_cache` 按 `id(last_data)` 自动失效）。测试读数断言注意：TextItem/QLabel 渲染 HTML，**`.text()` 返回源码字符串安全**，TextItem 的 `toPlainText()` 连续空格会折叠、不要原样比较。

## pyqtgraph 0.14 陷阱

- `pg.ptime` 已移除（用标准库 `time`）。
- `MouseClickEvent` 没有 `.isDrag()`（点击判定：移动 ≤5px 或 ≤0.5s）。
- `QSplitter.setSizes` 只接受 int 列表；`setSizes` 后 Qt 会按 sizeHint 重新分配，**断言 sizes 别用精确相等**。
- `PlotCurveItem(stepMode='center')` 的 x 必须是**bin 边**（len = N+1），不是中心点。
- 中文输入法：`NumericEdit` 已处理全角 `。`/`，`，测试用例覆盖它们。

## 文档

`README.md`（中文）是用户手册：1.2 操作 / 1.3 Measure / 1.4 Nano / 1.5 Distribution / 6 打包。改功能要同步对应小节，列表编号保持连续（手动维护，容易漏）。
