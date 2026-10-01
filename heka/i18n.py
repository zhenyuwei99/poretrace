"""UI constants for the Heka browser: theme palette + zh/en strings + T().

Pure data plus one lookup, split out of browser.py so the main module
carries logic only. browser.py re-imports T/L10N/THEME/_ui_lang as flat
module globals -- the offscreen smoke tests reach them there
(m['T'], m['L10N'], m['THEME'])."""

import pyqtgraph as pg

# Light modern theme: all colors in one place, tweak here only
THEME = {
    'bg':         '#FAFAFA',                    # plot background (off-white)
    'fg':         '#333333',                    # axes / ticks / legend text
    'crosshair':  '#FF7F0E',                    # orange dashed crosshair
    'A':          '#D62728',                    # A marker (red)
    'B':          '#1F77B4',                    # B marker (blue)
    'readout':    '#1F1F1F',                    # readout text
    'readout_bg': (255, 255, 255, 190),         # translucent white panel
    'seam':       '#B0B0B0',                    # join seam dashed lines
    'band':       '#76B7B2',                    # Detect threshold band (teal)
    'event':      '#59A14F',                    # event highlight / event hists
    'import':     '#9C9C9C',                    # groupless imported rows (CSV v3)
    'accent':     '#4E79A7',                    # mode-active highlight (Tableau blue)
    'accent_tint': '#E3EDF6',                   # active-mode hint pill background
    # Tableau 10 for <= 10 traces; Tableau 20 (deep+light shades) for <= 20;
    # beyond that a muted golden-ratio hue walk -- distinguishable, no neon
    'cycle':      ['#4E79A7', '#F28E2B', '#E15759', '#76B7B2', '#59A14F',
                   '#EDC948', '#B07AA1', '#FF9DA7', '#9C755F', '#BAB0AC'],
    'cycle20':    ['#4E79A7', '#A0CBE8', '#F28E2B', '#FFBE7D', '#59A14F',
                   '#8CD17D', '#B6992D', '#F1CE63', '#499894', '#86BCB6',
                   '#E15759', '#FF9D9A', '#79706E', '#BAB0AC', '#D37295',
                   '#FABFD2', '#B07AA1', '#D4A6C8', '#9D7660', '#D7B5A6'],
}

# Reads the same persistent scope as browser.py (ui/lang is written
# by the language button and honoured on the next launch).
# -- UI language (zh default; switching writes the setting and asks for a
# restart -- the UI is built once at module level, so live retranslation
# is not worth the machinery). All user-visible strings go through T();
# data-schema words (t_start/dwell/level/#, inside/outside/below/above,
# CSV column names, units) stay English in BOTH languages on purpose.
_ui_lang = pg.QtCore.QSettings('heka', 'browser').value('ui/lang', 'zh', type=str)
if _ui_lang not in ('zh', 'en'):
    _ui_lang = 'zh'

