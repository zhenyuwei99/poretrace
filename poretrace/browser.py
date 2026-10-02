import os, sys, time, csv, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyqtgraph as pg
import numpy as np
from poretrace import reader as heka_reader
from poretrace import analysis
from poretrace.nanopore import calculate_pore_diameter, get_conductivity
from poretrace.i18n import T, L10N, THEME, _ui_lang  # flat re-export: smoke tests reach these as module globals


def trace_pen(i, total):
    """Pen for trace i of total: Tableau 10/20 cycles when few; beyond that
    a golden-ratio hue walk with muted saturation (S .55 V .78) so hundreds
    of traces stay distinguishable without neon glare. Deterministic per i."""
    if total <= len(THEME['cycle']):
        return pg.mkPen(THEME['cycle'][i % len(THEME['cycle'])], width=1)
    if total <= len(THEME['cycle20']):
        return pg.mkPen(THEME['cycle20'][i % len(THEME['cycle20'])], width=1)
    hue = (i * 0.61803398875) % 1.0
    return pg.mkPen(pg.QtGui.QColor.fromHsvF(hue, 0.55, 0.78), width=1)


pg.setConfigOption('background', THEME['bg'])
pg.setConfigOption('foreground', THEME['fg'])

app = pg.mkQApp()

# Force a light UI regardless of the OS dark mode: the Fusion style ignores
# the system appearance and follows the palette below, so the tree, buttons
# and metadata pane stay light and match the plot, identically on all OSes.
app.setStyle('Fusion')
_pal = pg.QtGui.QPalette()
_fg = pg.QtGui.QColor(THEME['fg'])
_acc = pg.QtGui.QColor('#4E79A7')                      # Tableau blue accent
_pal.setColor(pg.QtGui.QPalette.Window, pg.QtGui.QColor(THEME['bg']))
_pal.setColor(pg.QtGui.QPalette.WindowText, _fg)
_pal.setColor(pg.QtGui.QPalette.Base, pg.QtGui.QColor('#FFFFFF'))
_pal.setColor(pg.QtGui.QPalette.AlternateBase, pg.QtGui.QColor('#F5F5F5'))
_pal.setColor(pg.QtGui.QPalette.Text, _fg)
_pal.setColor(pg.QtGui.QPalette.Button, pg.QtGui.QColor('#F2F2F2'))
_pal.setColor(pg.QtGui.QPalette.ButtonText, _fg)
_pal.setColor(pg.QtGui.QPalette.Highlight, _acc)
_pal.setColor(pg.QtGui.QPalette.HighlightedText, pg.QtGui.QColor('#FFFFFF'))
_pal.setColor(pg.QtGui.QPalette.ToolTipBase, pg.QtGui.QColor('#FFFFDC'))
_pal.setColor(pg.QtGui.QPalette.ToolTipText, _fg)
_pal.setColor(pg.QtGui.QPalette.PlaceholderText, pg.QtGui.QColor('#999999'))
_pal.setColor(pg.QtGui.QPalette.Link, _acc)
for _role in (pg.QtGui.QPalette.WindowText, pg.QtGui.QPalette.Text,
              pg.QtGui.QPalette.ButtonText):
    _pal.setColor(pg.QtGui.QPalette.Disabled, _role, pg.QtGui.QColor('#AAAAAA'))
app.setPalette(_pal)

# Persistent settings (remembers the last opened directory across sessions)
settings = pg.QtCore.QSettings('heka', 'browser')


def _splitter_assign(widget, want):
    """Give `widget` `want` px in its parent splitter, handing the
    difference to the widest sibling so the sizes still sum to the
    splitter's width: a lopsided request makes QSplitter redistribute
    the surplus per size hints, which is how panes spring back open."""
    sp = widget.parentWidget()
    if not isinstance(sp, pg.QtWidgets.QSplitter):
        return
    idx = sp.indexOf(widget)
    sizes = sp.sizes()
    delta = int(want) - sizes[idx]
    if not delta:
        return
    sizes[idx] += delta
    k = max((j for j in range(len(sizes)) if j != idx),
            key=lambda j: sizes[j], default=None)
    if k is not None:
        sizes[k] -= delta
    sp.setSizes([int(s) for s in sizes])


# Configure Qt GUI:

# Collapsible titled section: a one-line header with a fold arrow; folding
# hides the body so the section shrinks to just the header in the splitter.
class Collapsible(pg.QtWidgets.QWidget):
    def __init__(self, title):
        super().__init__()
        self._title = title
        self._collapsed = False
        lay = pg.QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.btn = pg.QtWidgets.QToolButton()
        self.btn.setText('\u25be ' + title)
        self.btn.setToolButtonStyle(pg.QtCore.Qt.ToolButtonTextOnly)
        self.btn.setStyleSheet('QToolButton { border: none; text-align: left;'
                               ' padding: 2px; font-weight: bold; }')
        self.btn.clicked.connect(self._toggle)
        lay.addWidget(self.btn)
        self.body = pg.QtWidgets.QWidget()
        self.body_lay = pg.QtWidgets.QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.body, 1)

    def _toggle(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.body.setVisible(not collapsed)
        self.btn.setText(('\u25be ' if not collapsed else '\u25b8 ') + self._title)
        # Constrain the section to its header height when folded -- QSplitter
        # then hands the freed space to the sibling sections automatically.
        sp = self.parentWidget()
        if collapsed:
            self._restore = sp.sizes()[sp.indexOf(self)] if isinstance(sp, pg.QtWidgets.QSplitter) else 0
            self.setMaximumHeight(self.btn.sizeHint().height() + 4)
        else:
            self.setMaximumHeight(16777215)
        strip = self.btn.sizeHint().height() + 4   # keep header clickable
        _splitter_assign(self, strip if collapsed
                         else (getattr(self, '_restore', 0) or 150))

    def is_collapsed(self):
        return self._collapsed

    def add_widget(self, w):
        self.body_lay.addWidget(w)


class CollapsibleColumn(pg.QtWidgets.QWidget):
    """Sideways sibling of Collapsible: a column in a HORIZONTAL splitter
    that folds to a slim strip (just the fold button). Same trick as
    Collapsible with width instead of height -- merely hiding the body
    shrinks nothing because QSplitter keeps the space reserved."""
    def __init__(self, title):
        super().__init__()
        self._title = title
        self._collapsed = False
        lay = pg.QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.btn = pg.QtWidgets.QToolButton()
        self.btn.setText('\u00bb ' + title)
        self.btn.setToolButtonStyle(pg.QtCore.Qt.ToolButtonTextOnly)
        self.btn.setStyleSheet('QToolButton { border: none; text-align: left;'
                               ' padding: 2px; font-weight: bold; }')
        self.btn.clicked.connect(self._toggle)
        lay.addWidget(self.btn)
        self.body = pg.QtWidgets.QWidget()
        self.body_lay = pg.QtWidgets.QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.body, 1)

    def _toggle(self):
        self.set_collapsed(not self._collapsed)

    def strip_width(self):
        """Folded-strip width (the fold button's cross-axis hint)."""
        return self.btn.sizeHint().height() + 4

    def _splitter_assign(self, want):
        """Delegate: kept as a method -- _restore_layout and the fold
        bookkeeping call amp_col._splitter_assign(...)."""
        _splitter_assign(self, want)

    def set_collapsed(self, collapsed):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.body.setVisible(not collapsed)
        sp = self.parentWidget()
        if collapsed:
            self._restore = (sp.sizes()[sp.indexOf(self)]
                             if isinstance(sp, pg.QtWidgets.QSplitter) else 0)
            self.setMaximumWidth(self.strip_width())
            self.btn.setText('\u00ab')
        else:
            self.setMaximumWidth(16777215)
            self.btn.setText('\u00bb ' + self._title)
        want = self.strip_width() if collapsed \
            else (getattr(self, '_restore', 0) or 200)
        self._splitter_assign(want)

    def is_collapsed(self):
        return self._collapsed


# Main window + splitters to let user resize panes
win = pg.QtWidgets.QWidget()
layout = pg.QtWidgets.QGridLayout()
win.setLayout(layout)
hsplit = pg.QtWidgets.QSplitter(pg.QtCore.Qt.Horizontal)
layout.addWidget(hsplit, 0, 0)

# Left column: fixed button row on top, then a vertical splitter of three
# collapsible sections (file tree / nanopore calculator / file info)
left_col = pg.QtWidgets.QWidget()
left_lay = pg.QtWidgets.QGridLayout()
left_lay.setContentsMargins(0, 0, 0, 0)
left_col.setLayout(left_lay)
# Cap the left pane so wide screens give most of the space to the traces
left_col.setMaximumWidth(480)
hsplit.addWidget(left_col)

vsplit = pg.QtWidgets.QSplitter(pg.QtCore.Qt.Vertical)
left_lay.addWidget(vsplit, 1, 0)

# Fixed-height button rows (not part of the vertical splitter)
btn_row = pg.QtWidgets.QWidget()
btn_row_lay = pg.QtWidgets.QGridLayout()
btn_row_lay.setContentsMargins(0, 0, 0, 0)
btn_row.setLayout(btn_row_lay)
left_lay.addWidget(btn_row, 0, 0)

# Button for loading .dat file
load_btn = pg.QtWidgets.QPushButton(T('btn.load'))
btn_row_lay.addWidget(load_btn, 0, 0)

# Button to auto-fit X/Y axes to the displayed data
auto_btn = pg.QtWidgets.QPushButton(T('btn.auto'))
btn_row_lay.addWidget(auto_btn, 0, 1)

# Checkable follow mode: watch the loaded .dat on disk and re-parse it
# whenever Patchmaster appends data (near-live feedback per sweep); F5 is
# the manual counterpart. Not persisted -- always off at launch.
follow_btn = pg.QtWidgets.QPushButton(T('btn.follow'))
follow_btn.setCheckable(True)
follow_btn.setToolTip(T('tip.follow'))
btn_row_lay.addWidget(follow_btn, 0, 2)

# Checkable button toggling click-to-measure mode on the plot
measure_btn = pg.QtWidgets.QPushButton(T('btn.measure'))
measure_btn.setCheckable(True)
btn_row_lay.addWidget(measure_btn, 1, 0)

# Button clearing all measurement markers
clear_btn = pg.QtWidgets.QPushButton(T('btn.clear'))
btn_row_lay.addWidget(clear_btn, 1, 1)

# Checkable button toggling end-to-end joining of multi-selected traces
join_btn = pg.QtWidgets.QPushButton(T('btn.join'))
join_btn.setCheckable(True)
# settings key was 'stitch' before the Join rename -- read-migrate
_join_saved = settings.value('join', None)
if _join_saved is None:
    _join_saved = settings.value('stitch', False, type=bool)
join_btn.setChecked(bool(_join_saved))
btn_row_lay.addWidget(join_btn, 1, 2, 1, 2)

# Language switch: writes ui/lang and offers a restart (the whole UI is
# built at module level, so the new language lands on the next launch)
lang_btn = pg.QtWidgets.QPushButton('EN' if _ui_lang == 'zh' else '中文')
lang_btn.setToolTip(T('btn.tip.lang'))
btn_row_lay.addWidget(lang_btn, 0, 3)


def _lang_clicked():
    settings.setValue('ui/lang', 'en' if _ui_lang == 'zh' else 'zh')
    ans = pg.QtWidgets.QMessageBox.question(
        win, T('lang.title'), T('lang.ask'),
        pg.QtWidgets.QMessageBox.Yes | pg.QtWidgets.QMessageBox.No,
        pg.QtWidgets.QMessageBox.Yes)
    if ans == pg.QtWidgets.QMessageBox.Yes:
        if getattr(sys, 'frozen', False):
            _args = [sys.executable]
        else:
            _args = [sys.executable, os.path.abspath(__file__)]
        pg.QtCore.QProcess.startDetached(sys.executable, _args)
        win.close()


lang_btn.clicked.connect(lambda *_: _lang_clicked())

# Amplitude-region and event-detection controls live inside the Distribution
# panel tabs below the plot (see the distribution section), not up here.

# Collapsible section: file tree
sec_tree = Collapsible(T('sec.tree'))
tree = pg.QtWidgets.QTreeWidget()
tree.setHeaderLabels([T('tree.node'), T('tree.label')])
tree.setColumnWidth(0, 200)
tree.setSelectionMode(pg.QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
sec_tree.add_widget(tree)
vsplit.addWidget(sec_tree)

# Read-only path bar showing the full path of the loaded file.
# Text is selectable so the absolute path can be copied (Cmd+C / Cmd+A).
path_label = pg.QtWidgets.QLineEdit(T('info.nofile'))
path_label.setReadOnly(True)
path_label.setStyleSheet('QLineEdit { border: none; background: transparent; color: gray; }')

# Tree for displaying metadata for selected node
data_tree = pg.DataTreeWidget()

# Plot for displaying trace data (the measure readout floats inside the
# view as a TextItem -- see the measure section below)
plot = pg.PlotWidget()
plot.setDownsampling(auto=True, mode='peak')
plot.setClipToView(True)
legend = plot.addLegend(brush=pg.mkBrush(255, 255, 255, 200),
                        pen=pg.mkPen('#CCCCCC'),
                        labelTextColor=THEME['fg'])

# Right column: main plot + collapsible Amplitude column side by side on
# top, collapsible Event panel below (see the analysis sections further
# down); the splitters keep a fixed panel height while the traces take
# the rest. top_split is horizontal: [main plot | amp column].
right_split = pg.QtWidgets.QSplitter(pg.QtCore.Qt.Vertical)
top_split = pg.QtWidgets.QSplitter(pg.QtCore.Qt.Horizontal)
top_split.addWidget(plot)
right_split.addWidget(top_split)
right_col = pg.QtWidgets.QWidget()
right_lay = pg.QtWidgets.QGridLayout()
right_lay.setContentsMargins(0, 0, 0, 0)
right_col.setLayout(right_lay)
right_lay.addWidget(right_split, 0, 0)
hsplit.addWidget(right_col)

# Resize and show window
hsplit.setStretchFactor(0, 400)
hsplit.setStretchFactor(1, 600)
win.resize(1200, 800)
win.show()


def load_clicked():
    # Start in the directory of the last opened file
    start_dir = settings.value('last_dir', '')
    file_name, _ = pg.QtWidgets.QFileDialog.getOpenFileName(
        None, T('dlg.open'), start_dir, 'Heka bundle (*.dat)')
    if file_name == '':
        return
    load(file_name)
    
load_btn.clicked.connect(load_clicked)


def fit_view():
    """Fit X to the full data range and Y to the 1-99 percentile of the data.

    The percentile Y range keeps the initial capacitor-charging transient of
    a sweep from flattening the displayed current while nanopore events stay
    in view. Ranges are computed on the original (not downsampled) data.
    """
    pi = plot.getPlotItem()
    curves = [it for it in pi.listDataItems()
              if getattr(it, 'xData', None) is not None and it.yData is not None]
    if not curves:
        return
    x_lo = x_hi = y_lo = y_hi = None
    for it in curves:
        x = np.asarray(it.xData, dtype=float)
        x = x[np.isfinite(x)]
        if x.size == 0:
            continue
        x0, x1 = float(x.min()), float(x.max())
        x_lo = x0 if x_lo is None else min(x_lo, x0)
        x_hi = x1 if x_hi is None else max(x_hi, x1)
        y = np.asarray(it.yData, dtype=float)
        y = y[np.isfinite(y)]
        if y.size == 0:
            continue
        p1, p99 = np.percentile(y, [1, 99])
        y_lo = p1 if y_lo is None else min(y_lo, p1)
        y_hi = p99 if y_hi is None else max(y_hi, p99)
    if x_lo is None or y_lo is None:
        return
    x_span = x_hi - x_lo
    y_span = y_hi - y_lo
    if y_span <= 1e-30:
        y_span = max(abs(y_hi) * 0.1, 1e-15)
    if x_span <= 0:
        x_span = abs(x_hi) * 0.01 or 1.0
    pi.getViewBox().setRange(
        xRange=(x_lo - 0.02 * x_span, x_hi + 0.02 * x_span),
        yRange=(y_lo - 0.05 * y_span, y_hi + 0.05 * y_span),
        padding=0)


def auto_clicked():
    """Fit the view (X full range, Y percentile) and reset the zoom history."""
    zoom_history.clear()
    fit_view()

auto_btn.clicked.connect(auto_clicked)


# --- Measure mode: live crosshair + two-point (A/B) delta readout -------------

v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(THEME['crosshair'], width=1, style=pg.QtCore.Qt.DashLine))
h_line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(THEME['crosshair'], width=1, style=pg.QtCore.Qt.DashLine))

# Floating readout (cursor / A / B / delta) anchored to the top-left of the
# view: no layout impact on the traces and never clipped
readout_item = pg.TextItem('', color=THEME['readout'], anchor=(0, 0),
                           fill=pg.mkBrush(*THEME['readout_bg']))
readout_item.setZValue(100)
readout_item.hide()
plot.getPlotItem().addItem(readout_item, ignoreBounds=True)


def add_readout():
    """Re-attach the floating readout after plot.clear() and pin it to the
    top-left corner of the current view."""
    pi = plot.getPlotItem()
    if readout_item.scene() is None:
        pi.addItem(readout_item, ignoreBounds=True)
    place_readout()


def place_readout():
    (x0, x1), (y0, y1) = plot.getPlotItem().getViewBox().viewRange()
    readout_item.setPos(x0 + 0.01 * (x1 - x0), y1)


plot.getPlotItem().getViewBox().sigRangeChanged.connect(lambda *a: place_readout())

meas_points = []
meas_items = []
join_segments = []
cur_xunit = 's'
cur_yunit = 'A'
last_mouse = None
last_snap = None
last_cursor_text = ''
bundle = None


def add_crosshair():
    """Re-attach crosshair lines to the plot (plot.clear() detaches them)."""
    pi = plot.getPlotItem()
    for ln in (v_line, h_line):
        pi.addItem(ln, ignoreBounds=True)
        ln.setVisible(measure_btn.isChecked())


def fmt_si(value, unit):
    if unit == '' or value is None or not np.isfinite(value):
        return '-'
    return pg.siFormat(float(value), precision=6, suffix=unit)


def format_point(px, py, name=''):
    txt = 'x=%s, y=%s' % (fmt_si(px, cur_xunit), fmt_si(py, cur_yunit))
    if name:
        txt = '[%s] %s' % (name, txt)
    return txt


def segment_at(x):
    """Text of the joined segment containing x ('' outside join mode)."""
    for x0, x1, text in join_segments:
        if x0 <= x < x1:
            return text
    return ''


def nearest_on_curves(pos, prefer=None):
    """Find the displayed data point closest to pos (view coords).

    prefer: a PlotDataItem to restrict the search to one curve (used for the
    B point so the A/B slope is computed on the same trace).
    Otherwise only curves whose x-range covers pos.x (2% margin) are
    considered and the one nearest in |dy| wins (|dx| as weak tie-breaker),
    so the picked trace does not jump around when zooming.
    Returns (score, px, py, item) or None.
    """
    pi = plot.getPlotItem()
    (x0, x1), (y0, y1) = pi.getViewBox().viewRange()
    dx = (x1 - x0) or 1.0
    dy = (y1 - y0) or 1.0
    items = pi.listDataItems()
    if prefer is not None:
        items = [prefer]
    best = None
    for item in items:
        x = getattr(item, 'xData', None)
        y = getattr(item, 'yData', None)
        if x is None or y is None or len(x) == 0 or len(x) != len(y):
            continue
        if prefer is None and not (float(x[0]) - 0.02 * dx <= pos.x() <= float(x[-1]) + 0.02 * dx):
            continue
        i = int(np.clip(np.searchsorted(x, pos.x()), 0, len(x) - 1))
        if i > 0 and abs(x[i - 1] - pos.x()) < abs(x[i] - pos.x()):
            i -= 1
        px, py = float(x[i]), float(y[i])
        if np.isfinite(px) and np.isfinite(py):
            score = abs(py - pos.y()) / dy + 0.1 * abs(px - pos.x()) / dx
        else:
            score = float('inf')
        if best is None or score < best[0]:
            best = (score, px, py, item)
    return best


def add_marker(px, py, label):
    pi = plot.getPlotItem()
    color = THEME['A'] if label == 'A' else THEME['B']
    spot = pg.ScatterPlotItem(x=[px], y=[py], size=10, symbol='o',
                              pen=pg.mkPen(color, width=2))
    pi.addItem(spot, ignoreBounds=True)
    txt = pg.TextItem('%s: y=%s' % (label, fmt_si(py, cur_yunit)),
                      color=color, anchor=(0, 1))
    txt.setPos(px, py)
    pi.addItem(txt, ignoreBounds=True)
    meas_items.extend([spot, txt])


# Free drag measurement state (Measure mode: left-drag in the plot)
drag_items = []
drag_txt = ''


def update_readout(cursor_text=None):
    """Floating readout inside the plot: cursor line, A line, B line, delta
    line, free-drag line."""
    if not measure_btn.isChecked():
        readout_item.hide()
        return
    readout_item.show()
    if cursor_text is None:
        cursor_text = last_cursor_text
    lines = []
    if cursor_text:
        lines.append(cursor_text)
    if meas_points:
        t1, y1, n1, _ = meas_points[0]
        lines.append('A: ' + format_point(t1, y1, n1))
    if len(meas_points) >= 2:
        t2, y2, n2, _ = meas_points[1]
        lines.append('B: ' + format_point(t2, y2, n2))
        dt = t2 - t1
        dy = y2 - y1
        slope_str = fmt_si(dy / dt, cur_yunit + '/s') if dt != 0 else 'inf'
        lines.append('dt=%s  dy=%s  dy/dt=%s'
                     % (fmt_si(dt, cur_xunit), fmt_si(dy, cur_yunit), slope_str))
    if drag_txt:
        lines.append(drag_txt)
    readout_item.setHtml('<br>'.join(lines))


def clear_meas():
    global meas_points
    pi = plot.getPlotItem()
    for it in meas_items:
        if it.scene() is not None:
            pi.removeItem(it)
    meas_items.clear()
    meas_points = []
    drag_measure_hide()
    update_readout()


def measure_toggled(checked):
    v_line.setVisible(checked)
    h_line.setVisible(checked)
    # no exclusivity needed any more: Measure owns plain drag, the
    # analysis tabs own Shift+drag -- they can be on at the same time
    if not checked:
        drag_measure_hide()
    update_readout()
    if checked and last_mouse is not None:
        mouse_moved([last_mouse])


def plot_clicked(ev):
    if not measure_btn.isChecked():
        return
    if ev.button() != pg.QtCore.Qt.LeftButton or ev.double():
        return
    if not vb.sceneBoundingRect().contains(ev.scenePos()):
        return
    if len(meas_points) >= 2:
        clear_meas()
    if len(meas_points) == 1 and last_mouse is not None:
        best = nearest_on_curves(vb.mapSceneToView(last_mouse), prefer=meas_points[0][3])
        if best is None:
            return
        px, py, item = best[1], best[2], best[3]
    elif last_snap is not None:
        px, py, item = last_snap[0], last_snap[1], last_snap[3]
    else:
        best = nearest_on_curves(vb.mapSceneToView(ev.scenePos()))
        if best is None:
            return
        px, py, item = best[1], best[2], best[3]
    name = segment_at(px) or (item.name() or '')
    meas_points.append((px, py, name, item))
    add_marker(px, py, 'A' if len(meas_points) == 1 else 'B')
    autofill_measurement(py)
    update_readout()


def mouse_moved(evt):
    global last_mouse, last_snap, last_cursor_text
    pos = evt[0]
    last_mouse = pg.QtCore.QPointF(pos)
    if not measure_btn.isChecked():
        return
    if not vb.sceneBoundingRect().contains(pos):
        return
    vpos = vb.mapSceneToView(pos)
    v_line.setPos(vpos.x())
    h_line.setPos(vpos.y())
    best = nearest_on_curves(vpos)
    last_snap = None
    name = ''
    if best is not None:
        last_snap = (best[1], best[2], best[3].name() or '', best[3])
        name = segment_at(vpos.x()) or (best[3].name() or '')
    txt = 'cursor: ' + format_point(vpos.x(), vpos.y(), name)
    last_cursor_text = txt
    update_readout(txt)


# --- Free drag measurement: left-drag inside the plot while Measure is on
#     measures the raw dx / dy between two arbitrary (unsnapped) points -------

def drag_measure_hide():
    global drag_items, drag_txt
    pi = plot.getPlotItem()
    for it in drag_items:
        if it.scene() is not None:
            pi.removeItem(it)
    drag_items = []
    drag_txt = ''


