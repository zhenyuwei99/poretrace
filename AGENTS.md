# AGENTS.md — heka（HEKA .dat 读取 + pyqtgraph 浏览器）

## 运行与构建

- 日常开发/运行：conda env `experiment`（`/Users/zhenyuwei/Program/anaconda3/envs/experiment/bin/python3`，Python 3.14 + PyQt5 + pyqtgraph 0.14）。在本目录 `python browser.py` 即可启动，改代码即时生效。
- **不要主动打包。只在用户明确要求时才运行 `bash build_mac.sh`**（Windows/Linux 对应 `build_windows.bat` / `build_linux.sh`）。
- 打包用独立 conda env `hekabuild`（Python 3.12 + pip 版 PyQt5/PyInstaller，脚本自动创建）。**绝不能从 `experiment` env 打包**（conda Qt + PyInstaller 是雷区）。产物：`dist/HekaBrowser.app` + zip，onedir 模式（别改回 onefile）。
- 本目录**不是 git 仓库**——不要尝试 commit/branch。

## 架构要点

- `browser.py` 没有函数式入口：整个 UI 在**模块级**构建，文件末尾 `if sys.flags.interactive == 0: app.exec_()` 进入事件循环。
- 所有颜色集中在 `browser.py` 顶部 `THEME`；应用强制浅色（Fusion + QPalette，与 macOS 深色模式解耦），改配色只动 THEME。
- 单位换算按族（`utils.py` 的 `_UNIT_FAMILIES`）：跨族必须 raise、同单位直通。电压钳数据原生 A、电流钳原生 V；`get()` 默认 `unit="A"` 是用户明确保留的决定。
- 左列三个可折叠区块（`sec_tree` / `sec_nano` / `sec_info`）在垂直 QSplitter 里，折叠靠 `setMaximumHeight` 技巧（QSplitter 会保留隐藏控件的空间）。
- 树节点文本是路径式编号 `G0 S26 W3 T0`（对应图例 `(G#g S#w W#)` 和 `rec.get(N)`）；选中/绘图逻辑全部走 `item.index`，不要解析节点文本。

## 测试（无正式测试套件）

- 快速语法门：`python3 -m py_compile <file>`。
- GUI 冒烟测试模式：`QT_QPA_PLATFORM=offscreen`；exec `browser.py` 源码并把 `if sys.flags.interactive == 0:` 替换为 `if False:`（跳过事件循环），然后直接调用模块全局里的函数/控件。
- **QSettings('heka','browser') 跨运行持久化**（`stitch`、`last_dir`、`layout/hsplit`、`layout/vsplit`、`layout/collapsed/*`，测试和真实 .app 都会写）。断言默认布局/状态前必须先 `settings.clear()`/`remove(...)` 再 `_restore_layout()`。
- 现成的完整冒烟脚本在 `/var/folders/ts/jr156kps24x69kvjj0fkmp580000gn/T/opencode/smoke_test.py`（临时目录，丢了就按上述模式重建；覆盖树编号、折叠布局+持久化、Measure A/B+拖拽测距、Nano 自动填充、单位、主题、Stitch、百分位拟合）。测试读数断言注意：TextItem 渲染 HTML，连续空格会折叠，不要原样比较 `toPlainText()`。

## pyqtgraph 0.14 陷阱

- `pg.ptime` 已移除（用标准库 `time`）。
- `MouseClickEvent` 没有 `.isDrag()`（点击判定：移动 ≤5px 或 ≤0.5s）。
- `QSplitter.setSizes` 只接受 int 列表。
- 中文输入法：`NumericEdit` 已处理全角 `。`/`，`，测试用例覆盖它们。

## 文档

`README.md`（中文）是用户手册：1.2 操作 / 1.3 Measure / 1.4 Nano / 6 打包。改功能要同步对应小节，列表编号保持连续（手动维护，容易漏）。