L10N = {
    'zh': {
        'btn.load': '打开…', 'btn.auto': '自动', 'btn.follow': '跟随文件',
        'btn.measure': '测量', 'btn.clear': '清除', 'btn.join': '拼接',
        'btn.tip.lang': '切换界面语言（中/EN），重启后生效',
        'tip.follow': '监视当前 .dat：Patchmaster 落盘新数据后自动重新解析并保持你的选中\n'
                      '（≈按 sweep 级延迟；需 Patchmaster 开启按 sweep 落盘/自动保存）。\n'
                      'F5 = 随时手动刷新。读到半截写入会静默跳过、下次文件变化自动重试。',
        'lang.title': '语言', 'lang.ask': '语言已切换，重启后生效。现在重启吗？',
        'sec.tree': '文件树', 'sec.nano': '纳米孔计算器', 'sec.info': '文件信息',
        'sec.dist': '事件', 'amp.title': '幅度',
        'exp.title': '文件', 'exp.csvonly': '仅 CSV',
        'exp.tip.csvonly': '开启 = 只显示 *.csv 文件（目录始终显示）；\n关闭 = 显示全部文件。',
        'exp.tip.up': '返回上级目录',
        'exp.tip.refresh': '强制刷新当前目录（列表本身实时监听文件系统，\n同步盘偶发丢事件时兜底）。',
        'exp.tip.list': '双击 CSV = 打开为分析文档（自举：定位溯源 .dat、选中对应 trace、恢复 Join）；\n双击目录 = 进入；其他文件双击无动作。\n选中一项后按 回车 / F2 = 重命名。',
        'tree.node': '节点', 'tree.label': '标签', 'info.nofile': '未载入文件',
        'dlg.open': '打开数据文件', 'reload.title': '重新加载',
        'reload.fail': '解析失败：文件可能正在写入中，请稍后再试。',
        'nano.solution': '溶液', 'nano.conc': '浓度 (M)',
        'nano.thick': '膜厚 (nm)', 'nano.volt': '电压 (mV)', 'nano.current': '电流',
        'amp.clear': '清空区域', 'amp.ruler': '峰标尺',
        'amp.autobins': '自动 bins', 'amp.follow': '范围 = 视图Y',
        'amp.tip.ruler': '在直方图上放置两条可拖动的横线 A/B，\n实时读取两个峰的位置与它们的差 Δ',
        'amp.hint': '幅度模式已激活（本列被最后点击）：按住 <b>Shift</b> 在主图内'
                    '<b>横向拖拽</b>框选时间区域（普通拖拽 = 平移，轴条拖拽 = 缩放）；'
                    '点击下方事件面板切回事件抓取。',
        'amp.hint.off': '点击本列任意处激活幅度模式：激活后按住 <b>Shift</b> 在主图内'
                        '横向拖拽框选时间区域；折叠本列会清除全部区域。',
        'amp.tip.hint': '按住 Shift 在主图内横向拖拽 = 框选时间区域（普通拖拽 = 平移，'
                        '轴条拖拽 = 缩放），\n松开后该区域内的全部采样点进入左侧直方图'
                        '（可叠加多个区域，各自统计）。\n'
                        '拖区域边缘可继续调整，切换到事件面板或折叠本列会清除全部区域。\n'
                        '窄列下提示文字会被截断——完整说明见此处。',
        'amp.nosamples': '区域未覆盖任何采样点',
        'amp.axisy': '区域样本占比 %',
        'amp.over.commit': '<span style="color:{c}">事件数 {n} 超过上限 {cap}——'
                           '请收小矩形范围（事件面板用于逐个甄别事件，'
                           '批量分析请用 notebook + analysis.py）</span>',
        'amp.over.edit': '<span style="color:{c}">事件数 {n} 超过上限 {cap}——'
                         '编辑未生效，请收小矩形范围</span>',
        'grab.hint': '事件模式已激活（本面板被最后点击）：<b>Shift+拖拽</b>画 XY 矩形'
                     '（X=时间范围，Y=事件带）；范围内每个检出事件一行，'
                     '拖四边/内部=整组重抓',
        'grab.hint.off': '点击本面板任意处激活事件模式：激活后 <b>Shift+拖拽</b> 主图画'
                         ' XY 检测矩形（X=时间范围，Y=事件带）。',
        'grab.tip.hint': '按住 Shift 在主图内拖拽画 XY 矩形（X=分析时间范围，Y=事件判定带），\n'
                         '松开即在范围内检测：每个检出事件成为右侧列表的一行（dwell 即该事件时长）。\n'
                         '同一矩形抓出的事件为一组（同色、共用参数快照）。\n\n'
                         '拖矩形四边（改范围）或内部（平移）松手后按当前参数整组重抓替换；\n'
                         '被矩形边缘切断的事件按边界事件丢弃（完整在内才保留）。\n'
                         '0 个事件时矩形保留，拖大边缘直到事件完整即可。\n\n'
                         '参数为快照制：在抓取/改边时刻存入记录，之后改动不回溯已存记录，\n'
                         '[全部重算] 才应用当前参数重跑全部同源记录。',
        'grab.p.mode': '模式', 'grab.p.k': '滞回 k·σ', 'grab.p.tmin': '最短 (ms)',
        'grab.p.merge': '合并 (s)', 'grab.p.head': '忽略开头 (ms)',
        'grab.p.smooth': '检测平滑 (ms)', 'grab.p.duty': '带内占比 ≥',
        'evt.tip.mode': '事件语义——四种模式共用同一套滞回/时长逻辑：\n'
                        'inside = 带内即事件（默认；不假定基线，带子圈住哪个电平，那段驻留就是事件）\n'
                        'outside = 带外即事件（基线在带中，上下双向尖峰）\n'
                        'below = y < hi 即事件（经典向下阻断，只用上边一条线）\n'
                        'above = y > lo 即事件（向上尖峰）',
        'evt.tip.k': '滞回 k·σ —— 事件结束的防抖门槛。\n'
                     '噪声会让信号在带沿反复进出；纯"进带=开始 / 出带=结束"会把一个真实\n'
                     '事件拆成大量碎片。滞回要求信号明确离开带宽 k 倍噪声 σ 才认定结束\n'
                     '（σ 由相邻采样差自动稳健估计，不受事件尖峰影响）。\n'
                     '默认 3 适合多数数据；噪声大或 spike 密可加到 5–8；0 = 完全关闭滞回',
        'evt.tip.tmin': '最短时长 —— 短于该时长的事件直接丢弃。\n'
                        '滤掉电容毛刺与 spike 穿过带沿产生的 ~0.1–0.3 ms 碎片；\n'
                        '两态驻留通常 ≥ 数 ms，所以 0.1–1 ms 很安全，只关心长驻留可加大到 10。\n'
                        '内部按原始采样率换算成点数，开启平滑后自动再除以窗宽',
        'evt.tip.merge': '合并 —— 相邻事件间隔小于该值时并成一个，把被 spike 短暂打断的\n'
                         '真实驻留重新接上。\n'
                         '⚠ 危险：spike 越密、碎片间隔越短，合并值过大会把整段信号串成一个\n'
                         '巨型"假事件"（事件电平被带外间隙稀释）。spike 密集时保持 0，\n'
                         '改用「检测平滑」压掉 spike +「带内占比」兜底',
        'evt.tip.head': '忽略开头 —— 每条 sweep 开头切掉这段时间，规避电容充放电瞬态\n'
                        '（本数据瞬态可达 ±2 nA，不切会在每个 sweep 开头产生假事件）。\n'
                        '10 ms 覆盖绝大多数情况；Join 模式下每条 sweep 的开头都会切',
        'evt.tip.smooth': '检测平滑 —— 检测前按窗宽做中位数压缩。\n'
                          '比窗窄的 spike 被压平、比窗宽的电平台完整保留——spike 密集的\n'
                          '两态数据的关键参数（建议 1–2 ms）。不开它时每个 spike 穿带都\n'
                          '产生碎片；开了它 dwell/边界精度降为窗宽粒度（1 ms 窗 → 1 ms）。0 = 关闭',
        'evt.tip.duty': '带内占比 —— 合并后事件跨度内真正在带内的时间占比，\n'
                        '低于该值即丢弃：spike 顶部碎片链占比通常 ~3%，真实驻留 >50%，\n'
                        '0.5 一刀分开。只对发生过合并的事件生效；0 = 关闭该过滤',
        'grab.col.noise': '噪声',
        'grab.viewall': '显示全部',
        'grab.tip.viewall': '审计模式：主图保持当前缩放不变，把选中组的全部检出事件绿显\n'
                            '（选中的加粗）——快速检查方块里有没有选进不要的内容。\n'
                            '关闭 = 主图只显示选中的那一个事件。',
        'grab.recalc': '全部重算',
        'grab.tip.recalc': '用当前参数整组重抓所有仍对应本数据的记录\n（整组替换语义：手动删过的行会回来）',
        'grab.clear': '清空',
        'csv.imp.title': '导入事件 CSV', 'csv.exp.title': '导出事件 CSV',
        'exp.rename.title': '重命名',
        'exp.rename.exists': '“{name}”已存在。',
        'exp.rename.badname': '名称不能为空，也不能包含 “/”。',
        'exp.rename.fail': '无法重命名：{err}',
        'doc.new': '新建分析文件', 'doc.newbtn': '新建',
        'doc.empty.hint': '点击上方按钮开始圈选事件（Shift+拖拽主图画 XY 矩形），'
                          '<br>或双击右侧文件列中的 CSV 直接打开已保存的分析。',
        'doc.save': '保存', 'doc.saveas': '另存为…',
        'doc.untitled': '未命名',
        'doc.close.title': '关闭文档',
        'doc.close.q': '“{name}”有未保存的修改（事件行）。保存并关闭、直接丢弃，还是取消？',
        'doc.savefail': '无法写入文件：{err}',
        'doc.empty.save': '当前没有事件行，保存的只会是表头——确定继续吗？',
        'csv.readfail': '无法读取文件：{err}',
        'csv.v2': '这是 v2 分组格式（含 group_id 列）——v3 起导出为扁平事件表、'
                  '不再存储分组信息，v2 已不再支持。',
        'csv.missing': '文件缺少必需列：{cols}\n请使用本版本导出的 grab CSV（v4 扁平事件表；'
                       'v3 旧格式自动兼容，v2 及更早的分组格式已不再支持）。',
        'csv.empty': '文件没有数据行。',
        'csv.nousable': '没有可用的记录{bad}。',
        'csv.badrows': '（{n} 行解析失败）',
        'csv.locate': '定位来源数据文件{suffix}',
        'csv.openfail': '无法打开来源文件，相关行按灰显导入：{err}',
        'csv.report': '已导入 {n} 行：\n· {notes}',
        'csv.note.bad': '{n} 行解析失败被跳过',
        'csv.note.live': '{n} 行挂到当前显示',
        'csv.note.infile': '{n} 行在当前文件但未挂到显示（选中对应 trace / 匹配 Join 状态即亮）',
        'csv.note.other': '{n} 行来自其他数据（灰显，快照保留）',
        'csv.note.cand': '部分 trace 指纹有多条同名候选，按路径就近对齐（请核对）',
        'csv.note.content': '部分 trace 已按内容指纹对齐（原路径已漂移）',
        'grab.imp.otherfile': '来自其他数据（文件不匹配，快照保留）',
        'grab.imp.otherref': '来自其他数据（trace 指纹未匹配，快照保留）',
        'grab.imp.joinflip': '当前文件的 {label} —— 把 Join {sw}并选中该 trace 即亮',
        'grab.imp.select': '当前文件的 {label} —— 树里选中该 trace 即亮',
        'grab.w.on': '开', 'grab.w.off': '关',
        'grab.notlive': '<span style="color:#999">未挂到当前显示：{hint}</span>',
        'grab.stats.imp': '<b>#{r} · 导入行 · dwell {d} · level {l} · 噪声 ±{s}</b>',
        'grab.stats.row': '<b>#{r} · 组#{g} · dwell {d} · level {l} · 噪声 ±{s}</b>',
        'grab.w.grp': '组#{r}', 'grab.w.grp.short': '组#{r}',
        'grab.w.noise': '噪声 ±{v}',
        'grab.stats.bd': '边界丢弃 {n}', 'grab.stats.dd': '占比丢弃 {n}',
        'grab.w.nev': '{n} 个事件', 'grab.w.preview': '预览 {n} 个事件',
        'grab.overlimit': '<br><span style="color:{c}">超过上限 {cap}，松手会拒绝——收小矩形范围</span>',
        'grab.nofull': '<br><span style="color:#999">范围内没有完整事件</span>'
                       '（边界丢弃 {n}：事件被矩形边缘切断，把边缘拖离它即可收全；或检查 Y 带与参数）',
        'grab.grp.err': '<b>组#{r} · {a} – {b} s</b><br><span style="color:{c}">{e}</span>',
        'grab.grp.head': '<b>组#{r} · {a} – {b} s · {tag}{noise}</b>',
        'grab.allgrey': '<span style="color:#999">{n} 条记录均来自其他数据（树选择/文件已切换）'
                        '——事件与统计仍是快照；切回对应数据后矩形自动恢复、可继续编辑。</span>',
        'grab.norec': '<span style="color:#999">没有记录：按住 <b>Shift</b> '
                      '在主图内拖拽 XY 矩形，范围内每个检出事件一行。</span>',
        'grab.otherdata.rec': '<b>#{r} · 组#{g}</b> 来自其他数据（树选择/文件已切换）——'
                              'dwell/level 仍是抓取时的快照：<br>{stats}',
        'grab.otherdata.grp': '<b>组#{r}</b> 来自其他数据——切回对应数据后矩形自动恢复。',
        'grab.summary': 'N={n} · 均 dwell {dm} · level {lm} · 噪声 ±{sm}<br>'
                        '中位 dwell {dd} · level {ld} · 噪声 ±{sd}',
        'grab.tip.grp': '组 #{rank} 参数（快照于抓取/改边时刻，编辑=整组重抓）：\n'
                        '模式 {mode} · 滞回 k={k} · 最短 {tmin} ms · 合并 {merge} s\n'
                        '忽略开头 {head} ms · 检测平滑 {smooth} ms · 带内占比 ≥{duty}\n'
                        '矩形范围 {x0} – {x1} s · Y 带 {y0} – {y1}（原生单位）\n\n'
                        '噪声 ± = 该事件跨度内 90% 采样所在的波动带半宽（p5–p95 分位\n'
                        '包络，围绕事件电平，含 spike 穿刺与慢纹波；孤立单点毛刺\n'
                        '占比 <5% 会被折价），逐事件独立计算，单位 = 电流/电压原生单位。\n\n'
                        '整组替换：拖动矩形重新检测会用新结果替换该组全部行\n'
                        '（手动删过的行会回来）。手动删除某行只删那一个事件；\n'
                        '组内最后一行删掉时矩形一并移除。\n\n'
                        '边界丢弃 = 事件被矩形边缘切断（进入或离开发生在范围外），\n'
                        '完整落在范围内的事件才保留；想收全某个事件就把矩形边缘拖离它。',
        'del.rect.title': '删除矩形',
        'del.rect.confirm': '组#{r} 的矩形带 {n} 条事件行，矩形与行将一并删除。继续？',
    },
    'en': {
        'btn.load': 'Load...', 'btn.auto': 'Auto', 'btn.follow': 'Follow file',
        'btn.measure': 'Measure', 'btn.clear': 'Clear', 'btn.join': 'Join',
        'btn.tip.lang': 'Switch the UI language (zh/EN); takes effect after restart',
        'tip.follow': 'Watch the current .dat: re-parse automatically as Patchmaster\n'
                      'flushes new data, keeping your selection (≈ per-sweep latency;\n'
                      'needs Patchmaster per-sweep saving/auto-save).\n'
                      'F5 = manual refresh. Half-written reads are skipped silently\n'
                      'and retried on the next file change.',
        'lang.title': 'Language', 'lang.ask': 'Language switched; it takes effect after a restart. Restart now?',
        'sec.tree': 'File tree', 'sec.nano': 'Nanopore calculator', 'sec.info': 'File info',
        'sec.dist': 'Events', 'amp.title': 'Amplitude',
        'exp.title': 'Files', 'exp.csvonly': 'CSV only',
        'exp.tip.csvonly': 'On = show only *.csv files (directories always shown);\noff = show everything.',
        'exp.tip.up': 'Go to the parent directory',
        'exp.tip.refresh': 'Force a refresh of the current directory (the list watches\nthe filesystem live; fallback for synced folders).',
        'exp.tip.list': 'Double-click a CSV = open it as an analysis document (bootstraps '
                        'the source .dat, selects the referenced traces, restores Join);\n'
                        'double-click a directory = enter; other files do nothing.\n'
                        'Select an item and press Return / F2 = rename it.',
        'tree.node': 'Node', 'tree.label': 'Label', 'info.nofile': 'no file loaded',
        'dlg.open': 'Open data file', 'reload.title': 'Reload',
        'reload.fail': 'Parse failed: the file may be mid-write; try again shortly.',
        'nano.solution': 'Solution', 'nano.conc': 'Concentration (M)',
        'nano.thick': 'Membrane thickness (nm)', 'nano.volt': 'Voltage (mV)', 'nano.current': 'Current',
        'amp.clear': 'Clear regions', 'amp.ruler': 'Peak ruler',
        'amp.autobins': 'auto bins', 'amp.follow': 'range = view Y',
        'amp.tip.ruler': 'Two draggable horizontal markers A/B on the histogram;\n'
                         'reads both peak positions and their difference Δ live.',
        'amp.hint': 'Amplitude mode armed (this column was clicked last): '
                    '<b>Shift+drag horizontally</b> in the main plot to select '
                    'time regions (plain drag = pan, axis-band drag = zoom); '
                    'click the Event panel below to switch back to event grabs.',
        'amp.hint.off': 'Click anywhere in this column to arm amplitude mode: '
                        'then Shift+drag horizontally in the main plot to band '
                        'time regions; folding this column clears all regions.',
        'amp.tip.hint': 'Shift+drag horizontally in the main plot = select a time '
                        'region (plain drag = pan, axis-band drag = zoom);\n'
                        'on release every raw sample inside it joins the histogram '
                        '(regions stack, each with its own stats).\n'
                        'Drag a region edge to adjust; switching to the Event panel '
                        'or folding this column clears all regions.\n'
                        'The hint text clips in a narrow column -- full wording here.',
        'amp.nosamples': 'regions cover no samples',
        'amp.axisy': '% of region samples',
        'amp.over.commit': '<span style="color:{c}">{n} events exceed the cap {cap} -- '
                           'shrink the rectangle (the Event panel curates events one by one; '
                           'use the notebook + analysis.py for batch work)</span>',
        'amp.over.edit': '<span style="color:{c}">{n} events exceed the cap {cap} -- '
                         'edit refused, shrink the rectangle</span>',
        'grab.hint': 'Event mode armed (this panel was clicked last): <b>Shift+drag</b> '
                     'an XY rectangle (X = time scope, Y = event band); each detected '
                     'event becomes a row; drag edges/inside = re-grab',
        'grab.hint.off': 'Click anywhere in this panel to arm event mode: then '
                         '<b>Shift+drag</b> in the main plot draws an XY detection '
                         'rectangle (X = time scope, Y = event band).',
        'grab.tip.hint': 'Hold Shift and drag an XY rectangle in the main plot (X = analysis\n'
                         'time scope, Y = event band); release runs detection inside it: every\n'
                         'detected event becomes a row in the list (dwell = that event\'s duration).\n'
                         'Events from one rectangle form a group (same colour, shared param snapshot).\n\n'
                         'Dragging an edge (resize) or the inside (move) re-detects on release and\n'
                         'REPLACES the whole group with the current parameters; events cut by the\n'
                         'rectangle edge are dropped as boundary events (only fully-inside ones stay).\n'
                         'With 0 events the rectangle stays -- enlarge it until the event fits.\n\n'
                         'Parameters are snapshotted at grab/edit time and never back-applied;\n'
                         '[Recalc all] re-runs every still-matching record with the current ones.',
        'grab.p.mode': 'Mode', 'grab.p.k': 'Hysteresis k·σ', 'grab.p.tmin': 'Min (ms)',
        'grab.p.merge': 'Merge (s)', 'grab.p.head': 'Skip head (ms)',
        'grab.p.smooth': 'Smooth (ms)', 'grab.p.duty': 'In-band duty ≥',
        'evt.tip.mode': 'Event semantics -- all four modes share the hysteresis/duration logic:\n'
                        'inside = in-band is an event (default; no baseline assumed)\n'
                        'outside = out-of-band is an event (baseline mid-band, spikes both ways)\n'
                        'below = y < hi is an event (classic downward blockade, upper line only)\n'
                        'above = y > lo is an event (upward spikes)',
        'evt.tip.k': 'Hysteresis k·σ -- the debounce threshold for event END.\n'
                     'Noise makes the signal chatter across the band edge; a plain\n'
                     '"in = start / out = end" rule shatters one real event into many\n'
                     'fragments. Hysteresis demands a clear exit of k noise sigmas\n'
                     '(σ robustly estimated from neighbouring samples, immune to spikes).\n'
                     '3 suits most data; noisy or spike-dense traces may need 5-8; 0 = off',
        'evt.tip.tmin': 'Minimum duration -- shorter events are dropped outright.\n'
                        'Filters capacitive glitches and the ~0.1-0.3 ms fragments spikes\n'
                        'leave crossing the band edge; two-state dwells are usually >= ms,\n'
                        'so 0.1-1 ms is safe (raise to 10 for long dwells only).\n'
                        'Converted to samples at the raw rate; divided by the window if smoothing is on',
        'evt.tip.merge': 'Merge -- adjacent events closer than this are glued back together,\n'
                         'rejoining real dwells that a spike briefly interrupted.\n'
                         '⚠ Dangerous: the denser the spikes, the shorter the gaps -- too large a\n'
                         'value welds the whole trace into one giant "pseudo-event" (its level\n'
                         'diluted by out-of-band gaps). Keep 0 for dense spikes; use smoothing\n'
                         '+ the in-band duty guard instead',
        'evt.tip.head': 'Skip head -- this much time is cut from every sweep start, dodging\n'
                        'the capacitive transient (here up to ±2 nA; uncut it fakes an event\n'
                        'at every sweep start). 10 ms covers nearly everything; with Join on,\n'
                        'every sweep\'s head is cut',
        'evt.tip.smooth': 'Detection smoothing -- median-of-window decimation before detecting.\n'
                          'Spikes narrower than the window flatten, plateaus wider than it survive\n'
                          'intact -- the key parameter for spike-dense two-state data (1-2 ms\n'
                          'recommended). Without it every spike crossing shards the event; with it\n'
                          'dwell/boundary precision drops to the window grain (1 ms -> 1 ms). 0 = off',
        'evt.tip.duty': 'In-band duty -- the fraction of a MERGED event span actually spent\n'
                        'in band; below this the event is dropped: spike-top fragment chains\n'
                        'sit near ~3%, real dwells >50%, so 0.5 splits them cleanly.\n'
                        'Applies only to merged events; 0 = off',
        'grab.col.noise': 'noise',
        'grab.viewall': 'Show all',
        'grab.tip.viewall': 'Audit mode: keep the main-plot zoom and show EVERY detected event\n'
                            'of the selected group in green (selected one bold) -- quickly check\n'
                            'nothing unwanted slipped into the rectangle. Off = only the selected event.',
        'grab.recalc': 'Recalc all',
        'grab.tip.recalc': 'Re-grab every record still matching this data with the current\nparameters (whole-group replace: manually deleted rows come back)',
        'grab.clear': 'Clear',
        'csv.imp.title': 'Import event CSV', 'csv.exp.title': 'Export event CSV',
        'exp.rename.title': 'Rename',
        'exp.rename.exists': '"{name}" already exists.',
        'exp.rename.badname': 'The name must not be empty or contain "/".',
        'exp.rename.fail': 'Could not rename: {err}',
        'doc.new': 'New analysis file', 'doc.newbtn': 'New',
        'doc.empty.hint': 'Click the button above and Shift+drag an XY rectangle in the '
                          'main plot to start grabbing events,<br>or double-click a CSV '
                          'in the file column to open a saved analysis.',
        'doc.save': 'Save', 'doc.saveas': 'Save As…',
        'doc.untitled': 'untitled',
        'doc.close.title': 'Close document',
        'doc.close.q': '"{name}" has unsaved changes (event rows). Save & close, discard, or cancel?',
        'doc.savefail': 'Could not write the file: {err}',
        'doc.empty.save': 'There are no event rows -- the file would hold only the header. Continue?',
        'csv.readfail': 'Cannot read the file: {err}',
        'csv.v2': 'v2 grouped format (group_id column) -- exports are flat since v3 and no '
                  'longer store grouping; v2 is no longer supported.',
        'csv.missing': 'Missing required columns: {cols}\nUse a grab CSV exported by this '
                       'version (v4 flat table; v3 auto-maps; v2 and older grouped formats '
                       'are no longer supported).',
        'csv.empty': 'The file has no data rows.',
        'csv.nousable': 'No usable records{bad}.',
        'csv.badrows': ' ({n} rows failed to parse)',
        'csv.confirm': 'There are already {n} records; importing replaces them (unexported '
                       'curation is lost). Continue?',
        'csv.locate': 'Locate the source data file{suffix}',
        'csv.openfail': 'Cannot open the source file; those rows import grey: {err}',
        'csv.report': 'Imported {n} rows:\n· {notes}',
        'csv.note.bad': '{n} rows skipped (parse failed)',
        'csv.note.live': '{n} rows attached to the current display',
        'csv.note.infile': '{n} rows in the current file but not on the display (select their '
                           'trace / match the Join state to light them up)',
        'csv.note.other': '{n} rows from other data (grey snapshots kept)',
        'csv.note.cand': 'Some trace fingerprints have several same-name candidates; aligned '
                         'by path proximity (please verify)',
        'csv.note.content': 'Some traces aligned by content fingerprint (the original path drifted)',
        'grab.imp.otherfile': 'from other data (file mismatch; snapshot kept)',
        'grab.imp.otherref': 'from other data (trace fingerprint unmatched; snapshot kept)',
        'grab.imp.joinflip': '{label} of the current file -- turn Join {sw} and select that '
                             'trace to light it up',
        'grab.imp.select': '{label} of the current file -- select that trace in the tree to '
                           'light it up',
        'grab.w.on': 'on', 'grab.w.off': 'off',
        'grab.notlive': '<span style="color:#999">Not on the current display: {hint}</span>',
        'grab.stats.imp': '<b>#{r} · imported · dwell {d} · level {l} · noise ±{s}</b>',
        'grab.stats.row': '<b>#{r} · grp#{g} · dwell {d} · level {l} · noise ±{s}</b>',
        'grab.w.grp': 'grp#{r}', 'grab.w.grp.short': 'grp#{r}',
        'grab.w.noise': 'noise ±{v}',
        'grab.stats.bd': 'boundary-cut {n}', 'grab.stats.dd': 'duty-cut {n}',
        'grab.w.nev': '{n} events', 'grab.w.preview': 'preview of {n} events',
        'grab.overlimit': '<br><span style="color:{c}">over the cap {cap}, release will refuse '
                          '-- shrink the rectangle</span>',
        'grab.nofull': '<br><span style="color:#999">no complete event in range</span>'
                       '(boundary-cut {n}: the event crosses the rectangle edge; drag the edge '
                       'off it to collect it whole; or check the Y band and parameters)',
        'grab.grp.err': '<b>grp#{r} · {a} – {b} s</b><br><span style="color:{c}">{e}</span>',
        'grab.grp.head': '<b>grp#{r} · {a} – {b} s · {tag}{noise}</b>',
        'grab.allgrey': '<span style="color:#999">all {n} records are from other data (tree/file '
                        'switched) -- events and stats stay snapshots; rectangles re-attach '
                        'automatically once the data is back.</span>',
        'grab.norec': '<span style="color:#999">No records yet: <b>Shift+drag</b> an XY '
                      'rectangle in the main plot; every detected event inside becomes a row.</span>',
        'grab.otherdata.rec': '<b>#{r} · grp#{g}</b> from other data (tree/file switched) -- '
                              'dwell/level keep their grab-time snapshot:<br>{stats}',
        'grab.otherdata.grp': '<b>grp#{r}</b> from other data -- rectangles re-attach once the '
                              'matching data is back.',
        'grab.summary': 'N={n} · mean dwell {dm} · level {lm} · noise ±{sm}<br>'
                        'median dwell {dd} · level {ld} · noise ±{sd}',
        'grab.tip.grp': 'Group #{rank} parameters (snapshotted at grab/edit time; editing = '
                        'whole-group re-grab):\n'
                        'mode {mode} · hysteresis k={k} · min {tmin} ms · merge {merge} s\n'
                        'skip head {head} ms · smoothing {smooth} ms · in-band duty ≥{duty}\n'
                        'rectangle {x0} – {x1} s · Y band {y0} – {y1} (native unit)\n\n'
                        'noise ± = half-width of the band holding 90% of the samples inside the '
                        'event span (p5–p95 quantile envelope around the event level, spike '
                        'piercings and slow ripple included; lone one-sample glitches below a 5% '
                        'share are discounted), computed per event, in the native current/voltage '
                        'unit.\n\n'
                        'Whole-group replace: re-detecting via the rectangle replaces ALL rows of '
                        'the group (manually deleted rows come back). Deleting one row removes '
                        'only that event; deleting the last row of a group removes the rectangle '
                        'too.\n\n'
                        'Boundary-cut = the event crosses the rectangle edge (entry or exit lies '
                        'outside the range); only fully-inside events are kept -- drag the edge '
                        'off an event to collect it whole.',
        'del.rect.title': 'Delete rectangle',
        'del.rect.confirm': 'The rectangle of grp#{r} carries {n} event rows; rectangle and '
                            'rows are deleted together. Continue?',
    },
}


def T(key, **fmt):
    s = L10N.get(_ui_lang, L10N['zh']).get(key) or L10N['zh'].get(key, key)
    return s.format(**fmt) if fmt else s