def drag_measure_show(p0, p1):
    """Show (or update) the dashed line + end dots + label for the free
    two-point delta, and stage its readout line."""
    global drag_items, drag_txt
    pi = plot.getPlotItem()
    if not drag_items:
        line = pg.PlotDataItem(pen=pg.mkPen(THEME['crosshair'], width=1, style=pg.QtCore.Qt.DashLine))
        dots = pg.ScatterPlotItem(size=9, pen=pg.mkPen(THEME['crosshair'], width=1))
        label = pg.TextItem('', color=THEME['crosshair'], anchor=(0.5, 1))
        for it in (line, dots, label):
            pi.addItem(it, ignoreBounds=True)
        drag_items = [line, dots, label]
    line, dots, label = drag_items
    line.setData([p0.x(), p1.x()], [p0.y(), p1.y()])
    dots.setData(x=[p0.x(), p1.x()], y=[p0.y(), p1.y()])
    dx = p1.x() - p0.x()
    dy = p1.y() - p0.y()
    slope = fmt_si(dy / dx, cur_yunit + '/' + cur_xunit) if dx != 0 else 'inf'
    drag_txt = 'drag: dx=%s  dy=%s  dy/dx=%s' % (fmt_si(dx, cur_xunit),
                                                 fmt_si(dy, cur_yunit), slope)
    label.setText(drag_txt)
    label.setPos((p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2)


measure_btn.toggled.connect(measure_toggled)
clear_btn.clicked.connect(clear_meas)
plot.scene().sigMouseClicked.connect(plot_clicked)
_mouse_proxy = pg.SignalProxy(plot.scene().sigMouseMoved, rateLimit=60, slot=mouse_moved)  # keep a ref: SignalProxy must stay alive


# --- Nanopore size calculator dialog ------------------------------------------

class NumericEdit(pg.QtWidgets.QLineEdit):
    """Numeric input for the calculator.

    - select-all on focus, so typing simply replaces the previous value
    - full-width '。' / '，' / '．' (from Chinese IMEs) normalized to '.'
    - parsed value clamped to [minimum, maximum]; change_cb gets the clamped
      float whenever it changes
    - invalid text keeps the last valid value; editingFinished rewrites the
      field to the valid formatted value
    - commit_on: 'edit' fires change_cb on every keystroke; 'finish' fires
      it only on Enter / focus loss -- parameter fields use 'finish' so
      typing (and programmatic setText from live updates) never triggers a
      recomputation mid-input
    """

    def __init__(self, value, minimum, maximum, change_cb=None,
                 commit_on='edit'):
        super().__init__(self._fmt(value))
        self._min = float(minimum)
        self._max = float(maximum)
        self._cb = change_cb
        self._commit_on = commit_on
        self._valid = float(value)
        self._committed = float(value)
        self._normalizing = False
        self.textChanged.connect(self._on_text_changed)
        self.editingFinished.connect(self._on_editing_finished)

    @staticmethod
    def _fmt(v):
        return '%.6g' % v

    @staticmethod
    def _norm(text):
        return text.replace('，', '.').replace('。', '.').replace('．', '.')

    def value(self):
        return self._valid

    def set_value_quiet(self, v):
        """Programmatic update: refresh the text without firing change_cb."""
        self._valid = float(v)
        self._committed = self._valid
        self.setText(self._fmt(self._valid))

    def commit(self):
        """Force the editingFinished path (tests / programmatic commit)."""
        self._on_editing_finished()

    def _parse(self):
        text = self._norm(self.text())
        try:
            return float(text)
        except ValueError:
            return None

    def _on_text_changed(self, text):
        normalized = self._norm(text)
        if normalized != text:
            self._normalizing = True
            self.setText(normalized)
            self._normalizing = False
            text = normalized
        try:
            v = float(text)
        except ValueError:
            return
        v = min(max(v, self._min), self._max)
        if v != self._valid:
            self._valid = v
            if self._commit_on == 'edit' and self._cb is not None:
                self._committed = v
                self._cb(v)

    def _on_editing_finished(self):
        v = self._parse()
        if v is not None:
            self._valid = min(max(v, self._min), self._max)
        self.setText(self._fmt(self._valid))
        if (self._commit_on == 'finish' and self._cb is not None
                and self._valid != self._committed):
            self._committed = self._valid
            self._cb(self._valid)

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        self.selectAll()
        # deferred again: Qt clears the selection right after focus-in
        pg.QtCore.QTimer.singleShot(0, self.selectAll)


class NanoporePanel(pg.QtWidgets.QWidget):
    """Nanopore size calculator form, docked in the left pane below the tree
    (inside a collapsible section). Measured points are auto-filled into
    Voltage / Current (see autofill_measurement)."""

    def __init__(self):
        super().__init__()
        form = pg.QtWidgets.QFormLayout(self)

        self.salt = pg.QtWidgets.QComboBox()
        self.salt.addItems(['KCl', 'NaCl', 'LiCl'])
        form.addRow(T('nano.solution'), self.salt)

        self.conc = NumericEdit(1.0, 0.001, 5.0, change_cb=self.refresh)
        form.addRow(T('nano.conc'), self.conc)

        self.thick = NumericEdit(20.0, 1.0, 100.0, change_cb=self.refresh)
        form.addRow(T('nano.thick'), self.thick)

        self.volt = NumericEdit(100.0, 0.001, 10000.0, change_cb=self.refresh)
        form.addRow(T('nano.volt'), self.volt)

        curr_row = pg.QtWidgets.QWidget()
        curr_lay = pg.QtWidgets.QHBoxLayout(curr_row)
        curr_lay.setContentsMargins(0, 0, 0, 0)
        self.curr = NumericEdit(1.0, 0.0001, 1e6, change_cb=self.refresh)
        self.unit = pg.QtWidgets.QComboBox()
        self.unit.addItems(['nA', 'pA'])
        curr_lay.addWidget(self.curr)
        curr_lay.addWidget(self.unit)
        form.addRow(T('nano.current'), curr_row)

        self.sigma_out = pg.QtWidgets.QLineEdit()
        self.sigma_out.setReadOnly(True)
        form.addRow(pg.QtWidgets.QLabel('<b>sigma (S/m)</b>'), self.sigma_out)

        self.g_out = pg.QtWidgets.QLineEdit()
        self.g_out.setReadOnly(True)
        form.addRow(pg.QtWidgets.QLabel('<b>G (nS)</b>'), self.g_out)

        self.d_out = pg.QtWidgets.QLineEdit()
        self.d_out.setReadOnly(True)
        form.addRow(pg.QtWidgets.QLabel('<b>d (nm)</b>'), self.d_out)

        for w in (self.salt, self.unit):
            w.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *args):
        sigma = get_conductivity(self.salt.currentText(), self.conc.value())
        factor = {'pA': 1e-12, 'nA': 1e-9}[self.unit.currentText()]
        current = self.curr.value() * factor
        voltage = self.volt.value() * 1e-3
        thickness = self.thick.value() * 1e-9
        conductance = current / voltage * 1e9
        diameter = calculate_pore_diameter(current, voltage,
                                           sigma=sigma, thickness=thickness)
        self.sigma_out.setText('%.4f' % sigma)
        self.g_out.setText('%.4f' % conductance)
        self.d_out.setText('%.3f' % diameter)


# Panel instance, docked between the file tree and the file info section
nano = NanoporePanel()
sec_nano = Collapsible(T('sec.nano'))
sec_nano.add_widget(nano)
vsplit.addWidget(sec_nano)


# Collapsible section: file path + metadata tree. Docks at the TOP of the
# left column (insertWidget(0, ...) -- it is constructed after sec_tree),
# and its explicit zero minimum lets the splitter squeeze it far below the
# DataTreeWidget's own minimumSizeHint: a compact path + metadata strip.
sec_info = Collapsible(T('sec.info'))
sec_info.add_widget(path_label)
sec_info.add_widget(data_tree)
sec_info.setMinimumHeight(0)
vsplit.insertWidget(0, sec_info)          # [info, tree, nano]

# Native-unit -> SI factors for auto-filling measured points
_Y_TO_SI = {
    'A': 1.0, 'mA': 1e-3, 'uA': 1e-6, 'µA': 1e-6, 'nA': 1e-9, 'pA': 1e-12,
    'V': 1.0, 'mV': 1e-3, 'uV': 1e-6, 'µV': 1e-6,
}


def autofill_measurement(y):
    """Fill the nanopore panel from the latest measured point: voltage-family
    traces go to Voltage (converted to mV), current-family traces to Current
    (converted to the combo unit). The latest point wins per field."""
    f = _Y_TO_SI.get(cur_yunit)
    if f is None:
        return
    if cur_yunit.endswith('V'):
        nano.volt.setText(nano.volt._fmt(y * f * 1e3))       # native -> mV
    else:
        combo = {'pA': 1e-12, 'nA': 1e-9}[nano.unit.currentText()]
        nano.curr.setText(nano.curr._fmt(y * f / combo))


# --- Zoom interaction ---------------------------------------------------------
#   drag on X axis strip -> zoom X only, drag on Y axis strip -> zoom Y only,
#   wheel anywhere -> zoom both axes, left-drag in plot -> pan,
#   Delete/Backspace -> restore auto range

vb = plot.getPlotItem().getViewBox()
vb.setMouseMode(pg.ViewBox.PanMode)

x_region = pg.LinearRegionItem(orientation='vertical', movable=False,
                               brush=pg.mkBrush(255, 255, 0, 50))
x_region.setZValue(-10)
y_region = pg.LinearRegionItem(orientation='horizontal', movable=False,
                               brush=pg.mkBrush(255, 255, 0, 50))
y_region.setZValue(-10)
for _r in (x_region, y_region):
    _r.hide()
    plot.getPlotItem().addItem(_r, ignoreBounds=True)


def add_zoom_regions():
    """Re-attach preview regions to the plot (plot.clear() detaches them)."""
    pi = plot.getPlotItem()
    for r in (x_region, y_region):
        if r.scene() is None:
            pi.addItem(r, ignoreBounds=True)


zoom_history = []
_last_wheel_push = 0.0

_orig_vb_wheel = vb.wheelEvent


def vb_wheel_event(ev, axis=None):
    """Wheel zoom with per-axis routing (pyqtgraph native): over the plot
    area axis=None -> dual-axis zoom; over an axis strip the AxisItem
    forwards axis=0/1 -> ONLY that axis zooms. The undo history keeps
    working: a burst of consecutive wheel events (< 0.5 s apart) is one
    undo step.
    """
    global _last_wheel_push
    now = time.time()
    if now - _last_wheel_push > 0.5:
        zoom_history.append(tuple(tuple(r) for r in vb.viewRange()))
    _last_wheel_push = now
    return _orig_vb_wheel(ev, axis=axis)


vb.wheelEvent = vb_wheel_event

_orig_vb_drag = vb.mouseDragEvent


def vb_drag_event(ev, axis=None):
    if (axis is None and ev.button() == pg.QtCore.Qt.LeftButton
            and measure_btn.isChecked()):
        # Measure mode takes over the in-plot left-drag: free two-point
        # delta between arbitrary (unsnapped) points; pan is suspended.
        # Axis-strip zoom (axis=0/1, handled below) still works.
        ev.accept()
        scene_p0 = ev.buttonDownScenePos()
        scene_p1 = ev.scenePos()
        p0 = vb.mapSceneToView(scene_p0)
        p1 = vb.mapSceneToView(scene_p1)
        if ev.isFinish():
            span = pg.QtCore.QLineF(scene_p0, scene_p1).length()
            if span < 5:
                drag_measure_hide()          # a click, not a drag: discard
            else:
                drag_measure_show(p0, p1)
            update_readout()
        else:
            drag_measure_show(p0, p1)
            update_readout()
        return
    if (axis is None and ev.button() == pg.QtCore.Qt.LeftButton
            and _amp_active()
            and (ev.modifiers() & pg.QtCore.Qt.ShiftModifier)):
        # Amp selection gesture: Shift + left-drag rubber-bands a new time
        # region for the amplitude histogram. Plain drag always pans and
        # axis-strip drag always zooms -- selection never hijacks them.
        # A tiny span on release is a click: discard.
        ev.accept()
        p0 = vb.mapSceneToView(ev.buttonDownScenePos())
        p1 = vb.mapSceneToView(ev.scenePos())
        lo, hi = sorted((float(p0.x()), float(p1.x())))
        if ev.isFinish():
            amp_drag_finish(lo, hi)
        else:
            amp_drag_update(lo, hi)
        return
    if (axis is None and ev.button() == pg.QtCore.Qt.LeftButton
            and _grab_active()
            and (ev.modifiers() & pg.QtCore.Qt.ShiftModifier)):
        # Grab selection gesture: Shift + left-drag rubber-bands an XY
        # rectangle -- one gesture gives BOTH the time scope (X) and the
        # event band (Y) of a scoped detection, committed to the record
        # list on release. Plain drag pans (or moves a rectangle the cursor
        # started inside); axis-strip drag zooms -- never hijacked.
        ev.accept()
        p0 = vb.mapSceneToView(ev.buttonDownScenePos())
        p1 = vb.mapSceneToView(ev.scenePos())
        x0, x1 = sorted((float(p0.x()), float(p1.x())))
        y0, y1 = sorted((float(p0.y()), float(p1.y())))
        if ev.isFinish():
            grab_drag_finish(x0, x1, y0, y1)
        else:
            grab_drag_update(x0, x1, y0, y1)
        return
    if axis is None or ev.button() != pg.QtCore.Qt.LeftButton:
        return _orig_vb_drag(ev, axis=axis)
    ev.accept()
    p0 = vb.mapSceneToView(ev.buttonDownScenePos())
    p1 = vb.mapSceneToView(ev.scenePos())
    if axis == 0:
        region, lo, hi = x_region, min(p0.x(), p1.x()), max(p0.x(), p1.x())
        total = vb.viewRange()[0][1] - vb.viewRange()[0][0]
    else:
        region, lo, hi = y_region, min(p0.y(), p1.y()), max(p0.y(), p1.y())
        total = vb.viewRange()[1][1] - vb.viewRange()[1][0]
    if ev.isFinish():
        region.hide()
        if total > 0 and hi - lo > 1e-12 * total:
            zoom_history.append(tuple(tuple(r) for r in vb.viewRange()))
            if axis == 0:
                vb.setXRange(lo, hi, padding=0)
            else:
                vb.setYRange(lo, hi, padding=0)
        return
    region.setRegion((lo, hi))
    region.show()


vb.mouseDragEvent = vb_drag_event


def restore_view():
    """Delete/Backspace: undo the last zoom step (no-op when history is empty)."""
    if not zoom_history:
        return
    xr, yr = zoom_history.pop()
    vb.setRange(xRange=xr, yRange=yr, padding=0)


QShortcut = getattr(pg.QtWidgets, 'QShortcut', pg.QtGui.QShortcut)
for _key in (pg.QtCore.Qt.Key_Delete, pg.QtCore.Qt.Key_Backspace):
    _sc = QShortcut(pg.QtGui.QKeySequence(_key), win)
    _sc.setContext(pg.QtCore.Qt.ApplicationShortcut)
    _sc.activated.connect(restore_view)


_bundle_cache = {}       # abspath -> Bundle, LRU (multi-document tabs)


def _bundle_cache_put(path, bundle):
    """Insert into the 2-entry LRU (most recent last)."""
    _bundle_cache.pop(path, None)
    _bundle_cache[path] = bundle
    while len(_bundle_cache) > 2:
        _bundle_cache.pop(next(iter(_bundle_cache)))


def load(file_name):
    """Load a new .dat file into the browser. The parsed bundle is
    LRU-cached (2 entries): switching document tabs between two files
    reuses the parse instead of re-reading the .pul."""
    global bundle, tree_items, _loaded_file, _loaded_fp

    file_name = os.path.abspath(file_name)
    bundle = _bundle_cache.get(file_name)
    if bundle is not None:
        _bundle_cache_put(file_name, bundle)       # LRU touch
    else:
        # Read the bundle header (no data is read at this time)
        bundle = heka_reader.Bundle(file_name)
        _bundle_cache_put(file_name, bundle)
    _loaded_file = file_name
    _loaded_fp = _file_fp(file_name)
    settings.setValue('last_dir', os.path.dirname(file_name))
    # the explorer column follows the loaded data (root = its directory;
    # F5 / follow reload in place and never touch the root)
    _exp_set_root(os.path.dirname(file_name))
    win.setWindowTitle(file_name)
    path_label.setText(file_name)
    if follow_btn.isChecked():
        _watch_switch(file_name)
    
    # Clear the tree and update to show the structure provided in the embedded
    # .pul file
    tree.clear()
    rebuild_tree(tree.invisibleRootItem(), [])
    replot()


# -- follow mode: near-live re-parse of a .dat Patchmaster is writing --------
#   QFileSystemWatcher on the loaded file; Patchmaster appends in bursts, so
#   changes are debounced 500 ms. A reload makes a FRESH Bundle (the old
#   instance caches its lazily-parsed .pul tree), rebuilds the file tree and
#   restores the selection by index path -- the view never jumps away from
#   what the user is looking at. A half-written sweep makes the parse raise;
#   that reload is skipped (silently while following) and the next file
#   change retries. New sweeps change the trace-label set, so previously
#   grabbed rows grey out (records stay) and the join axis grows.

_watcher = pg.QtCore.QFileSystemWatcher()
_follow_debounce = pg.QtCore.QTimer()
_follow_debounce.setSingleShot(True)
_follow_debounce.setInterval(500)


def _tree_item_by_path(path):
    """Tree item whose .index equals the given index path, or None.

    The tree's ONLY top-level item is the file root ('Pulsed', index [])
    -- all content hangs below it, so the descent starts at the root's
    children. (Comparing against invisibleRoot's children never matched:
    every real path starts with its G index, which silently broke the
    follow-mode selection restore and the grab-CSV import lock-on.)"""
    node = next((tree.topLevelItem(k)
                 for k in range(tree.topLevelItemCount())
                 if tuple(tree.topLevelItem(k).index) == ()), None)
    if node is None:
        return None
    for depth in range(len(path)):
        target = tuple(path[:depth + 1])
        node = next((node.child(k) for k in range(node.childCount())
                     if tuple(node.child(k).index) == target), None)
        if node is None:
            return None
    return node


def _reload_file(silent=False):
    """Re-parse the loaded .dat in place. Returns True on success."""
    global bundle, _loaded_fp
    if not _loaded_file or not os.path.isfile(_loaded_file):
        return False
    sel_paths = [tuple(it.index) for it in tree.selectedItems()]
    try:
        new_bundle = heka_reader.Bundle(_loaded_file)
        new_bundle.pul          # force the .pul parse NOW: a truncated
        bundle = new_bundle     # tail must raise here, not on first click
        _bundle_cache_put(_loaded_file, new_bundle)  # on-disk change: evict
        _file_fp_cache.pop(_loaded_file, None)    # content changed: rehash
        _loaded_fp = _file_fp(_loaded_file)
    except Exception:
        if not silent:
            pg.QtWidgets.QMessageBox.warning(
                win, T('reload.title'), T('reload.fail'))
        return False
    tree.blockSignals(True)
    tree.clear()
    rebuild_tree(tree.invisibleRootItem(), [])
    for path in sel_paths:
        item = _tree_item_by_path(path)
        if item is not None:
            item.setSelected(True)
    tree.blockSignals(False)
    replot()
    return True


def _watch_set(watcher, path):
    """Point `watcher` at exactly `path` (falsy -> watch nothing)."""
    for p in list(watcher.files()) + list(watcher.directories()):
        watcher.removePath(p)
    if path:
        watcher.addPath(path)


def _watch_switch(path):
    """Point the watcher at exactly one path."""
    _watch_set(_watcher, path)


def _follow_toggled(checked):
    if checked:
        if not _loaded_file:
            follow_btn.setChecked(False)      # nothing to watch yet
            return
        _watch_switch(_loaded_file)
    else:
        _watch_switch('')                     # stop watching everything


def _follow_changed(path):
    if not follow_btn.isChecked() or path != _loaded_file:
        return
    # some writers replace the file (the watcher then drops the path) --
    # re-add defensively and debounce the burst of changes
    if path not in _watcher.files():
        _watcher.addPath(path)
    _follow_debounce.start()


_follow_debounce.timeout.connect(lambda: _reload_file(silent=True))
_watcher.fileChanged.connect(_follow_changed)
follow_btn.toggled.connect(_follow_toggled)

_sc_f5 = QShortcut(pg.QtGui.QKeySequence('F5'), win)
_sc_f5.activated.connect(lambda: _reload_file())
    

def rebuild_tree(root_item, index):
    """Recursively read tree information from the bundle's embedded .pul file
    and add items into the GUI tree to allow browsing.

    Nodes show only their 0-based index (matching rec.list() / rec.get(N));
    the hierarchy is conveyed by indentation. The file root keeps 'Pulsed'.
    """
    global bundle
    root = bundle.pul
    node = root
    for i in index:
        node = node[i]
    if index:
        # path-style id, e.g. 'G0 S26 W3 T0' -- same numbering as the legend
        # / readout '(G#g S#w W#)' and rec.get(N)
        node_label = ' '.join('%s%d' % (lvl, i) for lvl, i in zip('GSWT', index))
    else:
        node_label = node.__class__.__name__.replace('Record', '')
    try:
        item_label = node.Label
    except AttributeError:
        item_label = ''
    item = pg.QtWidgets.QTreeWidgetItem([node_label, item_label])
    root_item.addChild(item)
    item.node = node
    item.index = index
    if len(index) < 2:
        item.setExpanded(True)
    for i in range(len(node.children)):
        rebuild_tree(item, index + [i])


def collect_traces(index, node, traces):
    """Recursively expand a tree node into all trace nodes it contains."""
    if len(index) == 4:
        traces[tuple(index)] = node
    else:
        for i in range(len(node.children)):
            collect_traces(index + [i], node.children[i], traces)


def trace_label(index):
    """Human-readable trace id: '<series label> (G#g S#w W#)' + ' T#' when
    the series holds multiple traces. Numbers are the 0-based indices from
    item.index, matching the tree node numbering."""
    series = bundle.pul[index[0]][index[1]]
    label = '%s (G%d S%d W%d)' % (series.Label, index[0], index[1], index[2])
    if len(series) > 1:
        label += ' T%d' % index[3]
    return label


def build_joined(entries):
    """Concatenate cached (x, y, label, trace) entries end-to-end on a
    continuous time axis.

    Each segment continues at the previous segment's end time using its own
    XInterval, so traces with different sampling rates or lengths mix fine.
    The y arrays come from the last_data cache (each read from disk once);
    the x axes are rebuilt from the running time. Returns
    (x, y, seams, segments): seams holds the junction times between
    consecutive segments (len(entries) - 1 entries); segments holds
    (x_start, x_end, label) per segment for the measure cursor lookup.
    The joined axis advancement must match _join_t_starts (detection side).
    """
    xs = []
    ys = []
    seams = []
    segments = []
    t = float(entries[0][0][0])
    for x, y, label, trace in entries:
        n = len(y)
        t0 = t
        ys.append(y)
        xs.append(t + np.arange(n) * trace.XInterval)
        t += n * trace.XInterval
        seams.append(t)
        segments.append((t0, t, label))
    return np.concatenate(xs), np.concatenate(ys), seams[:-1], segments


def replot():
    """Show data associated with the selected tree node(s).

    For all nodes, the meta-data is updated in the bottom tree.
    Group/Series/Sweep nodes expand to all traces they contain;
    trace nodes plot individually. Multi-selection plots the union
    (deduplicated) of all expanded traces.
    """
    global cur_xunit, cur_yunit, last_snap, join_segments, last_data
    global last_data_idx, _join_active, _join_cache, _prep_cache
    global _joined_display, _data_stamp
    plot.clear()
    legend.clear()
    data_tree.clear()
    clear_meas()
    clear_amp_regions()
    add_crosshair()
    add_zoom_regions()
    add_readout()
    zoom_history.clear()
    join_segments = []
    _join_active = False
    _join_cache = None
    _prep_cache = None
    _joined_display = None
    _data_stamp += 1

    selected = tree.selectedItems()
    if len(selected) < 1 or bundle is None:
        last_data = []
        last_data_idx = []
        add_grab_items()
        amp_recompute()
        return

    # update data tree
    sel = selected[0]
    fields = sel.node.get_fields()
    data_tree.setData(fields)

    # expand selected nodes into a deduplicated set of traces
    traces = {}
    for sel in selected:
        collect_traces(sel.index, sel.node, traces)
    items = sorted(traces.items())

    # cache every displayed trace (raw arrays, one disk read each) for the
    # analysis panel; plotting below reuses the cache
    last_data = []
    last_data_idx = []
    _data_stamp += 1
    for index, trace in items:
        data = bundle.data[list(index)]
        time = np.linspace(trace.XStart, trace.XStart + trace.XInterval * (len(data)-1), len(data))
        last_data.append((time, data, trace_label(index), trace))
        last_data_idx.append(tuple(index))

    if len(items) > 20:
        legend.hide()
    else:
        legend.show()

    if join_btn.isChecked() and len(items) > 1:
        trace0 = items[0][1]
        plot.setLabels(bottom=('Time', trace0.XUnit), left=(trace.Label, trace0.YUnit))
        cur_xunit = trace0.XUnit
        cur_yunit = trace0.YUnit
        x, y, seams, seg_infos = build_joined(last_data)
        join_segments = seg_infos
        _join_active = True
        _joined_display = (x, y)
        # VISUAL-only large-data guard (the analysis paths -- _joined_display,
        # amp_values, detection -- always read the full-resolution arrays):
        # a 26-sweep join at 500k samples is a 13M-point curve, and pyqtgraph
        # defaults (no downsampling, no clipping) rasterize the whole
        # QPainterPath every paint -- ~2 s per pan frame, ~5 s first paint
        # (measured offscreen, 2026-10; the 500mv-medium/low 'open is laggy'
        # report). auto+peak ds scales with the view span (this is a LONG
        # curve spanning the view -- the short-curve vanishing bug in
        # AGENTS.md does not apply here; the green event curves keep their
        # explicit auto=False override).
        c = plot.plot(x, y, pen=pg.mkPen(THEME['cycle'][0], width=1),
                      name='joined ×%d' % len(items))
        c.setDownsampling(auto=True, method='peak')
        c.setClipToView(True)
        for t in seams:
            line = pg.InfiniteLine(pos=t, angle=90, movable=False,
                                   pen=pg.mkPen(THEME['seam'], width=1, style=pg.QtCore.Qt.DashLine))
            plot.getPlotItem().addItem(line, ignoreBounds=True)
    else:
        for i, (x, y, label, trace) in enumerate(last_data):
            plot.setLabels(bottom=('Time', trace.XUnit), left=(trace.Label, trace.YUnit))
            cur_xunit = trace.XUnit
            cur_yunit = trace.YUnit
            c = plot.plot(x, y, pen=trace_pen(i, len(items)), name=label)
            c.setDownsampling(auto=True, method='peak')
            c.setClipToView(True)

    # amp column unit follows the displayed data; set HERE (data time), not
    # at analysis time, so committing the first region shifts nothing
    amp_plot.setLabel('left', '', units=cur_yunit)

    # rectangles re-attach ONLY against the NEW display: add_grab_items
    # reads _grab_source_key(), which is built from last_data -- calling
    # it before the rebuild made the PREVIOUS display's groups stick to
    # the new plot (stale-key bug, found while writing CSV import)
    add_grab_items()
    fit_view()
    amp_recompute()
    _grab_after_replot()


# replot when ever the user selects a new item
tree.itemSelectionChanged.connect(replot)


def join_toggled(checked):
    settings.setValue('join', checked)
    replot()


join_btn.toggled.connect(join_toggled)


# --- Distribution panel: amplitude histograms + scoped event grabs --------------
#   Amp    checkable: left-drag in the plot adds time regions; the Amplitude
#          tab shows the all-point histogram of the raw samples inside them.
#   Grab   scoped detection: Shift+drag an XY rectangle (X = time scope,
#          Y = the event band); every detected event becomes ONE row in the
#          record list (the user's unit of analysis -- one curated event per
#          row, dwell is the quantity of interest). Analysis always runs on
#          the per-trace raw arrays in last_data (never on the joined
#          display curve) through the pure functions in heka/analysis.py.

last_data = []           # (x, y, label, trace) of every displayed trace
last_data_idx = []       # tree index tuple per displayed trace (aligned)
amp_regions = []         # committed time-region items
_pending_region = None   # region currently being rubber-band dragged
_join_active = False   # Join on -> detection runs on the continuous axis
_join_cache = None     # (_data_stamp, head_s, smooth_ms, (x, y)) join axis
_prep_cache = None       # (_data_stamp, head_s, smooth_ms, [...]) per trace
_joined_display = None # raw joined (x, y) shown in the main plot
_data_stamp = 0          # bumped on every last_data rebind (cache keys)
_loaded_file = ''        # absolute path of the loaded .dat ('' = none)
_loaded_fp = None        # intrinsic hash of the loaded .dat (see _file_fp)
_FILE_FP_PREFIX = 4 * 1024 * 1024   # hashed prefix; append-stable for follow
_file_fp_cache = {}      # abspath -> hash (or None when unreadable)


def _file_fp(path):
    """Intrinsic file identity: sha256 over the first 4 MiB (hex, 16
    chars). Stable under move / rename / append (follow mode rewrites the
    tail, never the prefix), so CSV row matching needs no path at all;
    two acquisitions never share their noisy first megabytes in practice.
    ~10 ms per file, cached per path. None when unreadable."""
    if not path:
        return None
    p = os.path.abspath(path)
    if p in _file_fp_cache:
        return _file_fp_cache[p]
    fp = None
    try:
        h = hashlib.sha256()
        with open(p, 'rb') as fh:
            h.update(fh.read(_FILE_FP_PREFIX))
        fp = h.hexdigest()[:16]
    except OSError:
        fp = None
    _file_fp_cache[p] = fp
    return fp
_grab_pending = None     # rubber-band ROI while Shift+dragging a grab rect
_grab_syncing = False    # programmatic ROI moves: no recompute loops


def _tint(hexcolor, alpha):
    c = pg.QtGui.QColor(hexcolor)
    c.setAlpha(alpha)
    return pg.mkBrush(c)


def _join_t_starts(prepped):
    """Running start time of each prepped trace on the joined axis.

    Advances by the FULL sweep length (head slicing must not compress
    the time axis); must stay aligned with build_joined's display axis."""
    t, starts = float(prepped[0][3].XStart), []
    for _x, _y, _l, trace, n_full in prepped:
        starts.append(t)
        t += n_full * float(trace.XInterval)
    return starts


def analysis_segments(stride=1, head_s=0.0, smooth_ms=0.0):
    """(t, y) segments for heka.analysis.

    Default: one segment per displayed trace -- sweeps of one series share
    their time axis, so blind concatenation would fabricate events at the
    junctions. With Join on, the traces are instead concatenated on their
    true acquisition timeline (each trace's first head_s seconds sliced off
    to drop the capacitor transient), so a level sojourn that outlives a
    single sweep is detected as ONE event instead of being cut at every
    sweep boundary.

    smooth_ms > 0 median-compresses each trace into disjoint windows of
    that width before detection: spikes narrower than the window are
    crushed while second-scale level plateaus survive, so spike-riddled
    two-state traces can be analysed at all. The decimated time axis uses
    window centres; everything downstream (detection, dwell) lives on it.
    """
    global _join_cache, _prep_cache
    prepped = _prepped(head_s, smooth_ms)
    if _join_active and prepped:
        if (_join_cache is None
                or _join_cache[:3] != (_data_stamp, head_s, smooth_ms)):
            starts = _join_t_starts(prepped)
            xs, ys = [], []
            for (x, y, _label, trace, _n), start in zip(prepped, starts):
                xs.append(start + (x - float(trace.XStart)))
                ys.append(y)
            _join_cache = (_data_stamp, head_s, smooth_ms,
                             (np.concatenate(xs), np.concatenate(ys)))
        x, y = _join_cache[3]
        if stride > 1:
            x, y = x[::stride], y[::stride]
        return [(x, y)]
    segs = []
    for x, y, label, trace, n_full in prepped:
        if stride > 1:
            x, y = x[::stride], y[::stride]
        segs.append((x, y))
    return segs


def _prepped(head_s, smooth_ms):
    """Per-trace detection arrays: transient head sliced, optional median
    decimation applied; cached per (data version, head_s, smooth_ms).
    n_full = the ORIGINAL sample count, so the join accumulation can
    advance by full sweep durations while the arrays stay sliced."""
    global _prep_cache
    key = (_data_stamp, head_s, smooth_ms)
    if _prep_cache is None or _prep_cache[:3] != key:
        out = []
        for x, y, label, trace in last_data:
            n_full = len(y)
            dt = float(trace.XInterval)
            k = int(round(head_s / dt)) if dt > 0 else 0
            if k:
                x, y = x[k:], y[k:]
            w = max(1, int(round(smooth_ms * 1e-3 / dt))) if dt > 0 else 1
            m = (len(y) // w) * w
            if w > 1 and m >= w:
                y = np.median(y[:m].reshape(-1, w), axis=1)
                x = x[:m].reshape(-1, w).mean(axis=1)     # window centres
            if len(y):
                out.append((x, y, label, trace, n_full))
        _prep_cache = key + (out,)
    return _prep_cache[3]


def total_points():
    return sum(len(y) for _, y, _, _ in last_data)


def _tmin_points(t_min_ms, smooth_ms):
    """最短 (ms) -> 检测序列点数；平滑压缩后检测序列变稀，再除以窗宽。
    Used by the Grab tab's scoped detection."""
    dt0 = float(last_data[0][3].XInterval) if last_data else 0.0
    t_min_pts = max(1, int(round(t_min_ms * 1e-3 / dt0))) if dt0 > 0 else 1
    w = max(1, int(round(smooth_ms * 1e-3 / dt0))) if (dt0 > 0 and smooth_ms > 0) else 1
    return max(1, int(round(t_min_pts / w)))


_amp_syncing = False


def _amp_region_changed(*_):
    if not _amp_syncing:
        amp_preview()                 # strided live preview


def _amp_region_commit(*_):
    if not _amp_syncing:              # programmatic setRegion: skip
        amp_recompute()


def make_region(lo, hi, k):
    """Committed Amp region k: vertical band, edges draggable while the
    Amplitude tab is active (regions only exist while it is)."""
    color = THEME['cycle'][k % len(THEME['cycle'])]
    region = pg.LinearRegionItem(values=(lo, hi), orientation='vertical',
                                 movable=True, brush=_tint(color, 40),
                                 pen=pg.mkPen(color, width=1))
    region.setZValue(-8)
    plot.getPlotItem().addItem(region, ignoreBounds=True)
    region.sigRegionChanged.connect(_amp_region_changed)
    region.sigRegionChangeFinished.connect(_amp_region_commit)
    return region


def amp_drag_update(lo, hi):
    global _pending_region, _amp_syncing
    if _pending_region is None:
        _pending_region = make_region(lo, hi, len(amp_regions))
    else:
        _amp_syncing = True           # rubber-band preview: no recomputes
        try:
            _pending_region.setRegion((lo, hi))
        finally:
            _amp_syncing = False


def amp_drag_finish(lo, hi):
    global _pending_region
    total = vb.viewRange()[0][1] - vb.viewRange()[0][0]
    if _pending_region is not None:
        if hi - lo > 1e-9 * total:
            amp_regions.append(_pending_region)
        else:
            plot.getPlotItem().removeItem(_pending_region)
        _pending_region = None
    _refresh_region_list()
    amp_recompute()


def clear_amp_regions():
    global _pending_region
    pi = plot.getPlotItem()
    for r in ([_pending_region] if _pending_region is not None else []) + amp_regions:
        if r.scene() is not None:
            pi.removeItem(r)
    amp_regions.clear()
    _pending_region = None
    _refresh_region_list()


# -- Event panel + Amplitude column widgets --------------------------------------
#   The old two-tab Analysis panel (Amplitude | Grab) is split: Amplitude
#   lives in its own sideways-collapsible column right of the main plot,
#   the Event panel (formerly Grab) occupies the bottom slot directly.

sec_events = Collapsible(T('sec.dist'))
right_split.addWidget(sec_events)

# Amplitude column: the histogram is ROTATED -- Y = the current axis,
# X = % of samples -- and Y-linked to the main plot so a histogram peak
# sits at the same height as its current level in the trace. Bars are
# drawn in NATIVE units (pyqtgraph SI-prefixes the axis from the units=
# label), which is what makes the link line up with the main plot's
# native-unit view.
amp_col = CollapsibleColumn(T('amp.title'))
amp_body = pg.QtWidgets.QWidget()
amp_lay = pg.QtWidgets.QVBoxLayout(amp_body)
amp_lay.setContentsMargins(4, 4, 4, 4)
amp_lay.setSpacing(3)
# activation hint at the TOP, mirroring the Event panel's hint row; the
# bottom amp_stats keeps the per-region statistics only. Horizontal
# size policy Ignored on the one-line text labels: a QLabel's minimum
# width is its text width (~800 px for the zh hint!), which would pin
# the whole column open and SHRINK it again the moment the hint empties
# on the first committed region (the layout-min shift behind "it gets
# narrower after analysing"). Ignored lets the column be any width; the
# text clips when narrow and the tooltip carries the full wording.
amp_hint = pg.QtWidgets.QLabel('')
amp_hint.setSizePolicy(pg.QtWidgets.QSizePolicy.Ignored,
                       pg.QtWidgets.QSizePolicy.Preferred)
amp_hint.setStyleSheet('color:#999;')
amp_lay.addWidget(amp_hint)
# two control rows: the panel is narrow (15% of the window) and one row
# of every control would set a ~460 px minimum width on the column
amp_ctrl_a = pg.QtWidgets.QHBoxLayout()
amp_ctrl_b = pg.QtWidgets.QHBoxLayout()
amp_clear_btn = pg.QtWidgets.QPushButton(T('amp.clear'))
amp_ruler_btn = pg.QtWidgets.QPushButton(T('amp.ruler'))
amp_ruler_btn.setCheckable(True)
amp_ruler_btn.setToolTip(T('amp.tip.ruler'))
for _w in (amp_clear_btn, amp_ruler_btn):
    amp_ctrl_a.addWidget(_w)
amp_ctrl_a.addStretch(1)
amp_auto_bins = pg.QtWidgets.QCheckBox(T('amp.autobins'))
amp_auto_bins.setChecked(settings.value('amp/bins_auto', True, type=bool))
amp_bins = NumericEdit(float(settings.value('amp/bins', 150.0, type=float)),
                       8, 4096, commit_on='finish')
amp_follow = pg.QtWidgets.QCheckBox(T('amp.follow'))
amp_follow.setChecked(settings.value('amp/follow', False, type=bool))
for _w in (amp_auto_bins, pg.QtWidgets.QLabel('bins'), amp_bins, amp_follow):
    amp_ctrl_b.addWidget(_w)
amp_ctrl_b.addStretch(1)
amp_ctrl_rows = pg.QtWidgets.QVBoxLayout()
amp_ctrl_rows.addLayout(amp_ctrl_a)
amp_ctrl_rows.addLayout(amp_ctrl_b)
amp_lay.addLayout(amp_ctrl_rows)
amp_list_widget = pg.QtWidgets.QWidget()          # one row per committed region
amp_list_lay = pg.QtWidgets.QVBoxLayout(amp_list_widget)
amp_list_lay.setContentsMargins(0, 0, 0, 0)
amp_list_lay.setSpacing(1)
amp_lay.addWidget(amp_list_widget)
amp_plot = pg.PlotWidget()
# Reserve the left-axis width up front: tick numbers and the unit label
# only appear once analysis fills the histogram, and their late arrival
# used to visibly narrow the column on the first committed region (the
# layout-shift the users reported as "it shrinks after analysing").
amp_plot.getPlotItem().getAxis('left').setWidth(56)
amp_plot.setLabels(bottom=T('amp.axisy'))
amp_lay.addWidget(amp_plot, 1)
amp_ruler_lbl = pg.QtWidgets.QLabel('')
amp_ruler_lbl.setSizePolicy(pg.QtWidgets.QSizePolicy.Ignored,
                            pg.QtWidgets.QSizePolicy.Preferred)
amp_lay.addWidget(amp_ruler_lbl)
amp_stats = pg.QtWidgets.QLabel('')
amp_stats.setWordWrap(True)
amp_lay.addWidget(amp_stats)
amp_col.body_lay.addWidget(amp_body, 1)
top_split.addWidget(amp_col)
# stretch: the main plot absorbs all resizing, the amp column keeps
# whatever width it was given (setSizes / drag / restore). Without this,
# every layout pass redistributes surplus space per size hints and the
# column springs back open -- the "too wide no matter what" effect.
top_split.setStretchFactor(0, 1)
top_split.setStretchFactor(1, 0)


def _amp_follow_main_y(*_):
    """Mirror the main plot's Y view onto the amplitude histogram.

    Deliberately NOT ViewBox.setYLink: pyqtgraph's link is PIXEL-aligning
    (linkedViewChanged maps units-per-pixel between the two views' screen
    geometries) -- correct for overlaid plots, wrong for a side panel of a
    different height, where it silently drifts the range (0.14实测:
    [-200,50] -> [-185.5,50]). A manual mirror is exact and one-way.
    """
    avb = amp_plot.getPlotItem().getViewBox()
    y0, y1 = vb.viewRange()[1]
    avb.enableAutoRange(y=False)
    avb.setYRange(y0, y1, padding=0)

# Peak ruler: two draggable horizontal markers on the amplitude histogram
# (values on the Y=current axis) for reading peak positions and their
# difference (dI between two states)
ruler_a = pg.InfiniteLine(angle=0, movable=True,
                          pen=pg.mkPen(THEME['A'], width=1))
ruler_b = pg.InfiniteLine(angle=0, movable=True,
                          pen=pg.mkPen(THEME['B'], width=1))
for _r in (ruler_a, ruler_b):
    _r.hide()


def _attach_ruler():
    pi = amp_plot.getPlotItem()
    for _r in (ruler_a, ruler_b):
        if _r.scene() is None:
            pi.addItem(_r, ignoreBounds=True)
    on = amp_ruler_btn.isChecked()
    ruler_a.setVisible(on)
    ruler_b.setVisible(on)


def _update_ruler(*_):
    if not amp_ruler_btn.isChecked():
        return
    _, prefix = _yunit_scale()
    unit_s = '%s%s' % (prefix, cur_yunit)
    amp_ruler_lbl.setText(
        '<b>A</b> = %s &nbsp; <b>B</b> = %s &nbsp; <b>Δ = %s</b>'
        % (fmt_si(ruler_a.value(), unit_s), fmt_si(ruler_b.value(), unit_s),
           fmt_si(abs(ruler_b.value() - ruler_a.value()), unit_s)))


def amp_ruler_toggled(checked):
    _attach_ruler()
    if checked:
        y0, y1 = amp_plot.getPlotItem().getViewBox().viewRange()[1]
        if not y0 <= ruler_a.value() <= y1:
            ruler_a.setValue(y0 + 0.3 * (y1 - y0))
        if not y0 <= ruler_b.value() <= y1:
            ruler_b.setValue(y0 + 0.7 * (y1 - y0))
    _update_ruler()

# Detailed per-parameter explanations for the Grab tab's edge rules; every
# label AND its field carry the same tooltip (users hover the text, not the
# box). Historically the Events tab's tooltips -- that tab is gone (one
# curated event per Grab row replaced whole-data detection), the physics
# stayed.

# Event panel (formerly the Grab tab): scoped detection -- Shift+drag an XY
# rectangle in the main plot (X = analysis time scope, Y = the event band),
# detection runs inside it and the result is snapshotted into the record
# list (right half). Detection parameters are this panel's own (snapshot at
# grab/edit time; records keep the params they were made with).
event_body = pg.QtWidgets.QWidget()
grab_lay = pg.QtWidgets.QVBoxLayout(event_body)
grab_lay.setContentsMargins(4, 4, 4, 4)
grab_lay.setSpacing(2)

grab_hint_row = pg.QtWidgets.QHBoxLayout()
grab_hint = pg.QtWidgets.QLabel(T('grab.hint'))
grab_hint.setStyleSheet('color:#999;')
grab_hint.setToolTip(T('grab.tip.hint'))
grab_hint_row.addWidget(grab_hint)
grab_hint_row.addStretch(1)
grab_lay.addLayout(grab_hint_row)

grab_ctrl = pg.QtWidgets.QHBoxLayout()           # this tab's own edge rules
grab_mode = pg.QtWidgets.QComboBox()
grab_mode.addItems(['inside', 'outside', 'below', 'above'])
grab_mode.setCurrentText(settings.value('grab/mode', 'inside', type=str))
grab_k = NumericEdit(float(settings.value('grab/k', 3.0, type=float)),
                     0.0, 1e4, commit_on='finish')
grab_tmin = NumericEdit(float(settings.value('grab/t_min_ms', 0.1, type=float)),
                        0.0, 1e4, commit_on='finish')
grab_merge = NumericEdit(float(settings.value('grab/merge', 0.0, type=float)),
                         0.0, 1e4, commit_on='finish')
grab_head = NumericEdit(float(settings.value('grab/head', 10.0, type=float)),
                        0.0, 1e4, commit_on='finish')
grab_smooth = NumericEdit(float(settings.value('grab/smooth', 0.0, type=float)),
                          0.0, 1e4, commit_on='finish')
grab_duty = NumericEdit(float(settings.value('grab/duty', 0.5, type=float)),
                        0.0, 1.0, commit_on='finish')
for _name, _field, _tip in ((T('grab.p.mode'), grab_mode, 'evt.tip.mode'),
                            (T('grab.p.k'), grab_k, 'evt.tip.k'),
                            (T('grab.p.tmin'), grab_tmin, 'evt.tip.tmin'),
                            (T('grab.p.merge'), grab_merge, 'evt.tip.merge'),
                            (T('grab.p.head'), grab_head, 'evt.tip.head'),
                            (T('grab.p.smooth'), grab_smooth, 'evt.tip.smooth'),
                            (T('grab.p.duty'), grab_duty, 'evt.tip.duty')):
    _lab = pg.QtWidgets.QLabel(_name)
    _lab.setToolTip(T(_tip))
    _field.setToolTip(T(_tip))
    grab_ctrl.addWidget(_lab)
    grab_ctrl.addWidget(_field)
grab_ctrl.addStretch(1)
grab_lay.addLayout(grab_ctrl)

grab_split = pg.QtWidgets.QSplitter(pg.QtCore.Qt.Horizontal)
grab_left = pg.QtWidgets.QWidget()
grab_left_lay = pg.QtWidgets.QVBoxLayout(grab_left)
grab_left_lay.setContentsMargins(0, 0, 0, 0)
grab_left_lay.setSpacing(2)
grab_plot = pg.PlotWidget()
grab_left_lay.addWidget(grab_plot, 1)
grab_detail_lbl = pg.QtWidgets.QLabel('')
grab_left_lay.addWidget(grab_detail_lbl)
grab_split.addWidget(grab_left)

grab_right = pg.QtWidgets.QWidget()
grab_right_lay = pg.QtWidgets.QVBoxLayout(grab_right)
grab_right_lay.setContentsMargins(0, 0, 0, 0)
grab_right_lay.setSpacing(2)


class _GrabDelDelegate(pg.QtWidgets.QStyledItemDelegate):
    """Paints the per-row × delete affordance in column 5 and turns a
    left-button release there into _grab_delete. NO per-row itemWidget
    QPushButtons: ~1300 embedded widgets cost ~14.5 s per clear+rebuild
    on a SHOWN Cocoa QTreeWidget (the 500mv-medium/low freeze, 2026-10;
    plain-item rebuilds are ~2 ms -- and offscreen probes never see the
    native-view cost, only a real-platform bench does). The click also
    selects the row (the old real button consumed it); _grab_delete's
    neighbour-fallback selection and its 250 ms double-click guard
    already cover that."""

    def paint(self, p, option, index):
        hover = bool(option.state & pg.QtWidgets.QStyle.State_MouseOver)
        p.save()
        p.setPen(pg.QtGui.QPen(
            pg.QtGui.QColor(THEME['accent'] if hover else '#9C9C9C')))
        f = pg.QtGui.QFont(option.font)
        f.setBold(hover)
        p.setFont(f)
        p.drawText(option.rect, pg.QtCore.Qt.AlignCenter, '×')
        p.restore()

    def editorEvent(self, ev, model, option, index):
        if (ev.type() == pg.QtCore.QEvent.MouseButtonRelease
                and ev.button() == pg.QtCore.Qt.LeftButton):
            it = grab_tree.topLevelItem(index.row())   # flat list, no children
            rid = getattr(it, 'rec_id', None)
            if rid is not None:
                _grab_delete(rid)
                return True
        return pg.QtWidgets.QStyledItemDelegate.editorEvent(
            self, ev, model, option, index)


grab_tree = pg.QtWidgets.QTreeWidget()
grab_tree.setHeaderLabels(['#', 't_start', 'dwell', 'level',
                           T('grab.col.noise'), ''])
grab_tree.setRootIsDecorated(False)
grab_tree.setSelectionBehavior(
    pg.QtWidgets.QAbstractItemView.SelectRows)
grab_tree.setEditTriggers(pg.QtWidgets.QAbstractItemView.NoEditTriggers)
grab_tree.setUniformRowHeights(True)
grab_tree.setItemDelegateForColumn(5, _GrabDelDelegate(grab_tree))
# data columns stretch to fill the tree width; # and the x button stay
# fixed -- the rows spread with the panel instead of huddling on the left
_grab_hdr = grab_tree.header()
_grab_hdr.setSectionResizeMode(0, pg.QtWidgets.QHeaderView.Fixed)
for _c in (1, 2, 3, 4):
    _grab_hdr.setSectionResizeMode(_c, pg.QtWidgets.QHeaderView.Stretch)
_grab_hdr.setSectionResizeMode(5, pg.QtWidgets.QHeaderView.Fixed)
_grab_hdr.setStretchLastSection(False)
_grab_hdr.setSectionsClickable(True)
grab_tree.setColumnWidth(0, 40)
grab_tree.setColumnWidth(5, 26)
grab_right_lay.addWidget(grab_tree, 1)
grab_stats_lbl = pg.QtWidgets.QLabel('')   # running stats over ALL rows
grab_stats_lbl.setStyleSheet('color:#666;')
grab_right_lay.addWidget(grab_stats_lbl)
grab_btns = pg.QtWidgets.QHBoxLayout()
grab_viewall_btn = pg.QtWidgets.QPushButton(T('grab.viewall'))
grab_viewall_btn.setCheckable(True)
grab_viewall_btn.setToolTip(T('grab.tip.viewall'))
grab_recalc_btn = pg.QtWidgets.QPushButton(T('grab.recalc'))
grab_recalc_btn.setToolTip(T('grab.tip.recalc'))
grab_clear_btn = pg.QtWidgets.QPushButton(T('grab.clear'))
grab_btns.addStretch(1)
for _b in (grab_viewall_btn, grab_recalc_btn, grab_clear_btn):
    grab_btns.addWidget(_b)
grab_right_lay.addLayout(grab_btns)
grab_split.addWidget(grab_right)

# File explorer column (MATLAB-style current folder), third pane of the
# Grab tab: a plain QListWidget fed by QDir.entryInfoList and kept live by
# a QFileSystemWatcher on the current directory. Deliberately NOT the
# QFileSystemModel + QSortFilterProxyModel stack: dynamic proxy sorting
# over the model's async fetcher thread segfaulted intermittently
# (QTBUG-class race, unreproducible-friendly but 100% real offscreen),
# and we only show a name column anyway. Our own sort: directories on
# top, then a numeric-aware case-insensitive collator (a2.csv < a10.csv).
exp_col = CollapsibleColumn(T('exp.title'))
exp_tools = pg.QtWidgets.QHBoxLayout()
exp_dir_lbl = pg.QtWidgets.QLabel('')
exp_dir_lbl.setStyleSheet('color:#666;')
exp_tools.addWidget(exp_dir_lbl, 1)
exp_csv_only = pg.QtWidgets.QCheckBox(T('exp.csvonly'))
exp_csv_only.setChecked(settings.value('explorer/csv_only', True, type=bool))
exp_csv_only.setToolTip(T('exp.tip.csvonly'))
exp_up = pg.QtWidgets.QPushButton('\u2191')
exp_up.setFixedWidth(26)
exp_up.setToolTip(T('exp.tip.up'))
exp_refresh_btn = pg.QtWidgets.QPushButton('\u21bb')
exp_refresh_btn.setFixedWidth(26)
exp_refresh_btn.setToolTip(T('exp.tip.refresh'))
for _w in (exp_csv_only, exp_up, exp_refresh_btn):
    exp_tools.addWidget(_w)
exp_col.body_lay.addLayout(exp_tools)
exp_list = pg.QtWidgets.QListWidget()
exp_list.setEditTriggers(pg.QtWidgets.QAbstractItemView.NoEditTriggers)
exp_list.setSortingEnabled(False)        # the refresh owns the order
exp_list.setToolTip(T('exp.tip.list'))
exp_col.body_lay.addWidget(exp_list, 1)

_exp_dir = ['']
_exp_collator = pg.QtCore.QCollator()
_exp_collator.setCaseSensitivity(pg.QtCore.Qt.CaseInsensitive)
_exp_collator.setNumericMode(True)
_exp_icons = pg.QtWidgets.QFileIconProvider()
exp_watcher = pg.QtCore.QFileSystemWatcher()
_exp_watch_debounce = pg.QtCore.QTimer()   # watcher events arrive in bursts
_exp_watch_debounce.setSingleShot(True)
_exp_watch_debounce.setInterval(200)


def _exp_entries():
    """Visible entries of the current dir: dirs first, then files (csv
    filter applies to files only), both name-sorted by the collator."""
    if not _exp_dir[0]:
        return []
    qdir = pg.QtCore.QDir(_exp_dir[0])
    qdir.setFilter(pg.QtCore.QDir.Files | pg.QtCore.QDir.AllDirs
                   | pg.QtCore.QDir.NoDotAndDotDot)
    infos = qdir.entryInfoList()
    dirs = [i for i in infos if i.isDir()]
    files = [i for i in infos if not i.isDir()]
    if exp_csv_only.isChecked():
        files = [f for f in files
                 if f.suffix().lower() == 'csv']
    key = lambda fi: _exp_collator.sortKey(fi.fileName())
    return (sorted(dirs, key=key) + sorted(files, key=key))


def _exp_refresh():
    """Rebuild the list; keep the selection on the same path if alive.
    Runs under _exp_building: the per-item setData calls would otherwise
    look like rename commits to _exp_item_changed."""
    _exp_building[0] = True
    try:
        current = (exp_list.currentItem().data(pg.QtCore.Qt.UserRole)
                   if exp_list.currentItem() else None)
        exp_list.clear()
        for fi in _exp_entries():
            it = pg.QtWidgets.QListWidgetItem(_exp_icons.icon(fi),
                                              fi.fileName())
            it.setFlags(it.flags() | pg.QtCore.Qt.ItemIsEditable)
            it.setData(pg.QtCore.Qt.UserRole, fi.absoluteFilePath())
            exp_list.addItem(it)
            if fi.absoluteFilePath() == current:
                exp_list.setCurrentItem(it)
    finally:
        _exp_building[0] = False


def _exp_watch_switch(path):
    _watch_set(exp_watcher, path)


def _exp_set_root(path, save=True):
    """Point the explorer column at a directory (persisted as startup
    dir); the watcher follows so live updates keep flowing."""
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return
    _exp_dir[0] = path
    exp_dir_lbl.setText(os.path.basename(path) or path)
    exp_dir_lbl.setToolTip(path)
    exp_up.setEnabled(os.path.dirname(path) != path)
    _exp_watch_switch(path)
    _exp_refresh()
    if save:
        settings.setValue('explorer/dir', path)


def _exp_up():
    parent = os.path.dirname(_exp_dir[0]) if _exp_dir[0] else ''
    if parent and parent != _exp_dir[0]:
        _exp_set_root(parent)


def _exp_csv_toggled(checked):
    settings.setValue('explorer/csv_only', checked)
    _exp_refresh()


def _exp_double_clicked(item):
    path = item.data(pg.QtCore.Qt.UserRole)
    if not path:
        return
    if os.path.isdir(path):
        _exp_set_root(path)
    elif os.path.splitext(path)[1].lower() == '.csv':
        _open_doc(path)


# -- inline rename: Return/F2 starts an editor on the selected entry ----
#   Double-click keeps its open/enter meaning; editing only ever starts
#   programmatically (editItem), so NoEditTriggers stays. The commit
#   lands in _exp_item_changed (itemChanged), guarded against the
#   refresh's own setData calls by _exp_building.
_exp_building = [False]


class _ExpKeyFilter(pg.QtCore.QObject):
    """Return / Enter / F2 on the explorer list = rename the selected
    file or directory (the standard F2 binding plus Return, as requested).
    Consumed here so QListWidget's own Return handling (itemActivated)
    never fires -- double-click remains the only opener."""

    def eventFilter(self, obj, ev):
        if (ev.type() == pg.QtCore.QEvent.KeyPress
                and ev.key() in (pg.QtCore.Qt.Key_Return,
                                 pg.QtCore.Qt.Key_Enter,
                                 pg.QtCore.Qt.Key_F2)
                and exp_list.currentItem() is not None
                and exp_list.state()
                != pg.QtWidgets.QAbstractItemView.EditingState):
            exp_list.editItem(exp_list.currentItem())
            return True
        return pg.QtCore.QObject.eventFilter(self, obj, ev)


def _exp_rename_fixups(old, new):
    """Repoint everything that referenced the old path: open documents
    (their tab label follows the new basename), and the loaded .dat
    (window title, path bar, follow watcher, bundle-LRU cache key) --
    saving after a rename must not silently resurrect the old file."""
    global _loaded_file
    for d in _doc_list:
        if d.get('path') == old:
            d['path'] = new
            d.pop('name', None)             # the label follows the new file
            if d is _doc:
                _doc_sync_tab()
            else:
                doc_tabs.setTabText(_doc_list.index(d), _doc_tab_label(d))
    if _loaded_file == old:
        _loaded_file = new
        win.setWindowTitle(new)
        path_label.setText(new)
        b = _bundle_cache.pop(old, None)
        if b is not None:
            _bundle_cache[new] = b
        fp = _file_fp_cache.pop(old, None)
        if fp is not None:
            _file_fp_cache[new] = fp
        if follow_btn.isChecked():
            _watch_switch(new)


def _exp_item_changed(item):
    """Editor commit on an explorer row = rename the file/dir."""
    if _exp_building[0]:
        return
    path = item.data(pg.QtCore.Qt.UserRole)
    if not path or not os.path.exists(path):
        _exp_refresh()                      # stale row: just rebuild
        return
    old = os.path.basename(path)
    new = item.text().strip()
    target = os.path.join(os.path.dirname(path), new)

    def _revert():
        _exp_building[0] = True
        try:
            item.setText(old)
        finally:
            _exp_building[0] = False

    if new == old:
        _revert()
        return
    if (not new) or new in ('.', '..') or '/' in new or os.sep in new:
        pg.QtWidgets.QMessageBox.warning(
            win, T('exp.rename.title'), T('exp.rename.badname'))
        _revert()
        return
    if os.path.exists(target) and not os.path.samefile(path, target):
        # samefile lets a case-only rename through on case-insensitive
        # filesystems (target "exists" because it IS the same file)
        pg.QtWidgets.QMessageBox.warning(
            win, T('exp.rename.title'), T('exp.rename.exists', name=new))
        _revert()
        return
    try:
        os.rename(path, target)
    except OSError as exc:
        pg.QtWidgets.QMessageBox.warning(
            win, T('exp.rename.title'), T('exp.rename.fail', err=exc))
        _revert()
        return
    _exp_rename_fixups(path, target)
    # make the refresh keep the selection on the renamed entry
    _exp_building[0] = True
    try:
        item.setData(pg.QtCore.Qt.UserRole, target)
    finally:
        _exp_building[0] = False
    _exp_refresh()


exp_list.installEventFilter(_ExpKeyFilter())
exp_watcher.directoryChanged.connect(
    lambda *_: _exp_watch_debounce.start())
_exp_watch_debounce.timeout.connect(lambda: _exp_refresh())
exp_refresh_btn.clicked.connect(lambda *_: _exp_refresh())

grab_split.setStretchFactor(0, 1)
grab_split.setStretchFactor(1, 1)
grab_lay.addWidget(grab_split, 1)

# --- Document pages: empty state vs. open document -----------------------------
#   The Event panel hosts ONE analysis document at a time (multi-tab arrives
#   with Phase 3). No document -> a centred New button; document open ->
#   closable tab + Save / Save As + the grab content. The file column stays
#   visible in BOTH states: it is the open-a-document entry point.
doc_pages = pg.QtWidgets.QStackedWidget()

empty_page = pg.QtWidgets.QWidget()
empty_lay = pg.QtWidgets.QVBoxLayout(empty_page)
empty_new_btn = pg.QtWidgets.QPushButton(T('doc.new'))
empty_new_btn.setMinimumHeight(56)
empty_hint = pg.QtWidgets.QLabel(T('doc.empty.hint'))
empty_hint.setStyleSheet('color:#999;')
empty_hint.setAlignment(pg.QtCore.Qt.AlignCenter)
empty_lay.addStretch(1)
empty_lay.addWidget(empty_new_btn, 0, pg.QtCore.Qt.AlignCenter)
empty_lay.addSpacing(10)
empty_lay.addWidget(empty_hint, 0, pg.QtCore.Qt.AlignCenter)
empty_lay.addStretch(1)
doc_pages.addWidget(empty_page)

doc_page = pg.QtWidgets.QWidget()
doc_lay = pg.QtWidgets.QVBoxLayout(doc_page)
doc_lay.setContentsMargins(0, 0, 0, 0)
doc_lay.setSpacing(2)
doc_bar = pg.QtWidgets.QHBoxLayout()
doc_tabs = pg.QtWidgets.QTabBar()
doc_tabs.setTabsClosable(True)
doc_tabs.setExpanding(False)
doc_new_btn = pg.QtWidgets.QPushButton(T('doc.newbtn'))
doc_new_btn.setToolTip(T('doc.new'))
doc_save_btn = pg.QtWidgets.QPushButton(T('doc.save'))
doc_saveas_btn = pg.QtWidgets.QPushButton(T('doc.saveas'))
doc_bar.addWidget(doc_tabs, 1)
doc_bar.addWidget(doc_new_btn)
doc_bar.addWidget(doc_save_btn)
doc_bar.addWidget(doc_saveas_btn)
doc_lay.addLayout(doc_bar)
doc_lay.addWidget(event_body, 1)
doc_pages.addWidget(doc_page)

doc_split = pg.QtWidgets.QSplitter(pg.QtCore.Qt.Horizontal)
doc_split.addWidget(doc_pages)
doc_split.addWidget(exp_col)
doc_split.setStretchFactor(0, 1)
doc_split.setStretchFactor(1, 0)
doc_pages.setCurrentIndex(0)          # app starts with no document open
sec_events.add_widget(doc_split)

# Visible, grabbable splitter handles everywhere: the Fusion default is a
# few same-colour pixels that nobody can find or drag. A quiet grey bar
# that lights up (theme accent blue) on hover marks every divider.
_SPLIT_ACCENT = '#4E79A7'
_SPLITTER_QSS = (
    'QSplitter::handle { background: #DCDCDC; border-radius: 2px; }'
    'QSplitter::handle:horizontal { width: 5px; margin: 3px 1px; }'
    'QSplitter::handle:vertical { height: 5px; margin: 1px 3px; }'
    'QSplitter::handle:hover { background: %s; }'
    'QSplitter::handle:pressed { background: %s; }'
    % (_SPLIT_ACCENT, _SPLIT_ACCENT))
for _sp in (hsplit, vsplit, top_split, right_split, doc_split, grab_split):
    _sp.setHandleWidth(9)
    _sp.setStyleSheet(_SPLITTER_QSS)


# -- Document lifecycle (multi-tab) -----------------------------------------
#   Document = the flat event CSV itself (v5 = the v4 columns + a '#'
#   params header). The event rows ARE the content; rectangles / view
#   state live in the per-tab session slot only. Tabs coexist: New / Open
#   ADD a tab (nothing is lost, so no confirmation) -- only CLOSING a
#   dirty tab asks. The ACTIVE document's session state lives in the
#   module globals (grab_records / _grab_groups / _grab_rects / selection
#   / counters / params); switching tabs captures those into the outgoing
#   doc's slot and restores the incoming one. The display context is
#   never snapshotted -- it is re-derived from the rows (bootstrap).
_DOC_CLOSED = {'open': False, 'path': None, 'dirty': False}
_doc = _DOC_CLOSED          # the ACTIVE document (sentinel when none)
_doc_list = []              # every open document; list index == tab index
_doc_switching = [False]    # re-entrancy guard around currentChanged


def _doc_tab_label(d):
    name = (d.get('name') or (os.path.basename(d['path']) if d['path']
                              else T('doc.untitled')))
    return name + (' •' if d['dirty'] else '')


def _doc_sync_tab():
    if _doc is not _DOC_CLOSED:
        i = _doc_list.index(_doc)
        doc_tabs.setTabText(i, _doc_tab_label(_doc))
        doc_tabs.setTabToolTip(i, _doc['path'] or _doc.get('name') or '')


def _doc_touch():
    """Any real change to the event rows marks the document dirty."""
    if _doc is not _DOC_CLOSED and not _doc['dirty']:
        _doc['dirty'] = True
        _doc_sync_tab()


def _doc_activate_tab(d):
    """Append d's tab and make it current WITHOUT recursing through the
    currentChanged handler (the caller drives the state swap itself)."""
    _doc_switching[0] = True
    try:
        doc_tabs.addTab('')
        doc_tabs.setCurrentIndex(doc_tabs.count() - 1)
    finally:
        _doc_switching[0] = False
    _doc_sync_tab()
    doc_pages.setCurrentIndex(1)


def _doc_spawn(d):
    """Append a document slot, make it active, open its tab."""
    global _doc
    _doc_list.append(d)
    _doc = d
    _doc_activate_tab(d)


def _grab_detach_rects():
    """Take every rectangle off the main plot (they stay alive in their
    doc slot; add_grab_items re-attaches the matching ones after the
    next replot)."""
    pi = plot.getPlotItem()
    for roi in _grab_rects.values():
        if roi.scene() is not None:
            pi.removeItem(roi)


def _grab_clear_state():
    """Drop ALL in-memory grab state (rows / groups / rects / selection)."""
    global grab_records, _grab_groups, _grab_rects
    global _grab_selected, _grab_focus_gid
    _grab_detach_rects()
    grab_records = []
    _grab_groups = {}
    _grab_rects = {}
    _grab_selected = None
    _grab_focus_gid = None
    _grab_items.clear()


def _doc_state_capture():
    """Globals -> the active document's session slot. Rects are detached
    from the plot; tree rows are rebuilt on restore."""
    if _doc is _DOC_CLOSED:
        return
    _grab_detach_rects()
    _doc['state'] = dict(
        records=grab_records, groups=_grab_groups, rects=_grab_rects,
        selected=_grab_selected, focus=_grab_focus_gid,
        next_eid=_grab_next_eid[0], next_gid=_grab_next_gid[0],
        params=_grab_params())
    _grab_clear_state()


def _doc_state_restore():
    """The active document's session slot -> globals (+ param widgets)."""
    global grab_records, _grab_groups, _grab_rects
    global _grab_selected, _grab_focus_gid
    st = _doc.get('state') or {}
    grab_records = st.get('records') or []
    _grab_groups = st.get('groups') or {}
    _grab_rects = st.get('rects') or {}
    _grab_selected = st.get('selected')
    _grab_focus_gid = st.get('focus')
    _grab_next_eid[0] = st.get('next_eid', 1)
    _grab_next_gid[0] = st.get('next_gid', 1)
    _grab_items.clear()
    p = dict(st.get('params') or {})
    if p:
        _apply_doc_params(p)
    _refresh_grab_list()
    _grab_refresh_views()


def _doc_switch(idx):
    """Activate another tab: capture the outgoing session into its slot,
    restore the incoming one, re-derive the display context from rows."""
    global _doc
    if _doc_switching[0] or not (0 <= idx < len(_doc_list)):
        return
    if _doc is _doc_list[idx]:
        return
    _doc_switching[0] = True
    try:
        _doc_state_capture()
        _doc = _doc_list[idx]
        doc_tabs.setCurrentIndex(idx)
        _doc_state_restore()
        _doc_restore_context()
        _doc_sync_tab()
        doc_pages.setCurrentIndex(1)
    finally:
        _doc_switching[0] = False


def _doc_open_untitled():
    """Birth a new untitled document in its own tab. No confirmation:
    the existing documents stay open in theirs."""
    global _doc
    _doc_state_capture()
    n = sum(1 for d in _doc_list if d['path'] is None) + 1
    d = {'open': True, 'path': None, 'dirty': False, 'state': {},
         'name': (T('doc.untitled') if n == 1
                  else '%s %d' % (T('doc.untitled'), n))}
    _doc_spawn(d)
    # Empty slot -> globals + PANEL repaint. Without this the tree /
    # summary / detail view / green overlays kept showing the OUTGOING
    # document's rows (the model was already empty -- a display lie that
    # survived until some later action happened to call
    # _refresh_grab_list; the zero-event and >500 grab paths never do).
    _doc_state_restore()


def _reset_grab_globals():
    """Drop ALL active grab state (rows / groups / rects / selection)
    without touching the document bookkeeping."""
    _grab_clear_state()
    _refresh_grab_list()


def _doc_close_now():
    """Close the ACTIVE document unconditionally (any confirmation has
    already happened); a neighbour tab activates, or the panel returns
    to the empty state."""
    global _doc
    if _doc is _DOC_CLOSED:
        doc_pages.setCurrentIndex(0)
        return
    i = _doc_list.index(_doc)
    _reset_grab_globals()
    _doc_list.pop(i)
    _doc = _DOC_CLOSED
    _doc_switching[0] = True
    try:
        doc_tabs.removeTab(i)
    finally:
        _doc_switching[0] = False
    if _doc_list:
        _doc_switch(min(i, len(_doc_list) - 1))
    else:
        doc_pages.setCurrentIndex(0)


def _doc_close_requested():
    """Close the ACTIVE tab via its x: ask when dirty. Returns True when
    the document ended up closed (or none was open)."""
    if _doc is _DOC_CLOSED:
        doc_pages.setCurrentIndex(0)
        return True
    if _doc['dirty']:
        ans = pg.QtWidgets.QMessageBox.question(
            win, T('doc.close.title'), T('doc.close.q', name=_doc_tab_label(_doc)),
            pg.QtWidgets.QMessageBox.Save | pg.QtWidgets.QMessageBox.Discard
            | pg.QtWidgets.QMessageBox.Cancel,
            pg.QtWidgets.QMessageBox.Save)
        if ans == pg.QtWidgets.QMessageBox.Save:
            if not _doc_save():
                return False          # save-as dialog cancelled: stay open
            _doc_close_now()
            return True
        if ans == pg.QtWidgets.QMessageBox.Discard:
            _doc_close_now()
            return True
        return False
    _doc_close_now()
    return True


def _doc_close_tab(i):
    """Close tab i. A dirty BACKGROUND tab is switched to first so the
    standard confirmation applies; clean background tabs just vanish."""
    if not (0 <= i < len(_doc_list)):
        return True
    d = _doc_list[i]
    if d is not _doc:
        if not d['dirty']:
            _doc_switching[0] = True
            try:
                doc_tabs.removeTab(i)     # currentChanged -> guarded off
            finally:
                _doc_switching[0] = False
            _doc_list.pop(i)
            return True
        _doc_switch(i)
        if _doc is not d:
            return False
    return _doc_close_requested()


def _doc_new():
    """New analysis file: ADDS a tab. Existing documents stay open in
    theirs -- nothing to confirm."""
    _doc_open_untitled()


def _write_grab_csv(path):
    """Write the ACTIVE document to disk: v6 header (params included) +
    the flat event table (v5 + file_hash). Returns success; marks it
    clean on success."""
    if not grab_records:
        ans = pg.QtWidgets.QMessageBox.question(
            win, T('csv.exp.title'), T('doc.empty.save'),
            pg.QtWidgets.QMessageBox.Yes | pg.QtWidgets.QMessageBox.No,
            pg.QtWidgets.QMessageBox.No)
        if ans != pg.QtWidgets.QMessageBox.Yes:
            return False
    p = _grab_params()
    try:
        with open(path, 'w', newline='') as fh:
            fh.write('# heka-browser grab export v6 (flat events; detection'
                     ' params in header; file_hash = intrinsic .dat identity'
                     ' -- matching is path-independent; groups are a GUI'
                     ' selection tool and are not stored)\n'
                     '# units: t=s, y=native (per-row trace_yunit)\n'
                     '# join=True: t_* on the joined continuous axis;'
                     ' False: native per-sweep axis\n'
                     '# params: mode=%s k=%g t_min_ms=%g merge=%g head=%g'
                     ' smooth=%g duty=%g\n'
                     % (p['mode'], p['k'], p['t_min_ms'], p['merge'],
                        p['head_ms'], p['smooth_ms'], p['duty']))
            w = csv.writer(fh)
            w.writerow(_GRAB_CSV_COLUMNS)
            for rank, rec in enumerate(_grab_sorted_records(), 1):
                ref = rec.get('trace_ref')
                grp = _grab_groups.get(rec['gid']) \
                    if rec['gid'] is not None else None
                join = (grp['source_key'][1] if grp is not None
                        else bool(rec.get('join', False)))
                src_file = (grp['source_key'][0] if grp is not None
                            else rec.get('source_file', ''))
                # provenance was captured at grab time for grouped rows
                # (the loaded file may since have changed); groupless
                # rows carry their own
                sz, mt, fp = (
                    (grp.get('file_size', ''), grp.get('file_mtime', ''),
                     grp.get('file_hash') or '')
                    if grp is not None
                    else (rec.get('file_size', ''),
                          rec.get('file_mtime', ''),
                          rec.get('file_hash') or ''))
                w.writerow(
                    [rank, rec['t_start'], rec['t_end'], rec['dwell'],
                     rec['y_level'], rec['sigma'], join, src_file]
                    + (list(ref) if ref is not None
                       else ['', '', '', '', '', '', ''])
                    + [sz, fp, mt])
    except OSError as exc:
        pg.QtWidgets.QMessageBox.warning(
            win, T('csv.exp.title'), T('doc.savefail', err=exc))
        return False
    _doc['dirty'] = False
    _doc_sync_tab()
    return True


def _doc_save():
    if _doc is _DOC_CLOSED:
        return False
    if _doc['path'] is None:
        return _doc_saveas()
    return _write_grab_csv(_doc['path'])


def _doc_saveas():
    if _doc is _DOC_CLOSED:
        return False
    default = 'grab_events.csv'
    if _loaded_file:
        default = (os.path.splitext(os.path.basename(_loaded_file))[0]
                   + '_events.csv')
    start = os.path.join(_exp_dir[0] or settings.value('last_dir', ''),
                         default)
    path, _ = pg.QtWidgets.QFileDialog.getSaveFileName(
        win, T('csv.exp.title'), start, 'CSV (*.csv)')
    if not path:
        return False
    if not path.lower().endswith('.csv'):
        path += '.csv'
    if _write_grab_csv(path):
        _doc['path'] = path
        _doc.pop('name', None)
        _doc_sync_tab()
        return True
    return False


class _CloseGuard(pg.QtCore.QObject):
    """Window close with ANY dirty document: walk the dirty tabs (switch
    to each, ask Save/Discard/Cancel). Only a Cancel blocks the quit."""

    def eventFilter(self, obj, ev):
        if ev.type() == pg.QtCore.QEvent.Close:
            if any(d['dirty'] for d in _doc_list):
                ev.ignore()
                for i in [k for k, d in enumerate(_doc_list)
                          if d['dirty']]:
                    _doc_switch(i)
                    if not _doc_close_requested():
                        return True            # cancelled: keep running
                win.close()       # all clean/closed now: second pass
                return True
        return pg.QtCore.QObject.eventFilter(self, obj, ev)


win.installEventFilter(_CloseGuard())


# -- Analysis pipeline ------------------------------------------------------------

def amp_values(r0, r1, stride):
    """Raw samples of the displayed data inside a time region.

    With Join on the regions live on the continuous joined axis, so the
    values come from the cached joined raw arrays; otherwise per trace.
    x is monotonic everywhere -> searchsorted slice (never a full-axis
    boolean mask)."""
    pairs = ([_joined_display] if (_join_active and _joined_display is not None)
             else [(x, y) for x, y, _l, _t in last_data])
    vals = []
    for x, y in pairs:
        v = y[np.searchsorted(x, r0, 'left'):np.searchsorted(x, r1, 'right')]
        if stride > 1:
            v = v[::stride]
        if v.size:
            vals.append(v)
    return vals


def amp_recompute(full=True):
    """Rebuild the Amplitude histograms from the committed regions.

    All regions share one binning (edges from the pooled values) so the same
    physical level lands in the same bin everywhere. full=False computes on
    a strided subsample for live drags; release always recomputes in full.
    """
    pi = amp_plot.getPlotItem()
    pi.clear()
    _attach_ruler()
    if not (_amp_active() and amp_regions):
        amp_stats.setText('')
        _refresh_mode_hints()
        return
    _refresh_mode_hints()
    stride = 1 if full else max(1, total_points() // 200000)
    regs = [r.getRegion() for r in amp_regions]
    per_region = [amp_values(r0, r1, stride) for r0, r1 in regs]
    pooled = [v for vals in per_region for v in vals]
    if not pooled:
        amp_stats.setText(T('amp.nosamples'))
        return
    pooled = np.concatenate(pooled)
    if amp_follow.isChecked():
        rng = tuple(vb.viewRange()[1])
    else:
        rng = None
    nbins = 'fd' if amp_auto_bins.isChecked() else int(round(amp_bins.value()))
    edges = analysis.all_point_histogram(pooled, bins=nbins, value_range=rng)[0]

    lines = []
    maxc = 0.0
    for k, ((r0, r1), vals) in enumerate(zip(regs, per_region)):
        if not vals:
            continue
        v = np.concatenate(vals)
        _, counts, under, over = analysis.all_point_histogram(
            v, bins=edges)
        frac = counts * 100.0 / max(1, v.size)
        maxc = max(maxc, float(frac.max()))
        color = THEME['cycle'][k % len(THEME['cycle'])]
        # horizontal histogram: Y = current (NATIVE units -- the axis is
        # Y-linked to the main plot, which is also native), X = % of samples
        pi.addItem(pg.BarGraphItem(
            x0=np.zeros(len(frac)), x1=frac,
            y0=edges[:-1], y1=edges[1:],
            brush=_tint(color, 150), pen=pg.mkPen(color, width=1)))
        p1, p99 = np.percentile(v, [1, 99])
        lines.append(
            '<span style="color:%s">#%d: N=%d  mean=%s  σ=%s  '
            'p1..p99=%s .. %s  out-of-range=%d</span>'
            % (color, k, v.size, fmt_si(float(v.mean()), cur_yunit),
               fmt_si(float(v.std()), cur_yunit), fmt_si(float(p1), cur_yunit),
               fmt_si(float(p99), cur_yunit), under + over))
    # Y view mirrors the main plot manually (_amp_follow_main_y -- see the
    # comment there for why not setYLink); only X (% of samples) is set
    # here. The left axis / bottom label are configured at construction
    # and in replot() -- never here, or the column layout would shift the
    # moment the first histogram lands (fixedWidth reserves the ticks).
    if maxc > 0:
        pi.getViewBox().setXRange(0, maxc * 1.1, padding=0)
    _amp_follow_main_y()
    amp_stats.setText('<br>'.join(lines))
    _update_ruler()


def amp_preview():
    amp_recompute(full=False)


def clear_analysis():
    """Clear button: drop the Amp regions (grab records are an analysis
    logbook and stay)."""
    clear_amp_regions()
    amp_recompute()


# --- Activation: the last-clicked analysis area owns the Shift+drag gesture --
#   Clicking anywhere in the Amplitude column arms amplitude mode (Shift+
#   drag on the main plot = horizontal time region); clicking anywhere in
#   the Event panel arms event mode (Shift+drag = XY detection rectangle).
#   Clicks in the main plot / left column never change the mode -- the plot
#   is a shared canvas. Folding the amp column disarms amplitude mode and
#   deletes its regions; folding the Event panel freezes its rectangles.
_ui_mode = ['event']


def _amp_active():
    """Amplitude mode armed: amp column clicked last, column open."""
    return _ui_mode[0] == 'amp' and not amp_col.is_collapsed()


# activation styles: armed = accent-blue pill, idle = quiet grey; same
# padding on both so switching modes never jiggles the layout
_HINT_ON = ('color:%s; background:%s; border-radius:4px; padding:2px 6px;'
            ' font-weight:bold;' % (THEME['accent'], THEME['accent_tint']))
_HINT_OFF = 'color:#999; padding:2px 6px;'
_HINT_PAD = 'padding:2px 6px;'
_HEADER_QSS = ('QToolButton { border: none; text-align: left; padding: 2px;'
               ' font-weight: bold; color: %s; }')


def _mode_header(btn, on):
    """Section-header colour mark: the fold button of the ARMED analysis
    area renders in accent blue (mode stays visible even when the panel
    is tall and its hint row is scrolled out of sight)."""
    btn.setStyleSheet(_HEADER_QSS % (THEME['accent'] if on else THEME['fg']))


def _refresh_mode_hints():
    """Update the activation hints AND the section headers: the armed
    analysis area is announced in accent blue (hint pill + fold-button
    colour), the other one stays quiet grey."""
    amp_on = _amp_active()
    if amp_on and amp_regions:
        amp_hint.setText('')
        amp_hint.setToolTip('')
        amp_hint.setStyleSheet(_HINT_PAD)
    else:
        amp_hint.setText(T('amp.hint') if amp_on else T('amp.hint.off'))
        amp_hint.setToolTip(T('amp.tip.hint'))
        amp_hint.setStyleSheet(_HINT_ON if amp_on else _HINT_OFF)
    evt_on = _grab_active()
    grab_hint.setText(T('grab.hint') if evt_on else T('grab.hint.off'))
    grab_hint.setStyleSheet(_HINT_ON if evt_on else _HINT_OFF)
    _mode_header(amp_col.btn, amp_on)
    _mode_header(sec_events.btn, evt_on)


def _set_ui_mode(mode):
    was = _ui_mode[0]
    if was == mode:
        return
    _ui_mode[0] = mode
    if was == 'amp':
        clear_amp_regions()             # 切走即清除全部区域（用户要求）
    amp_recompute()
    _grab_roi_set_interactive(_grab_active())   # rects freeze outside event mode
    _grab_refresh_views()
    _refresh_mode_hints()


def _amp_col_toggled(*_):
    """Amp column fold/unfold: folding disarms amplitude (the mode falls
    back to event) and deletes its regions."""
    if amp_col.is_collapsed():
        if _ui_mode[0] == 'amp':
            _ui_mode[0] = 'event'
        clear_amp_regions()
        amp_recompute()
        _grab_roi_set_interactive(_grab_active())
        _grab_refresh_views()
    _refresh_mode_hints()


def _event_panel_toggled(*_):
    """Event panel fold/unfold: folding freezes its rectangles and clears
    the green highlights (the records themselves stay)."""
    _grab_roi_set_interactive(_grab_active())
    _grab_refresh_views()
    _refresh_mode_hints()


def _clear_layout(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget() is not None:
            it.widget().deleteLater()


def _refresh_region_list():
    """One row per committed Amp region: color chip, time span, remove ×."""
    _clear_layout(amp_list_lay)
    for k, r in enumerate(amp_regions):
        color = THEME['cycle'][k % len(THEME['cycle'])]
        row = pg.QtWidgets.QWidget()
        rl = pg.QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(2, 0, 2, 0)
        rl.setSpacing(6)
        chip = pg.QtWidgets.QLabel()
        chip.setFixedSize(10, 10)
        chip.setStyleSheet('background:%s; border-radius:3px;' % color)
        lo, hi = r.getRegion()
        text = pg.QtWidgets.QLabel('#%d   %.6g – %.6g %s'
                                   % (k, lo, hi, cur_xunit))
        text.setSizePolicy(pg.QtWidgets.QSizePolicy.Ignored,
                           pg.QtWidgets.QSizePolicy.Preferred)  # narrow column
        text.setToolTip(text.text())
        rm = pg.QtWidgets.QPushButton('×')
        rm.setFlat(True)
        rm.setFixedWidth(18)
        rm.clicked.connect(lambda _=False, r=r: _remove_region(r))
        rl.addWidget(chip)
        rl.addWidget(text)
        rl.addStretch(1)
        rl.addWidget(rm)
        amp_list_lay.addWidget(row)
    amp_list_lay.addStretch(1)


def _remove_region(r):
    if r.scene() is not None:
        plot.getPlotItem().removeItem(r)
    if r in amp_regions:
        amp_regions.remove(r)
    _refresh_region_list()
    amp_recompute()


# -- SI display-unit scale shared by the Amp ruler and the Grab readouts -------

_yunit_cache = None   # (_data_stamp, factor, si_prefix)


def _yunit_scale():
    """(factor, prefix) for Y-value display: an SI prefix chosen so the
    numbers are readable (an A-native trace is shown in pA)."""
    global _yunit_cache
    if _yunit_cache is None or _yunit_cache[0] != _data_stamp:
        e, prefix = 0, ''
        if last_data:
            y0 = last_data[0][1]
            ref = float(np.nanmedian(np.abs(y0[:min(100000, len(y0))])))
            if ref > 0 and np.isfinite(ref):
                for _ in range(9):
                    r = abs(ref) / 10.0 ** e
                    if 1 <= r < 1000:
                        break
                    e += 3 if r >= 1000 else -3
                f = 10.0 ** e
                prefix = {-12: 'p', -9: 'n', -6: 'u', -3: 'm',
                          0: '', 3: 'k', 6: 'M'}.get(e, '')
            else:
                f = 1.0
        else:
            f = 1.0
        _yunit_cache = (_data_stamp, f, prefix)
    return _yunit_cache[1], _yunit_cache[2]


# -- Grab tab: scoped detection, one curated event per row ------------------------
#   Shift+drag an XY rectangle in the main plot (X = time scope, Y = the
#   event band). Detection runs inside it and EVERY detected event becomes
#   ONE row in the record list -- the user's unit of analysis (dwell is the
#   quantity of interest, one curated event per row). Rows produced by the
#   same rectangle form a GROUP: they share the rectangle's colour, bounds,
#   params snapshot and source annotation.
#
#   The rectangle is a pg.ROI: interior drag translates, the four edge
#   handles resize; a live drag previews the event count (150 ms debounce,
#   strided), release re-detects in full with the CURRENT tab params and
#   REPLACES the whole group's rows (an edit re-scoops: rows the user had
#   deleted manually come back -- documented resurrection semantics).
#   Grabs that detect nothing keep their rectangle so the user can adjust
#   the edges until the event is complete (boundary events are discarded:
#   an event must fall entirely inside the rectangle).
#
#   Records/groups survive tree/file switches (the list is an analysis
#   logbook); rectangles and the detail view only re-attach while the exact
#   source data (file + join state + trace labels) is displayed again.

grab_plot.setDownsampling(auto=True, mode='peak')
grab_plot.setClipToView(True)

grab_records = []        # ONE dict per EVENT, creation order
_grab_groups = {}        # group id -> group dict (rectangle + params)
_grab_rects = {}         # group id -> pg.ROI in the main plot
_grab_items = {}         # event id -> QTreeWidgetItem in grab_tree
_grab_selected = None    # EVENT id shown in the detail view
_grab_focus_gid = None   # group shown instead when it has no rows (yet)
_grab_overlays = []      # green highlight curves in the MAIN plot
_grab_live_gid = [None]  # group being live-dragged (debounce target)
_grab_next_eid = [1]
_grab_next_gid = [1]
_GRAB_MAX_EVENTS = 500   # refuse to row-ify more events than this

_GRAB_DETAIL_YSPAN = 2.0    # detail-view uniform Y width = this x mean
                             # per-event region span (region = displayed
                             # data min-max inside the event's X window)


def _grab_active():
    """Event mode armed: event panel clicked last, panel expanded."""
    return _ui_mode[0] == 'event' and not sec_events.is_collapsed()


def _grab_source_key():
    """Identity of the data a group was grabbed from: file + join state +
    the displayed trace labels."""
    return (_loaded_file, _join_active,
            tuple(sorted(label for _, _, label, _ in last_data)))


def _grab_grp_matches(grp):
    """Group belongs to the displayed data: exact source key, or the
    intrinsic file hash when both sides have one (the .dat was moved /
    renamed / re-located after the grab -- same content, new path)."""
    key = _grab_source_key()
    if grp['source_key'] == key:
        return True
    fp = grp.get('file_hash')
    return (bool(fp) and bool(_loaded_fp) and fp == _loaded_fp
            and grp['source_key'][1:] == key[1:])


def _grab_rec_source_matches(rec):
    """Row is live on the current display. Grouped rows ride their
    group's exact source key; GROUPLESS (CSV v3 import) rows attach per
    event -- live iff their own trace is displayed under the row's join
    state (see _grab_ref_display_pos)."""
    if rec['gid'] is None:
        return _grab_ref_display_pos(rec) is not None
    grp = _grab_groups.get(rec['gid'])
    return grp is not None and _grab_grp_matches(grp)


def _grab_params():
    return dict(mode=grab_mode.currentText(), k=grab_k.value(),
                t_min_ms=grab_tmin.value(), merge=grab_merge.value(),
                head_ms=grab_head.value(), smooth_ms=grab_smooth.value(),
                duty=grab_duty.value())


def _grab_grp_by_id(gid):
    return _grab_groups.get(gid)


def _grab_sorted_records():
    """Records in CANONICAL order: global by t_start, ties by segment.
    The export and the default tree order use this."""
    return sorted(grab_records, key=lambda r: (r['t_start'], r['i_seg']))


# Header-click sorting: cycle asc -> desc -> default per column. The sort
# compares RAW record values (never the display text -- '9.99 ms' would
# string-sort after '10.0 ms'); the # column always renumbers to the
# CURRENT display order. The export stays in the canonical t_start order.
_GRAB_SORT_FIELDS = {1: 't_start', 2: 'dwell', 3: 'y_level', 4: 'sigma'}
_grab_sort_col = [None]        # None = default (canonical t_start asc)
_grab_sort_desc = [False]


def _grab_display_order():
    recs = _grab_sorted_records()
    key = _GRAB_SORT_FIELDS.get(_grab_sort_col[0])
    if key is None:
        return recs
    return sorted(recs, key=lambda r: r[key], reverse=_grab_sort_desc[0])


def _grab_header_clicked(col):
    if col not in _GRAB_SORT_FIELDS:
        return
    if _grab_sort_col[0] == col and not _grab_sort_desc[0]:
        _grab_sort_desc[0] = True                 # asc -> desc
    elif _grab_sort_col[0] == col:
        _grab_sort_col[0] = None                  # desc -> default
        _grab_sort_desc[0] = False
    else:
        _grab_sort_col[0] = col                   # new column -> asc
        _grab_sort_desc[0] = False
    hdr = grab_tree.header()
    if _grab_sort_col[0] is None:
        hdr.setSortIndicatorShown(False)
    else:
        hdr.setSortIndicatorShown(True)
        hdr.setSortIndicator(_grab_sort_col[0],
                             pg.QtCore.Qt.DescendingOrder
                             if _grab_sort_desc[0]
                             else pg.QtCore.Qt.AscendingOrder)
    _refresh_grab_list()


def _grab_group_ranks():
    """gid -> display rank (1-based, groups ordered by span start x0).
    Internal ids never surface in user-visible text."""
    ranks = {}
    for i, gid in enumerate(sorted(_grab_groups, key=lambda g: _grab_groups[g]['x0'])):
        ranks[gid] = i + 1
    return ranks


def _grab_rec_by_id(rid):
    for rec in grab_records:
        if rec['id'] == rid:
            return rec
    return None


def _grab_new_group(x0, x1, y0, y1):
    gid = _grab_next_gid[0]
    _grab_next_gid[0] += 1
    try:
        _st = os.stat(_loaded_file)
        sz, mt = _st.st_size, _st.st_mtime
    except (OSError, TypeError):
        sz, mt = '', ''
    return dict(id=gid, color=THEME['cycle'][gid % len(THEME['cycle'])],
                x0=x0, x1=x1, y0=y0, y1=y1,
                source_key=_grab_source_key(), params=_grab_params(),
                file_hash=_loaded_fp, file_size=sz, file_mtime=mt,
                events=np.empty(0, analysis.EVENT_DTYPE),
                stats=None, error=None, ev_refs=[])


def _make_grab_roi(grp):
    """Committed grab rectangle: edge handles resize, interior drag
    translates (rotatable/resizable off so Shift+drag falls through to the
    ViewBox and draws a NEW rectangle); translucent fill follows the size."""
    roi = pg.ROI(pg.Point(grp['x0'], grp['y0']),
                 pg.Point(grp['x1'] - grp['x0'], grp['y1'] - grp['y0']),
                 movable=True, rotatable=False, resizable=False,
                 pen=pg.mkPen(grp['color'], width=1),
                 hoverPen=pg.mkPen(grp['color'], width=2),
                 handlePen=pg.mkPen(grp['color']),
                 handleHoverPen=pg.mkPen(THEME['fg']))
    # IN FRONT of the curves (z=0): the edge handles must stay visible and
    # grabbable over the trace lines; the fill is translucent anyway
    roi.setZValue(10)
    roi.grp_id = grp['id']
    roi.rec_color = grp['color']
    for _hp, _hc in (([0, 0.5], [1, 0.5]), ([1, 0.5], [0, 0.5]),
                     ([0.5, 0], [0.5, 1]), ([0.5, 1], [0.5, 0])):
        roi.addScaleHandle(_hp, _hc)
    fill = pg.QtWidgets.QGraphicsRectItem(roi)
    fill.setBrush(_tint(grp['color'], 40))
    fill.setPen(pg.mkPen(None))
    fill.setAcceptedMouseButtons(pg.QtCore.Qt.NoButton)
    fill.setAcceptHoverEvents(False)

    def _sync_fill(*_):
        fill.setRect(pg.QtCore.QRectF(
            0, 0, roi.state['size'][0], roi.state['size'][1]).normalized())
    _sync_fill()
    roi.sigRegionChanged.connect(_sync_fill)
    roi.sigRegionChanged.connect(lambda _r, _g=grp: _grab_roi_changed(_g))
    roi.sigRegionChangeStarted.connect(
        lambda _r, _g=grp: _grab_roi_touched(_g))
    roi.sigRegionChangeFinished.connect(
        lambda _r, _g=grp: _grab_roi_commit(_g))
    return roi


def _grab_roi_touched(grp):
    """Press on a rectangle SELECTS it (thick pen): Ctrl+Delete's
    rectangle target is the last-touched rectangle. Fires only on real
    user grabs -- programmatic setPos emits Changed/Finished, never
    Started -- so no _grab_syncing guard is needed."""
    global _grab_focus_gid
    if _grab_focus_gid != grp['id']:
        _grab_focus_gid = grp['id']
        _grab_apply_selection_style()


def _grab_roi_set_interactive(on):
    """Rectangle interaction only while the Grab tab is active: hidden
    handles receive no events and translatable=off lets drags fall through
    to panning."""
    for roi in _grab_rects.values():
        if roi.scene() is None:
            continue
        roi.translatable = on
        for h in roi.handles:
            h['item'].setVisible(on)


def add_grab_items():
    """Re-attach grab rectangles after plot.clear(): only groups whose data
    is still displayed come back (the others stay list-only)."""
    pi = plot.getPlotItem()
    for grp in _grab_groups.values():
        if not _grab_grp_matches(grp):
            continue
        roi = _grab_rects.get(grp['id'])
        if roi is None:
            roi = _make_grab_roi(grp)
            _grab_rects[grp['id']] = roi
        if roi.scene() is None:
            pi.addItem(roi, ignoreBounds=True)
    _grab_roi_set_interactive(_grab_active())


def grab_drag_update(x0, x1, y0, y1):
    """Shift+drag live preview: a dashed rubber-band rectangle (guarded, so
    the programmatic setPos/setSize triggers no recompute)."""
    global _grab_pending, _grab_syncing
    if _grab_pending is None:
        r = pg.ROI(pg.Point(x0, y0), pg.Point(x1 - x0, y1 - y0),
                   movable=False, rotatable=False, resizable=False,
                   pen=pg.mkPen(THEME['band'], width=1,
                                style=pg.QtCore.Qt.DashLine))
        r.setZValue(10)
        fill = pg.QtWidgets.QGraphicsRectItem(r)
        fill.setBrush(_tint(THEME['band'], 40))
        fill.setPen(pg.mkPen(None))
        fill.setAcceptedMouseButtons(pg.QtCore.Qt.NoButton)
        fill.setAcceptHoverEvents(False)
        r.sigRegionChanged.connect(
            lambda: fill.setRect(pg.QtCore.QRectF(
                0, 0, r.state['size'][0], r.state['size'][1]).normalized()))
        fill.setRect(pg.QtCore.QRectF(0, 0, x1 - x0, y1 - y0))
        plot.getPlotItem().addItem(r, ignoreBounds=True)
        _grab_pending = r
        return
    _grab_syncing = True
    try:
        _grab_pending.setPos((x0, y0), finish=False)
        _grab_pending.setSize((x1 - x0, y1 - y0), finish=False)
    finally:
        _grab_syncing = False


def grab_drag_finish(x0, x1, y0, y1):
    """Commit the drawn rectangle (X extent <=1% of the view width or Y
    extent <=3% of the view height counts as an accidental drag): create
    the group, detect, and give every event its own row. Zero-event and
    error grabs KEEP the rectangle (adjust its edges until the event is
    complete); a grab catching more than _GRAB_MAX_EVENTS events is
    refused (the list would be unmanageable)."""
    global _grab_pending, _grab_focus_gid
    if _grab_pending is not None:
        if _grab_pending.scene() is not None:
            plot.getPlotItem().removeItem(_grab_pending)
        _grab_pending = None
    if not last_data:
        return
    xr = vb.viewRange()[0]
    yr = vb.viewRange()[1]
    if ((x1 - x0) <= 0.01 * (xr[1] - xr[0])
            or (y1 - y0) <= 0.03 * (yr[1] - yr[0])):
        return
    if _doc is _DOC_CLOSED:
        _doc_open_untitled()     # the first committed grab births the doc
    grp = _grab_new_group(x0, x1, y0, y1)
    _grab_groups[grp['id']] = grp
    roi = _make_grab_roi(grp)
    _grab_rects[grp['id']] = roi
    plot.getPlotItem().addItem(roi, ignoreBounds=True)
    _grab_roi_set_interactive(_grab_active())
    _grab_detect(grp)
    n = len(grp['events'])
    if n > _GRAB_MAX_EVENTS:
        _grab_drop_group(grp['id'])
        grab_detail_lbl.setToolTip('')
        grab_detail_lbl.setText(
            T('amp.over.commit', c=THEME['A'], n=n, cap=_GRAB_MAX_EVENTS))
        _grab_show_overlays()
        return
    if grp['error'] or n == 0:
        # keep the rectangle: the user adjusts its edges until the event is
        # complete (or fixes the band / params); the focus group renders
        # the guidance in the detail view
        if _grab_selected is not None:
            _grab_select(None)
        _grab_focus_gid = grp['id']
        _grab_refresh_views()
        return
    _grab_focus_gid = None
    _grab_sync_group(grp)
    _grab_select(grp['_first_eid'])
    _refresh_grab_list()


def _grab_drop_group(gid):
    """Remove a group: its rectangle and (by construction) all its rows."""
    global _grab_focus_gid
    roi = _grab_rects.pop(gid, None)
    if roi is not None and roi.scene() is not None:
        plot.getPlotItem().removeItem(roi)
    _grab_groups.pop(gid, None)
    if _grab_focus_gid == gid:
        _grab_focus_gid = None


def _grab_detect(grp, full=True):
    """Scoped detection for one group against the data it was grabbed from
    (only callable while that data is displayed). The rectangle's Y span IS
    the band (lo/hi); ValueError lands in grp['error']. Fills
    grp['events'/'stats']; does NOT touch the rows (that is
    _grab_sync_group)."""
    p = grp['params']
    segs = analysis_segments(1, head_s=p['head_ms'] * 1e-3,
                             smooth_ms=p['smooth_ms'])
    total = sum(len(t) for t, _ in segs)
    stride = 1 if full else max(1, total // 200000)
    segs = analysis.slice_segments(segs, grp['x0'], grp['x1'], stride)
    grp['error'] = None
    try:
        res = analysis.detect_events_segments(
            segs, mode=p['mode'], lo=grp['y0'], hi=grp['y1'], h=None,
            k=p['k'], t_min=_tmin_points(p['t_min_ms'], p['smooth_ms']),
            merge_gap=p['merge'], duty_min=p['duty'])
    except ValueError as exc:
        grp['error'] = str(exc)
        grp['events'] = np.empty(0, analysis.EVENT_DTYPE)
        grp['stats'] = None
        grp['ev_refs'] = []
        return
    grp['events'] = (res.events.copy() if len(res.events)
                     else np.empty(0, analysis.EVENT_DTYPE))
    grp['ev_refs'] = _grab_ev_refs(grp)
    dur = sum(float(t[-1] - t[0]) for t, _ in segs if len(t) > 1)
    grp['stats'] = dict(n=len(grp['events']), dur=dur, h=res.h,
                        sigma=res.sigma,
                        boundary=res.boundary_discarded,
                        duty_disc=res.duty_discarded)


def _grab_trace_ref(index, trace):
    """Fingerprint of a source trace: tree path + header shape (sample
    count / interval / y unit). Header-only -- no data read -- so the same
    fingerprint can be matched against ANY trace of a bundle on load."""
    return (int(index[0]), int(index[1]), int(index[2]), int(index[3]),
            int(trace.DataPoints), float(trace.XInterval), trace.YUnit)


def _kept_seg_indices(grp, segs):
    """Indices of segments holding >=1 sample inside grp bounds (the
    display side MUST use the same keep-rule as detection: only
    non-empty segments keep their i_seg slot)."""
    return [k for k, (x, _y) in enumerate(segs)
            if len(x) and np.searchsorted(x, grp['x1'], 'right')
            > np.searchsorted(x, grp['x0'], 'left')]


def _grab_ev_refs(grp):
    """Per-event source-trace refs aligned with grp['events'] (None when
    the mapping cannot be established). Must run while the group's source
    data is still displayed.

    Non-join: i_seg indexes the non-empty slices in last_data order --
    replay the same keep-rule (span must contain a prepped sample).
    Join: one concatenated axis; the per-trace accumulation advances by
    FULL sweep durations, so the display seams locate each event's sweep
    (side='left': an event starting exactly at a seam belongs to the
    trace ENDING there, whose tail events it is)."""
    evs = grp['events']
    refs = [None] * len(evs)
    if not len(evs):
        return refs
    p = grp['params']
    prepped = _prepped(p['head_ms'] * 1e-3, p['smooth_ms'])
    if not prepped or len(prepped) > len(last_data_idx):
        return refs
    if _join_active:
        seams = _join_t_starts(prepped)[1:]
        for j, t0 in enumerate(evs['t_start']):
            k = int(np.searchsorted(seams, float(t0), side='left'))
            if 0 <= k < len(prepped):
                refs[j] = _grab_trace_ref(last_data_idx[k], prepped[k][3])
        return refs
    kept = _kept_seg_indices(grp, [(p[0], p[1]) for p in prepped])
    for j, seg_i in enumerate(evs['i_seg']):
        if 0 <= int(seg_i) < len(kept):
            k = kept[int(seg_i)]
            refs[j] = _grab_trace_ref(last_data_idx[k], prepped[k][3])
    return refs


def _grab_raw_segs_for(grp):
    """RAW (unsmoothed) segments of the group's span in DETECTION order
    (non-empty per trace; single joined seg with Join on). Used for the
    per-event noise sigma -- the smoothed detection arrays would
    underestimate the noise. Monotonic axes -> searchsorted slices, never
    full-axis boolean masks (the live rectangle-drag preview calls this
    on ~1e7-sample joined axes)."""
    x0, x1 = grp['x0'], grp['x1']
    if _join_active and _joined_display is not None:
        xs, ys = _joined_display
        i0 = int(np.searchsorted(xs, x0, side='left'))
        i1 = int(np.searchsorted(xs, x1, side='right'))
        return [(ys[i0:i1], xs[i0:i1])] if i1 > i0 else []
    segs = []
    for x, y, label, trace in last_data:
        i0 = int(np.searchsorted(x, x0, side='left'))
        i1 = int(np.searchsorted(x, x1, side='right'))
        if i1 > i0:
            segs.append((y[i0:i1], x[i0:i1]))
    return segs


_NOISE_PREVIEW_CAP = 100_000   # per-segment sample cap for the ADVISORY
# rect-level envelope below -- percentile sorts on a full joined span
# (~1e7 samples) take seconds each and were the rectangle-drag lag


def _grab_segment_noise(grp, raw_segs):
    """RECT-level baseline envelope (5-95 percentile half-width of the RAW
    signal around its LOCAL level) -- only used for the row-less group
    guidance (0-event tuning / live preview), where there is no event yet
    and the question is 'is this stretch's baseline clean enough to
    bother'. Rows themselves carry the per-EVENT envelope
    (_grab_event_noise); same estimator everywhere. Native y units.
    ADVISORY ONLY: each segment is stride-subsampled to
    _NOISE_PREVIEW_CAP points first (the guidance line does not need
    full resolution; the exact per-event numbers at commit run on
    dwell-sized crops and are unaffected)."""
    ev = grp['events']
    sigmas = []
    for k, (y, x) in enumerate(raw_segs):
        if len(y) > _NOISE_PREVIEW_CAP:
            _stride = -(-len(y) // _NOISE_PREVIEW_CAP)   # ceil division
            y, x = y[::_stride], x[::_stride]
        evs = [(float(a), float(b), float(l)) for a, b, g, l in
               zip(ev['t_start'], ev['t_end'], ev['i_seg'], ev['y_level'])
               if g == k]
        mask = np.zeros(len(x), dtype=bool)
        for t0, t1, _ in evs:
            mask |= (x >= t0) & (x <= t1)
        base = (float(np.median(y[~mask])) if (~mask).any()
                else float(np.median(y)))
        local = np.full(len(y), base)
        for t0, t1, lev in evs:
            local[(x >= t0) & (x <= t1)] = lev
        resid = y - local
        resid = resid[np.isfinite(resid)]
        if resid.size:
            sigmas.append(float(np.percentile(resid, 95)
                                - np.percentile(resid, 5)) / 2.0)
        else:
            sigmas.append(0.0)
    return sigmas


def _grab_event_noise(ev, raw_segs):
    """Per-EVENT noise: the 5-95 PERCENTILE ENVELOPE half-width of the RAW
    samples inside the event's own span around the event's own level --
    '90% of the samples stay within level +- this'. Unlike the MAD (which
    the user rejected twice: the robust median scatter deliberately throws
    away exactly the spikes/junk that differ between events, so it came
    out identical everywhere), the envelope GROWS with spike chains and
    wobble; a lone sub-5%-of-samples poke is still discounted. Native y
    units."""
    k = int(ev['i_seg'])
    if not (0 <= k < len(raw_segs)):
        return 0.0
    y, x = raw_segs[k]
    i0 = np.searchsorted(x, ev['t_start'], side='left')
    i1 = np.searchsorted(x, ev['t_end'], side='right')
    d = y[i0:i1] - float(ev['y_level'])
    d = d[np.isfinite(d)]
    if d.size < 3:
        return 0.0
    return float(np.percentile(d, 95) - np.percentile(d, 5)) / 2.0


def _grab_sync_group(grp):
    """WHOLE-GROUP REPLACEMENT: drop the group's existing event rows and
    create one fresh row per detected event (the resurrection semantics of
    a rectangle edit). Marks grp['_first_eid'] for selection."""
    global _grab_focus_gid, _grab_selected
    raw_segs = _grab_raw_segs_for(grp)
    refs = grp.get('ev_refs') or []
    grab_records[:] = [r for r in grab_records if r['gid'] != grp['id']]
    first = None
    for j, e in enumerate(grp['events']):
        eid = _grab_next_eid[0]
        _grab_next_eid[0] += 1
        grab_records.append(dict(
            id=eid, gid=grp['id'], color=grp['color'],
            t_start=float(e['t_start']), t_end=float(e['t_end']),
            dwell=float(e['dwell']), y_level=float(e['y_level']),
            i_seg=int(e['i_seg']),
            sigma=_grab_event_noise(e, raw_segs),
            trace_ref=(refs[j] if j < len(refs) else None)))
        first = first if first is not None else eid
    grp['_first_eid'] = first
    _doc_touch()
    if first is None:
        _grab_focus_gid = grp['id']       # rows vanished: focus the group
    else:
        _grab_focus_gid = None
    if _grab_selected is not None:
        sel = _grab_rec_by_id(_grab_selected)
        if sel is None or sel['gid'] == grp['id']:
            _grab_selected = first        # reselect within the replaced group


_grab_preview_timer = pg.QtCore.QTimer()
_grab_preview_timer.setSingleShot(True)
_grab_preview_timer.setInterval(150)


def _grab_roi_changed(grp):
    """Real user drag of a rectangle (programmatic moves guarded): update
    bounds, focus the dragged group, then a debounced strided preview of
    the event COUNT (rows are only replaced on release)."""
    global _grab_focus_gid
    if _grab_syncing:
        return
    roi = _grab_rects.get(grp['id'])
    if roi is None:
        return
    px, py = roi.pos()
    w, h = roi.size()
    grp['x0'], grp['x1'] = float(min(px, px + w)), float(max(px, px + w))
    grp['y0'], grp['y1'] = float(min(py, py + h)), float(max(py, py + h))
    if _grab_selected is not None:
        _grab_select(None)          # preview follows the dragged group
    _grab_focus_gid = grp['id']
    _grab_live_gid[0] = grp['id']
    _grab_preview_timer.start()


def _grab_live_preview():
    """Debounced strided re-detection while a rectangle is being dragged:
    preview the event count in the stats line only (no row churn)."""
    grp = _grab_grp_by_id(_grab_live_gid[0])
    if grp is None or not _grab_grp_matches(grp):
        return
    _grab_detect(grp, full=False)
    _grab_show_selected()


_grab_preview_timer.timeout.connect(_grab_live_preview)


def _grab_roi_commit(grp):
    """Drag finished: re-detect in full with the CURRENT tab params and
    replace the whole group's rows (deleted rows come back -- documented)."""
    if _grab_syncing:
        return
    _grab_preview_timer.stop()
    _grab_live_gid[0] = None
    grp['params'] = _grab_params()
    _grab_detect(grp)
    n = len(grp['events'])
    if n > _GRAB_MAX_EVENTS:
        grab_detail_lbl.setToolTip('')
        grab_detail_lbl.setText(
            T('amp.over.edit', c=THEME['A'], n=n, cap=_GRAB_MAX_EVENTS))
        return
    _grab_sync_group(grp)
    if grp['_first_eid'] is not None:
        _grab_select(grp['_first_eid'])
    _refresh_grab_list()
    _grab_refresh_views()


def _grab_crop(x, y, t0, t1):
    """Samples with t0 <= t <= t1 as (x, y) slices, or None -- O(log n)
    via searchsorted. Green-highlight data is ALWAYS cropped through
    this: never wrap full-segment arrays (with or without a NaN mask) in
    an event curve -- a highlight that renders rectangle-length paths
    per paint is what made [显示全部] lag with many groups."""
    i0 = np.searchsorted(x, t0, side='left')
    i1 = np.searchsorted(x, t1, side='right')
    return (x[i0:i1], y[i0:i1]) if i1 > i0 else None


def _grab_event_trace_pos(grp, i_seg):
    """last_data position of the trace a detection i_seg refers to.
    slice_segments drops empty segments, so i_seg numbers the KEPT ones:
    replay the keep-rule (>=1 sample inside the group span) against the
    cached prepped segments, which align 1:1 with last_data order."""
    p = grp['params']
    segs = analysis_segments(1, head_s=p['head_ms'] * 1e-3,
                             smooth_ms=p['smooth_ms'])
    kept = _kept_seg_indices(grp, segs)
    return kept[int(i_seg)] if 0 <= int(i_seg) < len(kept) else None


def _grab_group_span_curves(grp, spans=None):
    """CROPPED green-highlight data for a group's events (default: all of
    them): per span, searchsorted-slice the prepped segment its i_seg
    maps onto. Event-sized arrays by construction, so the no-downsample /
    no-clip highlight curves stay cheap however long the segments are."""
    p = grp['params']
    segs = analysis_segments(1, head_s=p['head_ms'] * 1e-3,
                             smooth_ms=p['smooth_ms'])
    kept = _kept_seg_indices(grp, segs)
    out = []
    for t0, t1, g in (_grab_group_spans(grp) if spans is None else spans):
        k = kept[int(g)] if 0 <= int(g) < len(kept) else None
        if k is None:
            continue
        c = _grab_crop(segs[k][0], segs[k][1], t0, t1)
        if c is not None:
            out.append(c)
    return out


# Resolution of saved trace fingerprints against the loaded bundle,
# memoised per data stamp (the walk + header scan are pure bundle state;
# _data_stamp bumps on every replot, i.e. on every load/tree change).
_grab_res_stamp = [-1]
_grab_res_pool = []
_grab_res_map = {}


def _grab_resolve_ref(ref):
    """Resolve one saved fingerprint against the loaded bundle:
    (index tuple or None, 'path'|'content'|'content?'|None)."""
    if ref is None:
        return None, None
    if _grab_res_stamp[0] != _data_stamp:
        _grab_res_stamp[0] = _data_stamp
        _grab_res_pool[:] = _walk_bundle_traces()
        _grab_res_map.clear()
    if ref not in _grab_res_map:
        _grab_res_map[ref] = _import_match_ref(ref, _grab_res_pool)
    return _grab_res_map[ref]


def _grab_row_file_ok(rec):
    """A groupless row may only attach to the loaded file when that file
    IS the row's saved source -- intrinsic hash when available (v6,
    path-free), else path / basename+size -- so pure header coincidences
    must not attach rows to unrelated files."""
    return _import_file_matches(rec.get('source_file', ''),
                                rec.get('file_size'),
                                rec.get('file_hash'))


def _grab_ref_display_pos(rec):
    """last_data position of a groupless row's source trace, or None when
    the row cannot attach: source file mismatch, fingerprint unresolved,
    join state differs (t_start axis semantics), or trace not shown."""
    ref = rec.get('trace_ref')
    if ref is None or not _grab_row_file_ok(rec):
        return None
    if bool(rec.get('join', False)) != _join_active:
        return None
    idx, _how = _grab_resolve_ref(ref)
    if idx is None:
        return None
    try:
        return last_data_idx.index(idx)
    except ValueError:
        return None


def _grab_group_spans(grp):
    """(t0, t1, i_seg) per detected event of the group's last detection."""
    ev = grp['events']
    return [(float(a), float(b), int(g))
            for a, b, g in zip(ev['t_start'], ev['t_end'], ev['i_seg'])]


def _peak_decimate(x, y, cap):
    """Envelope-preserving decimation to <= cap OUTPUT samples: per bin
    the min and max y in x order (the same idea as pyqtgraph's peak
    downsampling, done ONCE here at creation so per-frame rendering is
    just the points). Spikes survive -- the envelope touches every local
    extreme."""
    bins = max(1, cap // 2)                  # each bin emits min+max (2 pts)
    w = -(-len(x) // bins)                   # ceil: samples per bin
    if w <= 1:
        return x, y
    n = len(x) // w
    xb = x[:n * w].reshape(n, w)
    yb = y[:n * w].reshape(n, w)
    rows = np.arange(n)
    imin = yb.argmin(axis=1)
    imax = yb.argmax(axis=1)
    lo = yb[rows, np.minimum(imin, imax)]
    hi = yb[rows, np.maximum(imin, imax)]
    x2 = np.repeat(xb[:, 0], 2)
    y2 = np.empty(2 * n)
    y2[0::2], y2[1::2] = lo, hi
    return x2, y2


_EVENT_CURVE_CAP = 2000     # painted samples per green event curve


def _grab_add_event_curve(pi, x, y, width):
    """Green event curve over an EVENT-SIZED cropped span -- callers crop
    through _grab_crop; never pass full-segment arrays here. The array is
    then envelope-decimated ONCE to <= _EVENT_CURVE_CAP samples: a 1.4 s
    dwell at 100 kHz is ~1.4e5 samples EACH, and dozens of those at full
    resolution were the [显示全部] lag. Downsampling/clipping stay OFF on
    purpose afterwards: pyqtgraph's AUTO downsampling measures the view
    span against the curve's OWN sample spacing, so a short curve inside
    a zoomed-out view gets an over-large factor and simply vanishes (the
    original disappearing-green bug -- it is NOT only about NaN). Capped
    arrays make the override cheap (<= cap points per curve per frame).
    connect='finite' guards stray NaN samples."""
    if len(y) > _EVENT_CURVE_CAP:
        x, y = _peak_decimate(x, y, _EVENT_CURVE_CAP)
    curve = pg.PlotDataItem(
        x, y, pen=pg.mkPen(THEME['event'], width=width), connect='finite')
    pi.addItem(curve, ignoreBounds=True)
    curve.setDownsampling(auto=False)
    curve.setClipToView(False)
    return curve


def _grab_stats_head(rec, group=False):
    """Shared stats line: rank (+ group no), dwell, level, noise."""
    if group:
        return T('grab.stats.row', r=_grab_rank_of(rec),
                 g=_grab_group_ranks().get(rec['gid'], 0),
                 d=fmt_si(rec['dwell'], 's'),
                 l=fmt_si(rec['y_level'], cur_yunit),
                 s=fmt_si(rec['sigma'], cur_yunit))
    return T('grab.stats.imp', r=_grab_rank_of(rec),
             d=fmt_si(rec['dwell'], 's'),
             l=fmt_si(rec['y_level'], cur_yunit),
             s=fmt_si(rec['sigma'], cur_yunit))


def _grab_stats_tip(grp):
    p = grp['params']
    rank = _grab_group_ranks().get(grp['id'], '?')
    return T('grab.tip.grp', rank=rank, mode=p['mode'],
             k=('%.4g' % p['k']), tmin=('%g' % p['t_min_ms']),
             merge=('%g' % p['merge']), head=('%g' % p['head_ms']),
             smooth=('%g' % p['smooth_ms']), duty=('%g' % p['duty']),
             x0=('%.4g' % grp['x0']), x1=('%.4g' % grp['x1']),
             y0=('%.4g' % grp['y0']), y1=('%.4g' % grp['y1']))


def _grab_stats_text(rec):
    """Compact per-EVENT stats: ONE headline line (+ one optional notes
    line, no wrapping -- vertical space is precious in the panel)."""
    grp = _grab_groups.get(rec['gid']) if rec['gid'] is not None else None
    if grp is None:
        grab_detail_lbl.setToolTip('')
        return _grab_stats_head(rec)
    grab_detail_lbl.setToolTip(_grab_stats_tip(grp))
    head = _grab_stats_head(rec, group=True)
    st = grp.get('stats') if grp else None
    if grp is not None and grp['error']:
        return ('%s<br><span style="color:%s">%s</span>'
                % (head, THEME['A'], grp['error']))
    parts = []
    if st:
        parts.append('h=%s' % fmt_si(st['h'], cur_yunit))
        if st['boundary']:
            parts.append(T('grab.stats.bd', n=st['boundary']))
        if st['duty_disc']:
            parts.append(T('grab.stats.dd', n=st['duty_disc']))
    return head + ('<br>' + ' · '.join(parts) if parts else '')


def _grab_group_stats_text(grp, preview=False):
    """Stats for a row-less group: guidance while the user tunes the
    rectangle (0 events / detection error / live-drag preview) -- including
    the segment noise, so the user can judge the stretch before tuning."""
    grab_detail_lbl.setToolTip(_grab_stats_tip(grp))
    rank = _grab_group_ranks().get(grp['id'], '?')
    noise = np.mean(_grab_segment_noise(grp, _grab_raw_segs_for(grp))) \
        if not grp['error'] else 0.0
    noise_txt = (' · ' + T('grab.w.noise',
                            v=fmt_si(float(noise), cur_yunit))) \
        if not grp['error'] else ''
    if grp['error']:
        return T('grab.grp.err', r=rank, a=fmt_si(grp['x0'], 's'),
                 b=fmt_si(grp['x1'], 's'), c=THEME['A'], e=grp['error'])
    st = grp['stats'] or dict(n=0, boundary=0, duty_disc=0)
    n = len(grp['events'])
    tag = T('grab.w.preview', n=n) if preview else T('grab.w.nev', n=n)
    msg = T('grab.grp.head', r=rank, a=fmt_si(grp['x0'], 's'),
            b=fmt_si(grp['x1'], 's'), tag=tag, noise=noise_txt)
    if n > _GRAB_MAX_EVENTS:
        msg += T('grab.overlimit', c=THEME['A'], cap=_GRAB_MAX_EVENTS)
    elif n == 0:
        msg += T('grab.nofull', n=st['boundary'])
    return msg


_dw_cache = [None, None, None]   # fingerprint, wx, wy (see _grab_detail_windows)


def _grab_detail_windows():
    """UNIFORM detail-view window sizes so events compare fairly: every
    event gets the same X/Y widths (averaged over ALL live rows -- grouped
    rows via their group's source key, groupless import rows via their
    resolved trace). X keeps the +-50% dwell context in the mean (width
    = 2 x mean dwell). Y width = _GRAB_DETAIL_YSPAN x mean(REGION
    min-max): each row's region is the DISPLAYED data inside its own
    X window (searchsorted slices via _grab_view_segs -- raw two-state
    swings included, a sigma-based width shows only the flat in-band
    state and hides the morphology). Returns (wx, wy); wy is None when
    no row yields a finite span (callers fall back to the band).

    CACHED: the result depends only on the display (_data_stamp) and the
    row SET -- never on WHICH row is selected -- but every selection
    change used to redo the all-rows extent loop (~100+ ms with the
    1316-row 500mv-low.csv, on top of every arrow key). Fingerprint =
    (stamp, row count, sum of row ids): ids are unique integers, so
    count+sum changes on any add/remove and the sum is order-free (rows
    are never edited in place, only added/removed)."""
    fp = (_data_stamp, len(grab_records),
          sum(r['id'] for r in grab_records))
    if _dw_cache[0] == fp:
        return _dw_cache[1], _dw_cache[2]
    rows = [r for r in grab_records if _grab_rec_source_matches(r)]
    if not rows:
        _dw_cache[:] = [fp, 2.0e-6, None]
        return 2.0e-6, None
    wx = 2.0 * max(float(np.mean([r['dwell'] for r in rows])), 1e-6)
    spans = []
    for r in rows:
        xc = 0.5 * (r['t_start'] + r['t_end'])
        ext = _grab_region_extent(xc - 0.5 * wx, xc + 0.5 * wx)
        if ext is not None:
            spans.append(ext[1] - ext[0])
    wy = _GRAB_DETAIL_YSPAN * float(np.mean(spans)) if spans else None
    _dw_cache[:] = [fp, wx, wy]
    return wx, wy


def _grab_view_segs(x0, x1):
    """Display segments (raw, per-trace or joined) inside [x0, x1].
    Monotonic axes -> searchsorted slices (never full-axis masks: this
    runs on every selection change and every drag-preview tick)."""
    if _join_active and _joined_display is not None:
        xs, ys = _joined_display
        i0 = int(np.searchsorted(xs, x0, side='left'))
        i1 = int(np.searchsorted(xs, x1, side='right'))
        return ([(xs[i0:i1], ys[i0:i1])] if i1 > i0 else []), 1
    segs = []
    for x, y, label, trace in last_data:
        i0 = int(np.searchsorted(x, x0, side='left'))
        i1 = int(np.searchsorted(x, x1, side='right'))
        if i1 > i0:
            segs.append((x[i0:i1], y[i0:i1]))
    return segs, max(1, len(last_data))


def _grab_region_extent(x0, x1):
    """Finite min/max of everything DISPLAYED inside [x0, x1] (joined
    axis or every trace), or None when the window holds no finite data.
    Same slices the detail view draws, so a window sized from this
    extent is guaranteed to show the whole raw morphology."""
    segs, _n = _grab_view_segs(x0, x1)
    lo, hi = np.inf, -np.inf
    for _x, y in segs:
        yv = y[np.isfinite(y)]
        if yv.size:
            lo = min(lo, float(yv.min()))
            hi = max(hi, float(yv.max()))
    return (lo, hi) if hi > lo else None


def _grab_show_imported(rec):
    """Detail view for a GROUPLESS (CSV v3 import) row: centred on the
    event like a grouped row, but no band / params / tooltip (there is no
    rectangle behind it). Draws only while the row's own trace is
    displayed; otherwise a grey snapshot line saying exactly what to
    select to bring it alive."""
    pi = grab_plot.getPlotItem()
    pi.clear()
    grab_detail_lbl.setToolTip('')
    k = _grab_ref_display_pos(rec)
    if k is None:
        if not _grab_row_file_ok(rec):
            hint = T('grab.imp.otherfile')
        else:
            idx, _how = _grab_resolve_ref(rec.get('trace_ref'))
            if idx is None:
                hint = T('grab.imp.otherref')
            elif bool(rec.get('join', False)) != _join_active:
                hint = T('grab.imp.joinflip', label=trace_label(idx),
                         sw=(T('grab.w.on') if rec.get('join')
                            else T('grab.w.off')))
            else:
                hint = T('grab.imp.select', label=trace_label(idx))
        grab_detail_lbl.setText(
            _grab_stats_head(rec)
            + '<br>' + T('grab.notlive', hint=hint))
        return
    wx, wy = _grab_detail_windows()
    xc = 0.5 * (rec['t_start'] + rec['t_end'])
    x0, x1 = xc - 0.5 * wx, xc + 0.5 * wx
    # searchsorted slices, NEVER full-axis boolean masks: this runs on every
    # row click and a 13M-point joined axis costs ~33 ms PER mask op vs
    # ~0.03 ms for two binary searches (the same rule _grab_view_segs and
    # _grab_crop already follow; only this row's own curve is sliced).
    if _join_active and _joined_display is not None:
        xs, ys = _joined_display
        i0 = int(np.searchsorted(xs, x0, side='left'))
        i1 = int(np.searchsorted(xs, x1, side='right'))
        segs = [(xs[i0:i1], ys[i0:i1])] if i1 > i0 else []
        c = _grab_crop(xs, ys, rec['t_start'], rec['t_end'])
    else:
        x, y = last_data[k][0], last_data[k][1]
        i0 = int(np.searchsorted(x, x0, side='left'))
        i1 = int(np.searchsorted(x, x1, side='right'))
        segs = [(x[i0:i1], y[i0:i1])] if i1 > i0 else []
        c = _grab_crop(x, y, rec['t_start'], rec['t_end'])
    for x, y in segs:
        pi.addItem(pg.PlotDataItem(x, y, pen=trace_pen(0, 1),
                                   connect='finite'))
    if c is not None:
        _grab_add_event_curve(pi, c[0], c[1], 3)
    grab_detail_lbl.setText(_grab_stats_head(rec))
    pi.setXRange(x0, x1, padding=0.02)
    ext = _grab_region_extent(x0, x1)
    if wy is not None and ext is not None:
        yc = 0.5 * (ext[0] + ext[1])
        pi.setYRange(yc - 0.5 * wy, yc + 0.5 * wy, padding=0)
    else:
        span_y = max(abs(rec['y_level']) * 0.2, 3.0 * rec['sigma'], 1e-15)
        pi.setYRange(rec['y_level'] - span_y, rec['y_level'] + span_y,
                     padding=0)
    if last_data:
        pi.setLabels(bottom=('time', cur_xunit), left=('Y', cur_yunit))


def _grab_refresh_views():
    """Repaint selection + overlays (the standard post-change pair)."""
    _grab_show_selected()
    _grab_show_overlays()


def _grab_show_selected():
    """Detail view (left half), centred on the SELECTED EVENT with a
    UNIFORM window (X = 2 x mean dwell of all live rows, keeping the
    +-50% context in the mean; Y = 2 x mean region min-max, centred on
    the event's own region midpoint) so peak sizes compare across
    events; ONLY that event highlights green
    (siblings stay plain -- the green marks the addressed event and
    nothing else). Falls back to the focus group (row-less, being tuned,
    shown at the group's own bounds) or a hint. Stats text always
    renders from the snapshot; curves only while the source data is
    displayed."""
    global _grab_selected
    pi = grab_plot.getPlotItem()
    pi.clear()
    rec = _grab_rec_by_id(_grab_selected)
    if rec is not None and rec['gid'] is None:
        _grab_show_imported(rec)
        return
    grp = _grab_grp_by_id(_grab_focus_gid) if rec is None \
        else _grab_groups.get(rec['gid'])
    if rec is None and grp is None:
        if grab_records:
            grab_detail_lbl.setToolTip('')
            grab_detail_lbl.setText(T('grab.allgrey', n=len(grab_records)))
        else:
            grab_detail_lbl.setToolTip('')
            grab_detail_lbl.setText(T('grab.norec'))
        return
    if not _grab_grp_matches(grp):
        grab_detail_lbl.setText(
            T('grab.otherdata.rec', r=_grab_rank_of(rec),
              g=_grab_group_ranks().get(rec['gid'], 0),
              stats=_grab_stats_text(rec))
            if rec is not None else
            T('grab.otherdata.grp',
              r=_grab_group_ranks().get(grp['id'], 0)))
        return
    preview = _grab_live_gid[0] == grp['id']
    wy = None
    ext = None
    if rec is None:
        grab_detail_lbl.setText(_grab_group_stats_text(grp, preview))
        x0, x1 = grp['x0'], grp['x1']
        bright = None
    else:
        grab_detail_lbl.setText(_grab_stats_text(rec))
        wx, wy = _grab_detail_windows()
        xc = 0.5 * (rec['t_start'] + rec['t_end'])
        x0, x1 = xc - 0.5 * wx, xc + 0.5 * wx
        ext = _grab_region_extent(x0, x1)
        bright = (rec['t_start'], rec['t_end'], rec['i_seg'])
    segs, n_disp = _grab_view_segs(x0, x1)
    for i, (x, y) in enumerate(segs):
        pi.addItem(pg.PlotDataItem(x, y, pen=trace_pen(i, n_disp),
                                   connect='finite'))
    if bright is not None:
        # precise raw-sample highlight: crop the event's OWN trace (the
        # window seg list can reorder/drop traces vs detection i_seg)
        if _join_active and _joined_display is not None:
            xs, ys = _joined_display
            c = _grab_crop(xs, ys, bright[0], bright[1])
        else:
            k = _grab_event_trace_pos(grp, bright[2])
            c = (_grab_crop(last_data[k][0], last_data[k][1],
                            bright[0], bright[1])
                 if k is not None else None)
        if c is not None:
            _grab_add_event_curve(pi, c[0], c[1], 3)
    band = pg.LinearRegionItem(values=(grp['y0'], grp['y1']),
                               orientation='horizontal', movable=False,
                               brush=_tint(THEME['band'], 30),
                               pen=pg.mkPen(THEME['band'], width=1,
                                            style=pg.QtCore.Qt.DashLine))
    band.setZValue(-5)
    pi.addItem(band, ignoreBounds=True)
    pi.setXRange(x0, x1, padding=0.02)
    if wy is not None and ext is not None:
        yc = 0.5 * (ext[0] + ext[1])
        pi.setYRange(yc - 0.5 * wy, yc + 0.5 * wy, padding=0)
    else:
        pad_y = 0.2 * (grp['y1'] - grp['y0'])
        pi.setYRange(grp['y0'] - pad_y, grp['y1'] + pad_y, padding=0)
    if last_data:
        pi.setLabels(bottom=('time', cur_xunit), left=('Y', cur_yunit))


def _grab_show_overlays():
    """Green highlight in the MAIN plot. Default: ONLY the selected event
    (the green marks the addressed event so it can be found at a glance).
    [显示全部] audit mode: EVERY event of EVERY group still matching the
    displayed data AND every live groupless (CSV v3 import) row, at the
    CURRENT view scale (no zooming), the selected one boldest. All spans
    are CROPPED to the events themselves (_grab_crop on the cached prepped
    segments) and finite arrays ride the panel's peak downsampling -- the
    old full-segment NaN masks rendered rectangle-length paths per paint
    and made panning lag with many groups. Audit siblings render as ONE
    merged NaN-separated curve built by _grab_viewall_arrays (below) --
    1316 separate per-event curves meant ~2.6M painted points per pan
    frame (~0.4 s) plus 0.36 s of item churn per selection (2026-10,
    500mv-low viewall lag)."""
    global _grab_overlays
    pi = plot.getPlotItem()
    for it in _grab_overlays:
        if it.scene() is not None:
            pi.removeItem(it)
    _grab_overlays = []
    rec = _grab_rec_by_id(_grab_selected)
    if not _grab_active() or rec is None \
            or not _grab_rec_source_matches(rec):
        return
    if grab_viewall_btn.isChecked():
        X, Y = _grab_viewall_arrays(rec)
        if X is not None:
            cur = pg.PlotDataItem(
                X, Y, pen=pg.mkPen(THEME['event'], width=2),
                connect='finite')
            pi.addItem(cur, ignoreBounds=True)
            cur.setDownsampling(auto=False)     # rule 3: NaN separators
            cur.setClipToView(False)            # poison peak-ds bins
            _grab_overlays.append(cur)
    for x, y in _grab_selected_span(rec):
        _grab_overlays.append(_grab_add_event_curve(pi, x, y, 3))


_GRAB_VIEWALL_MIN_CAP = 64       # per-event floor in audit mode (slivers stay visible)
_GRAB_VIEWALL_PTS_PER_PX = 2.5   # audit decimation density vs on-screen event width
_grab_viewall_cache = [None, None, None, None]   # base fingerprint, X, Y, span


def _grab_viewall_span():
    """Width of the main plot's current x view, in data units (0 = unknown)."""
    try:
        return float(plot.getPlotItem().viewRect().width())
    except Exception:
        return 0.0


def _grab_viewall_arrays(rec):
    """Merged audit overlay for [显示全部]: every live row's event span --
    groups via _grab_group_span_curves (selected included, bold rides on
    top), groupless imports via _grab_selected_span (selected EXCLUDED, it
    draws its own bold curve) -- each cropped (iron rule 1: _grab_crop
    searchsorted, never segment-length arrays) and envelope-decimated
    (rule 2, VIEW-SCALE-AWARE cap: _GRAB_VIEWALL_PTS_PER_PX points per pixel of
    the event's on-screen width, floored at _GRAB_VIEWALL_MIN_CAP -- at a full
    130 s view a 17 ms event is a 0.16 px sliver and 64 points already
    overresolve it; zoomed in the cap grows to _EVENT_CURVE_CAP for full
    fidelity), then concatenated with NaN separators into ONE array for
    ONE PlotDataItem. autoDownsample stays OFF (rule 3) ON PURPOSE:
    pyqtgraph's peak method takes argmin/argmax per bin, so any bin
    straddling a NaN separator collapses to NaN (green patches would
    VANISH at zoom-out), and the gap-skewed mean spacing misjudges the
    factor -- our own scale-aware cap has already bounded the array, the
    override is free. Cache: base fingerprint = (data stamp, row-set
    count+id sum -- rows are only ever added/removed, ids are unique
    integers so count+sum is order-free and complete -- live group event
    counts); the stored span tolerates 1.5x drift, so PANS are pure cache
    hits and only a real zoom (beyond 1.5x, debounced by _grab_viewall_timer)
    rebuilds."""
    span = _grab_viewall_span()
    base_fp = (_data_stamp, len(grab_records),
               sum(r['id'] for r in grab_records),
               tuple((gid, len(g['events'])) for gid, g
                     in sorted(_grab_groups.items())
                     if _grab_grp_matches(g)))
    if _grab_viewall_cache[0] == base_fp and _grab_viewall_cache[1] is not None:
        old = _grab_viewall_cache[3]
        if not (span > 0 and old > 0) \
                or (span <= 1.5 * old and old <= 1.5 * span):
            return _grab_viewall_cache[1], _grab_viewall_cache[2]
    vw = max(1.0, float(plot.width()))
    parts_x, parts_y = [], []

    def _add(x, y):
        dur = float(x[-1] - x[0]) if len(x) > 1 else 0.0
        cap = (_EVENT_CURVE_CAP if span <= 0
               else int(_GRAB_VIEWALL_PTS_PER_PX * dur * vw / span))
        cap = max(_GRAB_VIEWALL_MIN_CAP, min(_EVENT_CURVE_CAP, cap))
        if len(y) > cap:
            x, y = _peak_decimate(x, y, cap)
        parts_x.append(x)
        parts_y.append(y)

    for gid, grp in sorted(_grab_groups.items()):
        if not _grab_grp_matches(grp) or not grp['events'].size:
            continue
        for x, y in _grab_group_span_curves(grp):
            _add(x, y)
    for r in grab_records:
        if r['gid'] is not None or r is rec:
            continue
        for x, y in _grab_selected_span(r):
            _add(x, y)
    if not parts_x:
        _grab_viewall_cache[:] = [base_fp, None, None, span]
        return None, None
    nan = np.full(1, np.nan)
    xs = [v for pair in ([nan, p] for p in parts_x) for v in pair][1:]
    ys = [v for pair in ([nan, p] for p in parts_y) for v in pair][1:]
    _grab_viewall_cache[:] = [base_fp, np.concatenate(xs), np.concatenate(ys),
                         span]
    return _grab_viewall_cache[1], _grab_viewall_cache[2]


def _grab_viewall_zoom_rebuild():
    """Debounced sigRangeChanged follow-up: rebuild the merged audit curve
    only when the view actually changed scale beyond the cache's 1.5x
    tolerance (pans keep the span -- pure cache hits, nothing to do)."""
    if not (grab_viewall_btn.isChecked() and _grab_active()):
        return
    span = _grab_viewall_span()
    old = _grab_viewall_cache[3]
    if span > 0 and old > 0 and (span > 1.5 * old or old > 1.5 * span):
        _grab_show_overlays()


_grab_viewall_timer = pg.QtCore.QTimer(singleShot=True)
_grab_viewall_timer.setInterval(150)
_grab_viewall_timer.timeout.connect(_grab_viewall_zoom_rebuild)


def _grab_viewall_range_debounced(*_a):
    if grab_viewall_btn.isChecked() and _grab_active():
        _grab_viewall_timer.start()


plot.getPlotItem().getViewBox().sigRangeChanged.connect(
    _grab_viewall_range_debounced)


def _grab_selected_span(rec):
    """The selected event's own highlight data (cropped, event-sized).
    Grouped rows read the group's prepped segments at the event's i_seg;
    groupless (import) rows read the displayed arrays their trace
    resolves to (raw samples -- no params, no smoothing to replay)."""
    t0, t1 = rec['t_start'], rec['t_end']
    if rec['gid'] is None:
        k = _grab_ref_display_pos(rec)
        if k is None:
            return []
        if _join_active and _joined_display is not None:
            xs, ys = _joined_display
            c = _grab_crop(xs, ys, t0, t1)
        else:
            c = _grab_crop(last_data[k][0], last_data[k][1], t0, t1)
        return [c] if c is not None else []
    grp = _grab_groups.get(rec['gid'])
    if grp is None or not _grab_grp_matches(grp):
        return []
    return _grab_group_span_curves(grp, [(t0, t1, rec['i_seg'])])


def _grab_rank_of(rec):
    """Display rank (1-based) of a record: its position in the CURRENT
    display order (respects header sorting) -- what the tree's # column
    shows."""
    for i, r in enumerate(_grab_display_order()):
        if r is rec:
            return i + 1
    return 0


def _grab_row(rec, rank):
    """One row per event: rank, start time, dwell, level, segment noise."""
    return ['%d' % rank, fmt_si(rec['t_start'], 's'),
            fmt_si(rec['dwell'], 's'), fmt_si(rec['y_level'], cur_yunit),
            '±' + fmt_si(rec['sigma'], cur_yunit), '']


def _grab_apply_selection_style():
    sel_gid = None
    rec = _grab_rec_by_id(_grab_selected)
    if rec is not None:
        sel_gid = rec['gid']
    elif _grab_focus_gid is not None:
        sel_gid = _grab_focus_gid
    for gid, roi in _grab_rects.items():
        roi.setPen(pg.mkPen(roi.rec_color, width=2 if gid == sel_gid else 1))


def _grab_select(rid):
    global _grab_selected, _grab_focus_gid
    if rid is None:
        _grab_selected = None
        _grab_apply_selection_style()
        return
    if _grab_selected == rid:
        return
    rec = _grab_rec_by_id(rid)
    _grab_selected = rid
    if rec is not None:
        _grab_focus_gid = None          # an event selection replaces focus
    _grab_apply_selection_style()
    _grab_refresh_views()


def _grab_update_summary():
    """Running statistics under the tree over ALL rows (greyed rows from
    other data included -- the list is the curated dataset). TWO fixed
    lines: means, then medians."""
    if not grab_records:
        grab_stats_lbl.setText('')
        return
    dw = np.array([r['dwell'] for r in grab_records])
    lv = np.array([r['y_level'] for r in grab_records])
    sg = np.array([r['sigma'] for r in grab_records])
    grab_stats_lbl.setText(
        T('grab.summary', n=len(grab_records),
          dm=fmt_si(float(dw.mean()), 's'),
          lm=fmt_si(float(lv.mean()), cur_yunit),
          sm=fmt_si(float(sg.mean()), cur_yunit),
          dd=fmt_si(float(np.median(dw)), 's'),
          ld=fmt_si(float(np.median(lv)), cur_yunit),
          sd=fmt_si(float(np.median(sg)), cur_yunit)))


def _refresh_grab_list():
    """Rebuild the event list in the CURRENT display order (header sort
    respected); the # column is the display RANK (recomputed every
    refresh: deletions close the gaps, a clear restarts at 1, edits
    re-sort automatically). Colour chip = group colour; the × delete is
    PAINTED by _GrabDelDelegate (no per-row widgets -- see its docstring).
    Events from other data are greyed but keep their values."""
    grab_tree.clear()
    _grab_items.clear()
    for rank, rec in enumerate(_grab_display_order(), 1):
        item = pg.QtWidgets.QTreeWidgetItem(_grab_row(rec, rank))
        item.rec_id = rec['id']
        pm = pg.QtGui.QPixmap(10, 10)
        pm.fill(pg.QtGui.QColor(rec['color']))
        item.setData(0, pg.QtCore.Qt.DecorationRole, pg.QtGui.QIcon(pm))
        if not _grab_rec_source_matches(rec):
            for c in range(5):
                item.setForeground(
                    c, pg.QtGui.QBrush(pg.QtGui.QColor('#AAAAAA')))
        grab_tree.addTopLevelItem(item)
        _grab_items[rec['id']] = item
    sel = _grab_items.get(_grab_selected)
    if sel is not None:
        grab_tree.setCurrentItem(sel)
    _grab_apply_selection_style()
    _grab_update_summary()


def _grab_tree_changed():
    it = grab_tree.currentItem()
    if it is None:
        return
    rid = getattr(it, 'rec_id', None)
    if rid is not None and rid != _grab_selected:
        _grab_select(rid)


def _grab_tree_doubleclicked(item, _col):
    """Double-click a row: jump the main view onto that event."""
    rec = _grab_rec_by_id(getattr(item, 'rec_id', None))
    if rec is None or not _grab_rec_source_matches(rec):
        return
    pad = max(2.0 * rec['dwell'], 0.01)
    vb.setXRange(rec['t_start'] - pad, rec['t_end'] + pad, padding=0)


_grab_last_delete_t = [0.0]


def _grab_delete(rid):
    """Delete ONE event row -- SURGICALLY: only that row's item is taken
    out and the # ranks renumber in place (no tree rebuild, so no fresh
    x-button ever slides under the cursor to catch the second click of a
    double-click; a 250 ms guard eats that click anyway). When its group's
    last row goes, the group and rectangle go with it. The selection falls
    to the row that takes the deleted rank position (the neighbour), not
    to the end of the list."""
    global _grab_selected
    now = time.time()
    if now - _grab_last_delete_t[0] < 0.25:
        return                                  # double-click's 2nd click
    _grab_last_delete_t[0] = now
    rec = _grab_rec_by_id(rid)
    if rec is None:
        return
    item = _grab_items.pop(rid, None)
    idx = grab_tree.indexOfTopLevelItem(item) if item is not None else None
    if item is not None:
        grab_tree.takeTopLevelItem(idx)         # surgical: neighbours stay
    grab_records[:] = [r for r in grab_records if r['id'] != rid]
    _doc_touch()
    if rec['gid'] is not None \
            and not any(r['gid'] == rec['gid'] for r in grab_records):
        _grab_drop_group(rec['gid'])
    # renumber the remaining rows in place (display order == tree order)
    remaining = _grab_display_order()
    for rank, r in enumerate(remaining, 1):
        it = _grab_items.get(r['id'])
        if it is not None:
            it.setText(0, '%d' % rank)
    if _grab_selected == rid:
        _grab_selected = None
        if remaining:
            pos = max(0, min(idx if idx is not None else 0,
                             len(remaining) - 1))
            for i in [pos] + [j for j in range(len(remaining)) if j != pos]:
                if _grab_rec_source_matches(remaining[i]):
                    _grab_selected = remaining[i]['id']
                    break
        it = _grab_items.get(_grab_selected)
        if it is not None:
            grab_tree.setCurrentItem(it)
        _grab_refresh_views()
    _grab_apply_selection_style()
    _grab_update_summary()


def _grab_clear():
    global _grab_selected, _grab_focus_gid
    if grab_records:
        _doc_touch()          # closing resets dirty after this anyway
    for gid in list(_grab_groups):
        _grab_drop_group(gid)
    grab_records.clear()
    _grab_items.clear()
    _grab_selected = None
    _grab_focus_gid = None
    _refresh_grab_list()
    _grab_refresh_views()


def _grab_delete_group_now(gid):
    """Delete a rectangle WITH all its rows (Ctrl+Delete on the focused
    group -- user-decided semantics: the rectangle and its curated rows
    go together). Selection falls to a surviving live row, else none."""
    global _grab_selected
    _grab_drop_group(gid)
    grab_records[:] = [r for r in grab_records if r['gid'] != gid]
    _doc_touch()
    _grab_selected = None
    first = next((r['id'] for r in grab_records
                  if _grab_rec_source_matches(r)), None)
    _refresh_grab_list()
    if first is not None:
        _grab_select(first)
    _grab_refresh_views()


def _delete_current_selection():
    """Ctrl/Cmd+Delete target, by state: the last-touched grab rectangle
    (focus group) > the selected event row > the Measure markers/drag
    line. Grab objects only resolve while the event panel is armed.
    Returns True when the key was consumed."""
    if _grab_active():
        gid = _grab_focus_gid
        if gid is not None and gid in _grab_groups:
            grp = _grab_groups[gid]
            n = sum(1 for r in grab_records if r['gid'] == gid)
            if n:
                ranks = _grab_group_ranks()
                ans = pg.QtWidgets.QMessageBox.question(
                    win, T('del.rect.title'),
                    T('del.rect.confirm', r=ranks.get(gid, '?'), n=n),
                    pg.QtWidgets.QMessageBox.Yes | pg.QtWidgets.QMessageBox.No,
                    pg.QtWidgets.QMessageBox.No)
                if ans != pg.QtWidgets.QMessageBox.Yes:
                    return True            # consumed, nothing deleted
            _grab_delete_group_now(gid)
            return True
        if _grab_selected is not None:
            _grab_delete(_grab_selected)
            return True
    if meas_points or meas_items or drag_items:
        clear_meas()
        return True
    return False


# -- Flat event CSV (document format) --------------------------------------------
#   v5 = the v4 flat table + a '#' params header. One row per curated
#   event; groups/rectangles are a GUI selection tool and are NOT stored.
#   v6 = v5 + the file_hash column (intrinsic .dat identity: matching no
#   longer consults the path at all; rows from v5-and-older files keep
#   using the legacy path / basename+size fallback).

_GRAB_CSV_COLUMNS = [
    'event_id', 't_start', 't_end', 'dwell', 'y_level', 'noise_sigma',
    'join', 'source_file',
    'trace_g', 'trace_s', 'trace_w', 'trace_t',
    'trace_n', 'trace_dt', 'trace_yunit',
    'file_size', 'file_hash', 'file_mtime']
# columns a CSV must have to be openable at all (file_hash is v6-only:
# its absence just means legacy provenance, not a bad file)
_GRAB_CSV_REQUIRED = [c for c in _GRAB_CSV_COLUMNS if c != 'file_hash']


def _csv_num(row, key, default=None):
    """CSV cell as float; '' / missing -> default."""
    v = (row.get(key) or '').strip()
    if v == '':
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _import_file_matches(src_file, src_size, src_hash=None):
    """File-layer match of the loaded .dat against the saved source.
    Path-independent when both sides carry an intrinsic hash (v6 rows):
    hash equality alone decides -- move / rename / cross-machine all
    resolve without any path. Rows from older CSVs (no hash) keep the
    legacy chain: same absolute path, or same basename + byte size.
    Advisory only -- the structural layer below is the real test."""
    if not _loaded_file or bundle is None:
        return False
    if src_hash and _loaded_fp:
        return src_hash == _loaded_fp
    if src_file and os.path.abspath(src_file) == _loaded_file:
        return True
    if not src_file or src_size is None:
        return False
    try:
        return (os.path.basename(src_file) == os.path.basename(_loaded_file)
                and int(src_size) == os.stat(_loaded_file).st_size)
    except (OSError, ValueError):
        return False


def _import_fp_matches(trace, n, dt, yunit):
    """Header fingerprint comparison (no data read). dt compared with a
    tiny relative tolerance: same acquisition settings round-trip through
    the CSV exactly, cross-file coincidences should not."""
    if int(trace.DataPoints) != int(n):
        return False
    dtc = float(trace.XInterval)
    if abs(dtc - dt) > 1e-9 * max(abs(dtc), abs(dt), 1e-30):
        return False
    return str(getattr(trace, 'YUnit', '') or '') == str(yunit)


def _walk_bundle_traces():
    """All trace leaves of the loaded bundle as (index tuple, node) --
    the resolution pool for saved fingerprints. Pure .pul walk, no data
    arrays are read."""
    out = []
    if bundle is None:
        return out

    def walk(index, node):
        if len(index) == 4:
            out.append((tuple(index), node))
            return
        for i in range(len(node.children)):
            walk(index + [i], node.children[i])

    try:
        walk([], bundle.pul)
    except Exception:
        return out
    return out


def _import_match_ref(ref, pool):
    """Match one saved fingerprint against the pool: the exact tree path
    first (strong), then content (DataPoints/XInterval/YUnit) when the
    path drifted. Returns (index or None, 'path'|'content'|'content?'|
    None) -- 'content?' marks an ambiguous content hit (several traces
    share the fingerprint; the first wins)."""
    path = tuple(ref[:4])
    for idx, trace in pool:
        if idx == path and _import_fp_matches(trace, ref[4], ref[5], ref[6]):
            return idx, 'path'
    hits = [idx for idx, trace in pool
            if _import_fp_matches(trace, ref[4], ref[5], ref[6])]
    if not hits:
        return None, None
    return hits[0], ('content' if len(hits) == 1 else 'content?')


def _grab_after_replot():
    """After every replot: re-attach rectangles against the NEW display
    (add_grab_items reads _grab_source_key from last_data), refresh the
    GROUPLESS (imported) rows -- i_seg follows the trace's position among
    the displayed ones (joined rows stay 0) -- then re-render the detail
    view / summary / overlays against the new attachment state."""
    add_grab_items()
    for rec in grab_records:
        if rec['gid'] is not None:
            continue
        k = _grab_ref_display_pos(rec)
        rec['i_seg'] = 0 if (k is None or _join_active) else k
    _refresh_grab_list()
    _grab_show_selected()
    _grab_update_summary()
    _grab_show_overlays()


def _grab_recalc_all():
    """Re-detect every group still matching the displayed data with the
    CURRENT panel params (whole-group replacement per group)."""
    global _grab_selected
    for grp in list(_grab_groups.values()):
        if not _grab_grp_matches(grp):
            continue
        grp['params'] = _grab_params()
        _grab_detect(grp)
        if len(grp['events']) > _GRAB_MAX_EVENTS:
            continue                                # message via detail view
        _grab_sync_group(grp)
    if _grab_selected is not None and _grab_rec_by_id(_grab_selected) is None:
        _grab_selected = None
    _refresh_grab_list()
    _grab_refresh_views()


class _CsvReject(Exception):
    """Unrecoverable CSV input; .msg is an already-translated message."""

    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg


def _parse_csv_params(path):
    """Scan the '#' header block for a v5 'params:' line -> dict or None.
    v3/v4 files predate the header: None means 'keep current params'."""
    params = None
    try:
        with open(path, errors='replace') as fh:
            for ln in fh:
                if not ln.startswith('#'):
                    break
                if ln.startswith('# params:'):
                    kv = {}
                    for tok in ln[len('# params:'):].split():
                        if '=' in tok:
                            k, v = tok.split('=', 1)
                            kv[k.strip()] = v.strip()
                    if kv:
                        params = kv
    except OSError:
        return None
    if params is not None:
        # CSV header carries the short file-format keys; internal param
        # dicts are uniformly head_ms / smooth_ms.
        if 'head' in params:
            params['head_ms'] = params.pop('head')
        if 'smooth' in params:
            params['smooth_ms'] = params.pop('smooth')
    return params


def _apply_doc_params(params):
    if not params:
        return

    def num(key, widget):
        try:
            widget.set_value_quiet(float(params[key]))
        except (KeyError, ValueError):
            pass

    if params.get('mode') in ('inside', 'outside', 'below', 'above'):
        grab_mode.setCurrentText(params['mode'])
    num('k', grab_k)
    num('t_min_ms', grab_tmin)
    num('merge', grab_merge)
    num('head_ms', grab_head)
    num('smooth_ms', grab_smooth)
    num('duty', grab_duty)


def _parse_grab_csv(path):
    """Flat v3/v4/v5/v6 grab CSV -> (events, bad_rows, params|None).

    v3 files auto-map their stitch column to join; v2 is rejected by its
    group_id column (v3's columns are a strict subset of v2's 33, so the
    missing-column check alone would let it through). v6 adds the
    file_hash column -- optional, its absence just means legacy
    path-based provenance."""
    try:
        with open(path, newline='') as fh:
            lines = [ln for ln in fh if not ln.lstrip().startswith('#')]
    except OSError as exc:
        raise _CsvReject(T('csv.readfail', err=exc))
    rdr = csv.DictReader(lines)
    rows = list(rdr)
    if 'group_id' in (rdr.fieldnames or []):
        raise _CsvReject(T('csv.v2'))
    _cols = set(rdr.fieldnames or [])
    if 'join' not in _cols and 'stitch' in _cols:
        for row in rows:
            row['join'] = row.get('stitch', '')
        _cols.add('join')
    missing = [c for c in _GRAB_CSV_REQUIRED if c not in _cols]
    if missing:
        raise _CsvReject(T('csv.missing', cols=', '.join(missing)))
    if not rows:
        raise _CsvReject(T('csv.empty'))

    evs = []
    bad = 0
    for row in rows:
        ts = _csv_num(row, 't_start')
        te = _csv_num(row, 't_end')
        dw = _csv_num(row, 'dwell')
        yl = _csv_num(row, 'y_level')
        sg = _csv_num(row, 'noise_sigma')
        if None in (ts, te, dw, yl, sg):
            bad += 1
            continue
        ref = None
        if all((row.get(c) or '').strip() for c in
               ('trace_g', 'trace_s', 'trace_w', 'trace_t',
                'trace_n', 'trace_dt', 'trace_yunit')):
            try:
                ref = (int(float(row['trace_g'])), int(float(row['trace_s'])),
                       int(float(row['trace_w'])), int(float(row['trace_t'])),
                       int(float(row['trace_n'])), float(row['trace_dt']),
                       row['trace_yunit'].strip())
            except ValueError:
                ref = None
        evs.append(dict(t_start=ts, t_end=te, dwell=dw, y_level=yl,
                        sigma=sg, trace_ref=ref,
                        join=str(row.get('join', '')).strip().lower()
                        == 'true',
                        source_file=(row.get('source_file') or '').strip(),
                        file_size=_csv_num(row, 'file_size'),
                        file_hash=(row.get('file_hash') or '').strip()
                        or None,
                        file_mtime=_csv_num(row, 'file_mtime')))
    if not evs:
        raise _CsvReject(T('csv.nousable',
                           bad=(T('csv.badrows', n=bad) if bad else '')))
    evs.sort(key=lambda e: e['t_start'])
    return evs, bad, _parse_csv_params(path)


_locate_dismissed = set()   # (src_file, src_size, src_hash) the user
                             # cancelled the locate dialog for -- asked
                             # once per session, not on every tab switch


def _doc_locate_source(src_file, src_size, csv_dir, src_hash=None):
    """Saved .dat path is gone: look for a same-named file next to the
    CSV (the classic moved-data-folder case), then in the last data dir,
    then in the explorer column's dir. Candidates verify by intrinsic
    hash when the rows carry one (v6), else by byte size."""
    base = os.path.basename(src_file) if src_file else ''
    if not base:
        return ''
    pool = dict.fromkeys(filter(None, (csv_dir,
                                       settings.value('last_dir', ''),
                                       _exp_dir[0])))
    for d in pool:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        if base not in names:
            continue
        p = os.path.join(d, base)
        try:
            if src_hash:
                if _file_fp(p) == src_hash:
                    return p
            elif src_size is None or os.path.getsize(p) == int(src_size):
                return p
        except OSError:
            continue
    return ''


def _doc_set_context(src_file, src_size, join_wanted, refs, csv_dir='',
                     src_hash=None):
    """Restore the display context a document's rows were grabbed from:
    load the source .dat (hash match against the loaded file -> saved
    path -> basename search (csv dir / last dir / explorer dir) -> locate
    dialog -> degrade to grey rows; bundle LRU makes switching between
    two files cheap), set Join from the rows' axis semantics, select the
    referenced traces' SERIES (refs arrive already collapsed to (g, s):
    the join axis is paced by the displayed set, so selecting bare trace
    leaves would drop every event-less sweep and shift every later seam).
    Degrade, never abort. In a bundle-less (synthetic / lost-source)
    context nothing display-side is touched: a replot with no tree
    selection would wipe the injected display."""
    global _join_active
    if not src_file and not refs and not join_wanted:
        return                          # nothing to restore (empty doc)
    if src_file and not _import_file_matches(src_file, src_size, src_hash):
        cand = ''
        if (os.path.isfile(src_file)
                and (not src_hash or _file_fp(src_file) == src_hash)):
            # path still lives and (when known) hashes to the right file
            cand = src_file
        else:
            cand = _doc_locate_source(src_file, src_size, csv_dir, src_hash)
            if not cand and (src_file, src_size, src_hash) \
                    not in _locate_dismissed:
                cand, _ = pg.QtWidgets.QFileDialog.getOpenFileName(
                    win, T('csv.locate',
                           suffix=('：' + os.path.basename(src_file))
                           if src_file else ''),
                    (os.path.dirname(src_file) if src_file
                     else csv_dir or settings.value('last_dir', '')),
                    'Heka bundle (*.dat)')
                if not cand:
                    _locate_dismissed.add((src_file, src_size, src_hash))
        if cand:
            _locate_dismissed.discard((src_file, src_size, src_hash))
            try:
                load(cand)
            except Exception as exc:
                pg.QtWidgets.QMessageBox.warning(
                    win, T('csv.imp.title'), T('csv.openfail', err=exc))
    # Join carries the t-axis semantics of the saved rows. With a real
    # bundle the toggle drives the normal replot path; bundle-less it is
    # flipped QUIETLY (signals would replot and wipe the synthetic
    # display the caller may have injected).
    if join_wanted != join_btn.isChecked():
        if bundle is not None:
            join_btn.setChecked(join_wanted)   # -> join_toggled -> replot
        else:
            join_btn.blockSignals(True)
            join_btn.setChecked(join_wanted)
            join_btn.blockSignals(False)
            _join_active = join_wanted
    if refs and bundle is not None:
        tree.blockSignals(True)
        for it in tree.selectedItems():
            it.setSelected(False)
        for path in refs:
            it = _tree_item_by_path(path)
            if it is not None:
                it.setSelected(True)
        tree.blockSignals(False)
        replot()                # re-attach + refresh live rows (grey rest)


def _doc_restore_context():
    """Re-derive the display context from the ACTIVE document's rows:
    grouped rows speak through their group's source key, groupless rows
    carry their own provenance. Feeds _doc_set_context."""
    src_file = ''
    src_size = None
    src_hash = None
    joins = set()
    for grp in _grab_groups.values():
        if not src_file and grp['source_key'][0]:
            src_file = grp['source_key'][0]
        if src_hash is None:
            src_hash = grp.get('file_hash') or None
        joins.add(bool(grp['source_key'][1]))
    for r in grab_records:
        if r['gid'] is not None:
            continue
        if not src_file and r.get('source_file'):
            src_file = r['source_file']
        if src_size is None and r.get('file_size') is not None:
            src_size = r['file_size']
        if src_hash is None and r.get('file_hash'):
            src_hash = r['file_hash']
        joins.add(bool(r.get('join', False)))
    join_wanted = any(joins) if joins else join_btn.isChecked()
    # Collapse refs to SERIES level: rows only carry refs for sweeps that
    # produced events, but the join axis is paced by the DISPLAYED set --
    # selecting the bare leaves would drop every event-less sweep from the
    # concatenation and shift all later seams (progressive t drift, found
    # with 200mv-high.csv: sweeps 19/37 event-less -> -5/-10 s steps).
    refs = sorted({r['trace_ref'][:2] for r in grab_records
                   if r.get('trace_ref')})
    csv_dir = (os.path.dirname(_doc['path']) if _doc.get('path') else '')
    _doc_set_context(src_file, src_size, join_wanted, refs, csv_dir,
                     src_hash=src_hash)


def _open_doc(path):
    """Open a flat event CSV as a NEW analysis document tab (the current
    documents stay open in theirs -- nothing to confirm). Opening a path
    that already has a tab just activates it. Rows are restored exactly
    as saved (no re-detection, no rectangles, no groups -- draw new
    rectangles to re-grab), then the context they came from is restored.
    Rows light up when their own trace is displayed; the rest stay grey
    snapshots."""
    global _doc, _grab_selected, _grab_focus_gid
    if not path:
        return
    try:
        evs, bad, params = _parse_grab_csv(path)
    except _CsvReject as exc:
        pg.QtWidgets.QMessageBox.warning(win, T('csv.imp.title'), exc.msg)
        return
    absp = os.path.abspath(path)
    for i, d in enumerate(_doc_list):
        if d['path'] == absp:
            _doc_switch(i)               # already open: just activate
            return
    _doc_state_capture()
    d = {'open': True, 'path': absp, 'dirty': False, 'state': {}}
    _doc_spawn(d)
    _apply_doc_params(params)

    # -- inject rows (groupless: the group machinery stays untouched)
    for e in evs:
        eid = _grab_next_eid[0]
        _grab_next_eid[0] += 1
        grab_records.append(dict(
            id=eid, gid=None, color=THEME['import'],
            t_start=e['t_start'], t_end=e['t_end'], dwell=e['dwell'],
            y_level=e['y_level'], i_seg=0, sigma=e['sigma'],
            trace_ref=e['trace_ref'], join=e['join'],
            source_file=e['source_file'], file_size=e['file_size'],
            file_hash=e['file_hash'], file_mtime=e['file_mtime']))

    src_file = next((e['source_file'] for e in evs if e['source_file']), '')
    src_size = next((e['file_size'] for e in evs
                     if e['file_size'] is not None), None)
    src_hash = next((e['file_hash'] for e in evs if e['file_hash']), None)
    join_wanted = any(e['join'] for e in evs)
    # SERIES-level paths (not the bare trace leaves): see
    # _doc_restore_context -- leaf selection drops event-less sweeps and
    # compresses the join axis for everything after them.
    refs = sorted({e['trace_ref'][:2] for e in evs if e['trace_ref']})
    _doc_set_context(src_file, src_size, join_wanted, refs,
                     csv_dir=os.path.dirname(absp), src_hash=src_hash)

    # -- i_seg for rows live on the current display: their trace's
    # position among the displayed ones (joined rows stay 0)
    for rec in grab_records:
        k = _grab_ref_display_pos(rec)
        rec['i_seg'] = 0 if (k is None or _join_active) else k

    _grab_focus_gid = None
    first = next((r['id'] for r in grab_records
                  if _grab_rec_source_matches(r)), None)
    if first is None and grab_records:
        first = grab_records[0]['id']
    _grab_selected = None
    _refresh_grab_list()
    if first is not None:
        _grab_select(first)
    _grab_show_overlays()

    # -- report (silent when everything attached cleanly)
    live = sum(1 for r in grab_records if _grab_rec_source_matches(r))
    resolved = 0
    hows = set()
    for r in grab_records:
        if not _grab_row_file_ok(r):
            continue
        _idx, how = _grab_resolve_ref(r.get('trace_ref'))
        if _idx is not None:
            resolved += 1
            if how:
                hows.add(how)
    notes = []
    if bad:
        notes.append(T('csv.note.bad', n=bad))
    in_file = resolved - live
    other = len(grab_records) - resolved
    if live < len(grab_records):
        notes.append(T('csv.note.live', n=live))
    if in_file > 0:
        notes.append(T('csv.note.infile', n=in_file))
    if other > 0:
        notes.append(T('csv.note.other', n=other))
    if 'content?' in hows:
        notes.append(T('csv.note.cand'))
    elif 'content' in hows:
        notes.append(T('csv.note.content'))
    if notes:
        pg.QtWidgets.QMessageBox.information(
            win, T('csv.imp.title'),
            T('csv.report', n=len(grab_records),
              notes='\n· '.join(notes)))


class _DeleteKeyFilter(pg.QtCore.QObject):
    """App-wide Ctrl+Delete (Win/Linux) / Cmd+Delete (macOS) deletes the
    CURRENT SELECTION, resolved by state in _delete_current_selection:
    last-touched grab rectangle > selected event row > Measure results.
    Installed as an APPLICATION filter (not a QShortcut, which would eat
    the key from every text field) with an explicit passthrough: while a
    text widget holds focus the key stays native (Cmd+Backspace =
    delete-to-line-start, Ctrl+Backspace = delete-word). Both physical
    keys count as "Delete" here: the macOS keyboard's delete key IS
    Backspace -- matching only Key_Delete (fn+delete) made the shortcut
    look dead on Macs. Bare Delete/Backspace stays bound to zoom-undo."""

    def eventFilter(self, obj, ev):
        if (ev.type() == pg.QtCore.QEvent.KeyPress
                and ev.key() in (pg.QtCore.Qt.Key_Delete,
                                 pg.QtCore.Qt.Key_Backspace)
                and (ev.modifiers() & (pg.QtCore.Qt.ControlModifier
                                        | pg.QtCore.Qt.MetaModifier))):
            fw = pg.QtWidgets.QApplication.focusWidget()
            if isinstance(fw, (pg.QtWidgets.QLineEdit,
                               pg.QtWidgets.QTextEdit,
                               pg.QtWidgets.QPlainTextEdit,
                               pg.QtWidgets.QAbstractSpinBox)):
                return False            # native text editing behaviour
            if _delete_current_selection():
                return True
        return pg.QtCore.QObject.eventFilter(self, obj, ev)


_delete_keys = _DeleteKeyFilter()
app.installEventFilter(_delete_keys)


class _ModeClickFilter(pg.QtCore.QObject):
    """App-wide click watcher arming the Shift+drag gesture: the analysis
    area whose widget tree contains the press target owns the gesture --
    a press inside the Amplitude column arms amplitude mode, a press
    inside the Event panel arms event mode. Presses anywhere else (main
    plot, left column, dialogs) leave the mode alone: the plot is a
    shared canvas and never switches the mode itself."""

    def eventFilter(self, obj, ev):
        if (ev.type() == pg.QtCore.QEvent.MouseButtonPress
                and isinstance(obj, pg.QtWidgets.QWidget)):
            w = obj
            while w is not None:
                if w is amp_col:
                    _set_ui_mode('amp')
                    break
                if w is sec_events:
                    _set_ui_mode('event')
                    break
                w = w.parentWidget()
        return pg.QtCore.QObject.eventFilter(self, obj, ev)


_mode_clicks = _ModeClickFilter()
app.installEventFilter(_mode_clicks)

grab_tree.currentItemChanged.connect(lambda *_: _grab_tree_changed())
grab_tree.itemDoubleClicked.connect(_grab_tree_doubleclicked)
grab_tree.header().sectionClicked.connect(_grab_header_clicked)
grab_viewall_btn.toggled.connect(lambda *_: _grab_show_overlays())
grab_clear_btn.clicked.connect(_grab_clear)
grab_recalc_btn.clicked.connect(_grab_recalc_all)
empty_new_btn.clicked.connect(lambda *_: _doc_new())
doc_new_btn.clicked.connect(lambda *_: _doc_new())
doc_tabs.tabCloseRequested.connect(lambda i: _doc_close_tab(i))
doc_tabs.currentChanged.connect(lambda i: _doc_switch(i))
doc_save_btn.clicked.connect(lambda *_: _doc_save())
doc_saveas_btn.clicked.connect(lambda *_: _doc_saveas())
exp_list.itemDoubleClicked.connect(_exp_double_clicked)
exp_list.itemChanged.connect(_exp_item_changed)
exp_up.clicked.connect(lambda *_: _exp_up())
exp_csv_only.toggled.connect(_exp_csv_toggled)

# Document shortcuts (StandardKey = Cmd on macOS, Ctrl elsewhere). Plain
# WindowShortcut context on the main window: modal dialogs block them
# naturally, focus anywhere inside the window triggers them. The handlers
# themselves no-op without an open document (_doc is _DOC_CLOSED).
for _seq, _fn in ((pg.QtGui.QKeySequence.New, _doc_new),
                  (pg.QtGui.QKeySequence.Save, _doc_save),
                  (pg.QtGui.QKeySequence.SaveAs, _doc_saveas)):
    _sc_doc = QShortcut(pg.QtGui.QKeySequence(_seq), win)
    _sc_doc.activated.connect(lambda fn=_fn: fn())


# Debounced refresh of the amplitude histogram while the user zooms the main
# view with "range = view Y" on
_follow_timer = pg.QtCore.QTimer()
_follow_timer.setSingleShot(True)
_follow_timer.setInterval(150)
_follow_timer.timeout.connect(amp_recompute)


def _main_range_changed(*_):
    if _amp_active() and amp_follow.isChecked() and amp_regions:
        _follow_timer.start()


amp_auto_bins.toggled.connect(lambda *_: amp_recompute())
amp_bins._cb = lambda *_: amp_recompute()
amp_follow.toggled.connect(lambda *_: amp_recompute())
amp_ruler_btn.toggled.connect(amp_ruler_toggled)
ruler_a.sigPositionChangeFinished.connect(_update_ruler)
ruler_b.sigPositionChangeFinished.connect(_update_ruler)
ruler_a.sigPositionChanged.connect(_update_ruler)
ruler_b.sigPositionChanged.connect(_update_ruler)
amp_clear_btn.clicked.connect(
    lambda: (clear_amp_regions(), _refresh_region_list(), amp_recompute()))
vb.sigYRangeChanged.connect(_amp_follow_main_y)
vb.sigRangeChanged.connect(_main_range_changed)
clear_btn.clicked.connect(clear_analysis)
sec_events.btn.clicked.connect(_event_panel_toggled)
amp_col.btn.clicked.connect(_amp_col_toggled)


# initial hints + persisted state. Deliberately NOT persisted: the mode
# (which area was clicked last) -- the app always starts in event mode,
# like Measure. The amp column's fold state IS remembered below.
amp_recompute()
_grab_show_selected()
_refresh_region_list()
_refresh_grab_list()
_refresh_mode_hints()

# explorer startup dir: last browsed dir, else the last data dir, else home
_exp_root0 = settings.value('explorer/dir', '') or ''
if not os.path.isdir(_exp_root0):
    _exp_root0 = settings.value('last_dir', '') or ''
if not os.path.isdir(_exp_root0):
    _exp_root0 = os.path.expanduser('~')
_exp_set_root(_exp_root0)

# load Heka's demo bundle if it is present
demo = 'DemoV9Bundle.dat'
if os.path.isfile(demo):
    load(demo)


_FOLD_SECTIONS = (('tree', sec_tree), ('nano', sec_nano), ('info', sec_info),
                  ('dist', sec_events), ('files', exp_col))


def _restore_layout():
    """Restore saved splitter sizes and folded sections. First launch (no
    saved state) uses a compact File info section: path + metadata visible
    but short, leaving most of the column to the tree and calculator."""
    hs = settings.value('layout/hsplit')
    if hs:
        hsplit.setSizes([int(s) for s in hs])
    vs = settings.value('layout/vsplit')
    if vs:
        vsplit.setSizes([int(s) for s in vs])
    else:
        # [info, tree, nano]: compact info strip up top, tree dominates
        vsplit.setSizes((150, 380, 200))
    ds = settings.value('layout/distsplit')
    if ds:
        right_split.setSizes([int(s) for s in ds])
    else:
        right_split.setSizes((600, 220))
    gs = settings.value('layout/grabsplit')
    # legacy saves hold THREE sizes (zoom | tree | files, before the file
    # column moved to its own document splitter): the inner splitter keeps
    # the first two panes, the outer document pane absorbs their sum
    if gs and len(gs) == 3:
        grab_split.setSizes([int(gs[0]), int(gs[1])])
        doc_split.setSizes([int(gs[0]) + int(gs[1]), int(gs[2])])
    elif gs and len(gs) == 2:
        grab_split.setSizes([int(s) for s in gs])
    else:
        grab_split.setSizes((520, 260))
    if not (gs and len(gs) == 3):
        ts2 = settings.value('layout/docsplit')
        if ts2 and len(ts2) == 2:
            doc_split.setSizes([int(s) for s in ts2])
        else:
            doc_split.setSizes((2400, 320))
    # amp column starts FOLDED on first launch (default True); the other
    # sections default to expanded. dist/tab died with the tab widget.
    settings.remove('dist/tab')
    for key, sec in _FOLD_SECTIONS:
        sec.set_collapsed(settings.value('layout/collapsed/' + key, False, type=bool))
    # left-column sections: seed the unfold height for still-folded ones.
    # The collapse transition above snapshots the live pane size -- which
    # is the STRIP (or pre-layout junk) at this point, never the height
    # the user had dragged. Same poison-and-seed pattern as the amp
    # column's _restore, which wins because it runs after the snapshot.
    for key, sec in (('tree', sec_tree), ('nano', sec_nano),
                     ('info', sec_info)):
        v = settings.value('layout/vopen/' + key)
        if sec.is_collapsed() and v:
            sec._restore = int(v)
    amp_col.set_collapsed(
        settings.value('layout/collapsed/amp', True, type=bool))
    # amp width: remembered width wins; first launch = 15% of the window
    # (the unmanaged splitter default was far too wide). Seeding _restore
    # AFTER the collapse call: collapsing snapshots the live pane size as
    # the unfold width, and that snapshot is unreliable before the first
    # layout pass -- the explicit seed makes the unfold deterministic.
    # A FOLDED pane must sit at strip width: QSplitter.setSizes only
    # raises values below the minimum hint and IGNORES maximumWidth, so
    # handing the saved EXPANDED width to the folded pane leaves it wide
    # and contentless (only the fold arrow). set_collapsed early-returns
    # once the flag is set, hence the direct strip assignment here.
    ts = settings.value('layout/ampsplit')
    if ts and len(ts) == 2:
        amp_w = int(ts[1])
    else:
        amp_w = max(240, int(win.width() * 0.15))
    amp_col._restore = amp_w
    if amp_col.is_collapsed():
        amp_col._splitter_assign(amp_col.strip_width())
    elif ts and len(ts) == 2:
        top_split.setSizes([int(ts[0]), int(ts[1])])
    else:
        top_split.setSizes([max(240, win.width() - amp_w), amp_w])
    # normalize mode-dependent state after programmatic folds
    _amp_col_toggled()
    _event_panel_toggled()


_restore_layout()

# Re-run the restore on the first event-loop tick: sizes set BEFORE the
# window's first real layout pass get clobbered -- the layout's minimum
# width grows the window (1200 -> ~1657 px) and QSplitter redistributes
# panes from size hints, ignoring the requested sizes. That was the
# long-standing "launch defaults / persisted layouts don't stick" quirk
# (and it made the amp column open at half the window). By the first
# tick the geometry is final, setSizes sticks, and the 15%-of-window
# default is computed against the REAL window width.
pg.QtCore.QTimer.singleShot(0, _restore_layout)


def _save_layout():
    settings.setValue('layout/hsplit', list(hsplit.sizes()))
    settings.setValue('layout/vsplit', list(vsplit.sizes()))
    # folded left-column sections persist their UNFOLD height separately:
    # the vsplit list above holds the STRIP height for them, and the
    # in-memory _restore would otherwise die with the process (expanding
    # after a restart used to fall back to the ~150 default). Expanded
    # sections remove the key so stale heights can never leak back.
    for key, sec in (('tree', sec_tree), ('nano', sec_nano),
                     ('info', sec_info)):
        k_open = 'layout/vopen/' + key
        if sec.is_collapsed() and getattr(sec, '_restore', 0):
            settings.setValue(k_open, int(sec._restore))
        else:
            settings.remove(k_open)
    settings.setValue('layout/distsplit', list(right_split.sizes()))
    # save the UNFOLDED amp width: quitting while collapsed stores the
    # strip width, which would become the unfold-restore width otherwise
    if amp_col.is_collapsed() and getattr(amp_col, '_restore', 0):
        _aw = int(amp_col._restore)
        settings.setValue('layout/ampsplit',
                          [max(240, sum(top_split.sizes()) - _aw), _aw])
    else:
        settings.setValue('layout/ampsplit', list(top_split.sizes()))
    settings.setValue('layout/grabsplit', list(grab_split.sizes()))
    settings.setValue('layout/docsplit', list(doc_split.sizes()))
    settings.setValue('grab/mode', grab_mode.currentText())
    settings.setValue('grab/k', grab_k.value())
    settings.setValue('grab/t_min_ms', grab_tmin.value())
    settings.setValue('grab/merge', grab_merge.value())
    settings.setValue('grab/head', grab_head.value())
    settings.setValue('grab/smooth', grab_smooth.value())
    settings.setValue('grab/duty', grab_duty.value())
    for key, sec in _FOLD_SECTIONS:
        settings.setValue('layout/collapsed/' + key, sec.is_collapsed())
    settings.setValue('layout/collapsed/amp', amp_col.is_collapsed())
    settings.setValue('amp/bins_auto', amp_auto_bins.isChecked())
    settings.setValue('amp/bins', amp_bins.value())
    settings.setValue('amp/follow', amp_follow.isChecked())


app.aboutToQuit.connect(_save_layout)

# Start the Qt event loop unless the user is in an interactive prompt
if sys.flags.interactive == 0:
    app.exec_()
