import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyqtgraph as pg
import numpy as np
from heka import reader as heka_reader
from heka import analysis
from heka.nanopore import calculate_pore_diameter, get_conductivity

# Light modern theme: all colors in one place, tweak here only
THEME = {
    'bg':         '#FAFAFA',                    # plot background (off-white)
    'fg':         '#333333',                    # axes / ticks / legend text
    'crosshair':  '#FF7F0E',                    # orange dashed crosshair
    'A':          '#D62728',                    # A marker (red)
    'B':          '#1F77B4',                    # B marker (blue)
    'readout':    '#1F1F1F',                    # readout text
    'readout_bg': (255, 255, 255, 190),         # translucent white panel
    'seam':       '#B0B0B0',                    # stitch seam dashed lines
    'band':       '#76B7B2',                    # Detect threshold band (teal)
    'event':      '#59A14F',                    # event highlight / event hists
    # Tableau 10 for <= 10 traces; Tableau 20 (deep+light shades) for <= 20;
    # beyond that a muted golden-ratio hue walk -- distinguishable, no neon
    'cycle':      ['#4E79A7', '#F28E2B', '#E15759', '#76B7B2', '#59A14F',
                   '#EDC948', '#B07AA1', '#FF9DA7', '#9C755F', '#BAB0AC'],
    'cycle20':    ['#4E79A7', '#A0CBE8', '#F28E2B', '#FFBE7D', '#59A14F',
                   '#8CD17D', '#B6992D', '#F1CE63', '#499894', '#86BCB6',
                   '#E15759', '#FF9D9A', '#79706E', '#BAB0AC', '#D37295',
                   '#FABFD2', '#B07AA1', '#D4A6C8', '#9D7660', '#D7B5A6'],
}


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
        if isinstance(sp, pg.QtWidgets.QSplitter):
            idx = sp.indexOf(self)
            sizes = sp.sizes()
            if collapsed:
                sizes[idx] = self.btn.sizeHint().height() + 4   # keep header clickable
            else:
                sizes[idx] = getattr(self, '_restore', 0) or 150
            sp.setSizes([int(s) for s in sizes])

    def is_collapsed(self):
        return self._collapsed

    def add_widget(self, w):
        self.body_lay.addWidget(w)


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
w1l = pg.QtWidgets.QGridLayout()
w1l.setContentsMargins(0, 0, 0, 0)
btn_row.setLayout(w1l)
left_lay.addWidget(btn_row, 0, 0)

# Button for loading .dat file
load_btn = pg.QtWidgets.QPushButton("Load...")
w1l.addWidget(load_btn, 0, 0)

# Button to auto-fit X/Y axes to the displayed data
auto_btn = pg.QtWidgets.QPushButton("Auto")
w1l.addWidget(auto_btn, 0, 1)

# Checkable button toggling click-to-measure mode on the plot
measure_btn = pg.QtWidgets.QPushButton("Measure")
measure_btn.setCheckable(True)
w1l.addWidget(measure_btn, 1, 0)

# Button clearing all measurement markers
clear_btn = pg.QtWidgets.QPushButton("Clear")
w1l.addWidget(clear_btn, 1, 1)

# Checkable button toggling end-to-end stitching of multi-selected traces
stitch_btn = pg.QtWidgets.QPushButton("Stitch")
stitch_btn.setCheckable(True)
stitch_btn.setChecked(settings.value('stitch', False, type=bool))
w1l.addWidget(stitch_btn, 1, 2, 1, 2)

# Amplitude-region and event-detection controls live inside the Distribution
# panel tabs below the plot (see the distribution section), not up here.

# Collapsible section: file tree
sec_tree = Collapsible('File tree')
tree = pg.QtWidgets.QTreeWidget()
tree.setHeaderLabels(['Node', 'Label'])
tree.setColumnWidth(0, 200)
tree.setSelectionMode(pg.QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
sec_tree.add_widget(tree)
vsplit.addWidget(sec_tree)

# Read-only path bar showing the full path of the loaded file.
# Text is selectable so the absolute path can be copied (Cmd+C / Cmd+A).
path_label = pg.QtWidgets.QLineEdit('no file loaded')
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

# Right column: main plot on top, collapsible Distribution panel below
# (see the distribution section further down); the splitter keeps a fixed
# panel height while the traces take the rest.
dist_split = pg.QtWidgets.QSplitter(pg.QtCore.Qt.Vertical)
dist_split.addWidget(plot)
right_col = pg.QtWidgets.QWidget()
right_lay = pg.QtWidgets.QGridLayout()
right_lay.setContentsMargins(0, 0, 0, 0)
right_col.setLayout(right_lay)
right_lay.addWidget(dist_split, 0, 0)
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
        None, 'Open data file', start_dir, 'Heka bundle (*.dat)')
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

vLine = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(THEME['crosshair'], width=1, style=pg.QtCore.Qt.DashLine))
hLine = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(THEME['crosshair'], width=1, style=pg.QtCore.Qt.DashLine))

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
stitch_segments = []
cur_xunit = 's'
cur_yunit = 'A'
last_mouse = None
last_snap = None
last_cursor_text = ''
bundle = None


def add_crosshair():
    """Re-attach crosshair lines to the plot (plot.clear() detaches them)."""
    pi = plot.getPlotItem()
    for ln in (vLine, hLine):
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
    """Text of the stitched segment containing x ('' outside stitch mode)."""
    for x0, x1, text in stitch_segments:
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


def update_title_from_state(cursor_text=None):
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
    update_title_from_state()


def measure_toggled(checked):
    vLine.setVisible(checked)
    hLine.setVisible(checked)
    # no exclusivity needed any more: Measure owns plain drag, the
    # analysis tabs own Shift+drag -- they can be on at the same time
    if not checked:
        drag_measure_hide()
    update_title_from_state()
    if checked and last_mouse is not None:
        mouse_moved([last_mouse])


def plot_clicked(ev):
    if not measure_btn.isChecked():
        return
    if ev.button() != pg.QtCore.Qt.LeftButton or ev.double():
        return
    vb = plot.getPlotItem().getViewBox()
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
    update_title_from_state()


def mouse_moved(evt):
    global last_mouse, last_snap, last_cursor_text
    pos = evt[0]
    last_mouse = pg.QtCore.QPointF(pos)
    if not measure_btn.isChecked():
        return
    vb = plot.getPlotItem().getViewBox()
    if not vb.sceneBoundingRect().contains(pos):
        return
    vpos = vb.mapSceneToView(pos)
    vLine.setPos(vpos.x())
    hLine.setPos(vpos.y())
    best = nearest_on_curves(vpos)
    last_snap = None
    name = ''
    if best is not None:
        last_snap = (best[1], best[2], best[3].name() or '', best[3])
        name = segment_at(vpos.x()) or (best[3].name() or '')
    txt = 'cursor: ' + format_point(vpos.x(), vpos.y(), name)
    last_cursor_text = txt
    update_title_from_state(txt)


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
proxy = pg.SignalProxy(plot.scene().sigMouseMoved, rateLimit=60, slot=mouse_moved)


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
        text = (self.text().replace('，', '.').replace('。', '.').replace('．', '.'))
        try:
            return float(text)
        except ValueError:
            return None

    def _on_text_changed(self, text):
        normalized = text.replace('，', '.').replace('。', '.').replace('．', '.')
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
        form.addRow('Solution', self.salt)

        self.conc = NumericEdit(1.0, 0.001, 5.0, change_cb=self.refresh)
        form.addRow('Concentration (M)', self.conc)

        self.thick = NumericEdit(20.0, 1.0, 100.0, change_cb=self.refresh)
        form.addRow('Membrane thickness (nm)', self.thick)

        self.volt = NumericEdit(100.0, 0.001, 10000.0, change_cb=self.refresh)
        form.addRow('Voltage (mV)', self.volt)

        curr_row = pg.QtWidgets.QWidget()
        curr_lay = pg.QtWidgets.QHBoxLayout(curr_row)
        curr_lay.setContentsMargins(0, 0, 0, 0)
        self.curr = NumericEdit(1.0, 0.0001, 1e6, change_cb=self.refresh)
        self.unit = pg.QtWidgets.QComboBox()
        self.unit.addItems(['nA', 'pA'])
        curr_lay.addWidget(self.curr)
        curr_lay.addWidget(self.unit)
        form.addRow('Current', curr_row)

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
sec_nano = Collapsible('Nanopore calculator')
sec_nano.add_widget(nano)
vsplit.addWidget(sec_nano)


# Collapsible section: file path + metadata tree
sec_info = Collapsible('File info')
sec_info.add_widget(path_label)
sec_info.add_widget(data_tree)
vsplit.addWidget(sec_info)

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
    """Force dual-axis wheel zoom everywhere (axis strips included).

    A burst of consecutive wheel events (< 0.5 s apart) is one undo step.
    """
    global _last_wheel_push
    now = time.time()
    if now - _last_wheel_push > 0.5:
        zoom_history.append(tuple(tuple(r) for r in vb.viewRange()))
    _last_wheel_push = now
    return _orig_vb_wheel(ev, axis=None)


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
            update_title_from_state()
        else:
            drag_measure_show(p0, p1)
            update_title_from_state()
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
            and _evt_active()
            and (ev.modifiers() & pg.QtCore.Qt.ShiftModifier)):
        # Events selection gesture: Shift + left-drag draws the Y-range band
        # vertically (live preview; a vertical extent below 3% of the view
        # height is treated as an accidental drag and ignored on release).
        ev.accept()
        p0 = vb.mapSceneToView(ev.buttonDownScenePos())
        p1 = vb.mapSceneToView(ev.scenePos())
        if ev.isFinish():
            band_drag_finish(p0.y(), p1.y())
        else:
            band_drag_update(p0.y(), p1.y())
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


def load(file_name):
    """Load a new .dat file into the browser.
    """
    global bundle, tree_items
    
    # Read the bundle header
    # (no data is read at this time)
    bundle = heka_reader.Bundle(file_name)
    
    file_name = os.path.abspath(file_name)
    settings.setValue('last_dir', os.path.dirname(file_name))
    win.setWindowTitle(file_name)
    path_label.setText(file_name)
    
    # Clear the tree and update to show the structure provided in the embedded
    # .pul file
    tree.clear()
    update_tree(tree.invisibleRootItem(), [])
    replot()
    

def update_tree(root_item, index):
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
        update_tree(item, index + [i])


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


def build_stitched(entries):
    """Concatenate cached (x, y, label, trace) entries end-to-end on a
    continuous time axis.

    Each segment continues at the previous segment's end time using its own
    XInterval, so traces with different sampling rates or lengths mix fine.
    The y arrays come from the last_data cache (each read from disk once);
    the x axes are rebuilt from the running time. Returns
    (x, y, seams, segments): seams holds the junction times between
    consecutive segments (len(entries) - 1 entries); segments holds
    (x_start, x_end, label) per segment for the measure cursor lookup.
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
    global cur_xunit, cur_yunit, last_snap, stitch_segments, last_data
    global _stitch_active, _stitch_cache, _prep_cache, _stitched_display
    global _data_stamp, _band_cleared
    plot.clear()
    legend.clear()
    data_tree.clear()
    clear_meas()
    clear_amp_regions()
    add_crosshair()
    add_zoom_regions()
    add_readout()
    add_detect_items()
    zoom_history.clear()
    stitch_segments = []
    _stitch_active = False
    _stitch_cache = None
    _prep_cache = None
    _stitched_display = None
    _band_cleared = False
    _data_stamp += 1

    selected = tree.selectedItems()
    if len(selected) < 1 or bundle is None:
        last_data = []
        run_detection()
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
    _data_stamp += 1
    for index, trace in items:
        data = bundle.data[list(index)]
        time = np.linspace(trace.XStart, trace.XStart + trace.XInterval * (len(data)-1), len(data))
        last_data.append((time, data, trace_label(index), trace))

    if len(items) > 20:
        legend.hide()
    else:
        legend.show()

    if stitch_btn.isChecked() and len(items) > 1:
        trace0 = items[0][1]
        plot.setLabels(bottom=('Time', trace0.XUnit), left=(trace0.Label, trace0.YUnit))
        cur_xunit = trace0.XUnit
        cur_yunit = trace0.YUnit
        x, y, seams, seg_infos = build_stitched(last_data)
        stitch_segments = seg_infos
        _stitch_active = True
        _stitched_display = (x, y)
        plot.plot(x, y, pen=pg.mkPen(THEME['cycle'][0], width=1), name='stitched ×%d' % len(items))
        for t in seams:
            line = pg.InfiniteLine(pos=t, angle=90, movable=False,
                                   pen=pg.mkPen(THEME['seam'], width=1, style=pg.QtCore.Qt.DashLine))
            plot.getPlotItem().addItem(line, ignoreBounds=True)
    else:
        for i, (x, y, label, trace) in enumerate(last_data):
            plot.setLabels(bottom=('Time', trace.XUnit), left=(trace.Label, trace.YUnit))
            cur_xunit = trace.XUnit
            cur_yunit = trace.YUnit
            plot.plot(x, y, pen=trace_pen(i, len(items)), name=label)

    fit_view()
    if _evt_active() and not _band_placed and not _band_cleared:
        _place_band()
    run_detection()
    amp_recompute()


# replot when ever the user selects a new item
tree.itemSelectionChanged.connect(replot)


def stitch_toggled(checked):
    settings.setValue('stitch', checked)
    replot()


stitch_btn.toggled.connect(stitch_toggled)


# --- Distribution panel: amplitude histograms + threshold-band events --------
#   Amp    checkable: left-drag in the plot adds time regions; the Amplitude
#          tab shows the all-point histogram of the raw samples inside them.
#   Detect checkable: a draggable horizontal band; what counts as an event
#          is set by the mode (default: samples inside the band). The Events
#          tab shows dwell / level histograms and highlights the events on
#          the traces. Analysis always runs on the per-trace raw arrays in
#          last_data (never on the stitched display curve) through the pure
#          functions in heka/analysis.py.

last_data = []           # (x, y, label, trace) of every displayed trace
amp_regions = []         # committed time-region items
_pending_region = None   # region currently being rubber-band dragged
_evt_overlays = []       # event highlight curves in the main plot
_stitch_active = False   # Stitch on -> detection runs on the continuous axis
_stitch_cache = None     # (_data_stamp, head_s, smooth_ms, (x, y)) stitch axis
_prep_cache = None       # (_data_stamp, head_s, smooth_ms, [...]) per trace
_stitched_display = None # raw stitched (x, y) shown in the main plot
_data_stamp = 0          # bumped on every last_data rebind (cache keys)
_band_placed = False     # Y-range band placed (auto or by the user)?
_band_cleared = False    # [清空] pressed: stay silent until a new band is drawn


def _tint(hexcolor, alpha):
    c = pg.QtGui.QColor(hexcolor)
    c.setAlpha(alpha)
    return pg.mkBrush(c)


def analysis_segments(stride=1, head_s=0.0, smooth_ms=0.0):
    """(t, y) segments for heka.analysis.

    Default: one segment per displayed trace -- sweeps of one series share
    their time axis, so blind concatenation would fabricate events at the
    junctions. With Stitch on, the traces are instead concatenated on their
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
    global _stitch_cache, _prep_cache
    prepped = _prepped(head_s, smooth_ms)
    if _stitch_active and prepped:
        if (_stitch_cache is None
                or _stitch_cache[:3] != (_data_stamp, head_s, smooth_ms)):
            xs, ys, t = [], [], None
            for x, y, label, trace, n_full in prepped:
                # place each sweep on the same timeline as the displayed
                # stitch: advance by the FULL sweep duration (head slicing
                # only hides samples, it must not compress the axis)
                if t is None:
                    t = float(trace.XStart)
                dt = float(trace.XInterval)
                xs.append(t + (x - float(trace.XStart)))
                ys.append(y)
                t += n_full * dt
            _stitch_cache = (_data_stamp, head_s, smooth_ms,
                             (np.concatenate(xs), np.concatenate(ys)))
        x, y = _stitch_cache[3]
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
    n_full = the ORIGINAL sample count, so the stitch accumulation can
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


# Detect band: two draggable lines + translucent fill; the region item is
# re-attached by add_detect_items() after every plot.clear()
band_region = pg.LinearRegionItem(values=(0.0, 1.0), orientation='horizontal',
                                  movable=True, brush=_tint(THEME['band'], 60),
                                  pen=pg.mkPen(THEME['band'], width=1))
band_region.setZValue(-5)
band_region.hide()


def add_detect_items():
    """Re-attach the Detect band to the plot (plot.clear() detaches it)."""
    pi = plot.getPlotItem()
    if band_region.scene() is None:
        pi.addItem(band_region, ignoreBounds=True)
    band_region.setVisible(_evt_active())


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


# -- Distribution panel widgets -------------------------------------------------

sec_dist = Collapsible('Distribution')
dist_tabs = pg.QtWidgets.QTabWidget()
sec_dist.add_widget(dist_tabs)
dist_split.addWidget(sec_dist)

# Amplitude tab: one histogram per region, Y axis linked to the main plot so
# a histogram peak sits at the same height as its current level in the trace
amp_tab = pg.QtWidgets.QWidget()
amp_lay = pg.QtWidgets.QVBoxLayout(amp_tab)
amp_lay.setContentsMargins(4, 4, 4, 4)
amp_lay.setSpacing(3)
amp_ctrl = pg.QtWidgets.QHBoxLayout()
amp_clear_btn = pg.QtWidgets.QPushButton('清空区域')
amp_ruler_btn = pg.QtWidgets.QPushButton('峰标尺')
amp_ruler_btn.setCheckable(True)
amp_ruler_btn.setToolTip('在直方图上放置两条可拖动的竖线 A/B，\n'
                         '实时读取两个峰的位置与它们的差 Δ')
amp_auto_bins = pg.QtWidgets.QCheckBox('auto bins')
amp_auto_bins.setChecked(settings.value('amp/bins_auto', True, type=bool))
amp_bins = NumericEdit(float(settings.value('amp/bins', 150.0, type=float)),
                       8, 4096, commit_on='finish')
amp_follow = pg.QtWidgets.QCheckBox('range = view Y')
amp_follow.setChecked(settings.value('amp/follow', False, type=bool))
for _w in (amp_clear_btn, amp_ruler_btn, amp_auto_bins,
           pg.QtWidgets.QLabel('bins'), amp_bins, amp_follow):
    amp_ctrl.addWidget(_w)
amp_ctrl.addStretch(1)
amp_lay.addLayout(amp_ctrl)
amp_list_widget = pg.QtWidgets.QWidget()          # one row per committed region
amp_list_lay = pg.QtWidgets.QVBoxLayout(amp_list_widget)
amp_list_lay.setContentsMargins(0, 0, 0, 0)
amp_list_lay.setSpacing(1)
amp_lay.addWidget(amp_list_widget)
amp_plot = pg.PlotWidget()
amp_lay.addWidget(amp_plot, 1)
amp_ruler_lbl = pg.QtWidgets.QLabel('')
amp_lay.addWidget(amp_ruler_lbl)
amp_stats = pg.QtWidgets.QLabel('')
amp_stats.setWordWrap(True)
amp_lay.addWidget(amp_stats)
dist_tabs.addTab(amp_tab, 'Amplitude')

# Peak ruler: two draggable vertical markers on the amplitude histogram for
# reading peak positions and their difference (dI between two states)
ruler_a = pg.InfiniteLine(angle=90, movable=True,
                          pen=pg.mkPen(THEME['A'], width=1))
ruler_b = pg.InfiniteLine(angle=90, movable=True,
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
        x0, x1 = amp_plot.getPlotItem().getViewBox().viewRange()[0]
        if not x0 <= ruler_a.value() <= x1:
            ruler_a.setValue(x0 + 0.3 * (x1 - x0))
        if not x0 <= ruler_b.value() <= x1:
            ruler_b.setValue(x0 + 0.7 * (x1 - x0))
    _update_ruler()

# Events tab: laid out in workflow order -- enable, Y range, edge rules,
# then the headline result and the histograms
evt_tab = pg.QtWidgets.QWidget()
evt_lay = pg.QtWidgets.QVBoxLayout(evt_tab)
evt_lay.setContentsMargins(4, 4, 4, 4)
evt_lay.setSpacing(2)

evt_ctrl0 = pg.QtWidgets.QHBoxLayout()
_evt_hint = pg.QtWidgets.QLabel('本页已激活：Shift+竖向拖拽画出 Y 范围带（普通拖拽 = 平移，'
                                '轴条拖拽 = 缩放）；绿色 = 判定为事件的采样段；'
                                '带子圈住事件电流水平，不要圈基线')
_evt_hint.setStyleSheet('color:#999;')
evt_ctrl0.addWidget(_evt_hint)
evt_ctrl0.addStretch(1)
evt_lay.addLayout(evt_ctrl0)

evt_ctrl1 = pg.QtWidgets.QHBoxLayout()          # workflow step 1: the Y range
evt_lo = NumericEdit(0.0, -1e6, 1e6, commit_on='finish')
evt_hi = NumericEdit(1.0, -1e6, 1e6, commit_on='finish')
evt_ylab = pg.QtWidgets.QLabel('(%s)' % cur_yunit)
evt_lo.setToolTip('Y 范围下沿，单位自动取可读的 SI 前缀（如 pA），与图上带子双向同步')
for _w in (pg.QtWidgets.QLabel('<b>Y 范围</b>  lo'), evt_lo,
           pg.QtWidgets.QLabel('–  hi'), evt_hi, evt_ylab,
           pg.QtWidgets.QLabel('<span style="color:#999">(与主图青色带双向同步，可直接输入)</span>')):
    evt_ctrl1.addWidget(_w)
evt_ctrl1.addStretch(1)
evt_lay.addLayout(evt_ctrl1)

evt_ctrl2 = pg.QtWidgets.QHBoxLayout()          # workflow step 2: edge rules
evt_mode = pg.QtWidgets.QComboBox()
evt_mode.addItems(['inside', 'outside', 'below', 'above'])
evt_mode.setCurrentText(settings.value('dist/mode', 'inside', type=str))
evt_k = NumericEdit(float(settings.value('dist/k', 3.0, type=float)),
                    0.0, 1e4, commit_on='finish')
evt_tmin = NumericEdit(float(settings.value('dist/t_min_ms', 0.1, type=float)),
                       0.0, 1e4, commit_on='finish')
evt_merge = NumericEdit(float(settings.value('dist/merge', 0.0, type=float)),
                        0.0, 1e4, commit_on='finish')
evt_head = NumericEdit(float(settings.value('dist/head', 10.0, type=float)),
                       0.0, 1e4, commit_on='finish')
evt_smooth = NumericEdit(float(settings.value('dist/smooth', 0.0, type=float)),
                         0.0, 1e4, commit_on='finish')
evt_duty = NumericEdit(float(settings.value('dist/duty', 0.5, type=float)),
                       0.0, 1.0, commit_on='finish')
evt_dwell_log = pg.QtWidgets.QCheckBox('对数X')
evt_dwell_log.setChecked(settings.value('dist/dwell_log', False, type=bool))
evt_dwell_log.setToolTip('dwell 直方图用对数 bin + 对数轴（默认线性）；\n'
                         '1-CDF 视图恒为对数-对数')
evt_ccdf = pg.QtWidgets.QCheckBox('1-CDF (log-log)')
evt_ccdf.setChecked(settings.value('dist/ccdf', False, type=bool))

# detailed per-parameter explanations; every label AND its field carry the
# same tooltip (users hover the text, not the box)
_EVT_TIP_MODE = ('事件语义——四种模式共用同一套滞回/时长逻辑：\n'
                 'inside = 带内即事件（默认；不假定基线，带子圈住哪个电平，那段驻留就是事件）\n'
                 'outside = 带外即事件（基线在带中，上下双向尖峰）\n'
                 'below = y < hi 即事件（经典向下阻断，只用上边一条线）\n'
                 'above = y > lo 即事件（向上尖峰）')
_EVT_TIP_K = ('滞回 k·σ —— 事件结束的防抖门槛。\n'
              '噪声会让信号在带沿反复进出；纯"进带=开始 / 出带=结束"会把一个真实\n'
              '事件拆成大量碎片。滞回要求信号明确离开带宽 k 倍噪声 σ 才认定结束\n'
              '（σ 由相邻采样差自动稳健估计，不受事件尖峰影响）。\n'
              '默认 3 适合多数数据；噪声大或 spike 密可加到 5–8；0 = 完全关闭滞回')
_EVT_TIP_TMIN = ('最短时长 —— 短于该时长的事件直接丢弃。\n'
                 '滤掉电容毛刺与 spike 穿过带沿产生的 ~0.1–0.3 ms 碎片；\n'
                 '两态驻留通常 ≥ 数 ms，所以 0.1–1 ms 很安全，只关心长驻留可加大到 10。\n'
                 '内部按原始采样率换算成点数，开启平滑后自动再除以窗宽')
_EVT_TIP_MERGE = ('合并 —— 相邻事件间隔小于该值时并成一个，把被 spike 短暂打断的\n'
                  '真实驻留重新接上。\n'
                  '⚠ 危险：spike 越密、碎片间隔越短，合并值过大会把整段信号串成一个\n'
                  '巨型"假事件"（事件电平被带外间隙稀释）。spike 密集时保持 0，\n'
                  '改用「检测平滑」压掉 spike +「带内占比」兜底')
_EVT_TIP_HEAD = ('忽略开头 —— 每条 sweep 开头切掉这段时间，规避电容充放电瞬态\n'
                 '（本数据瞬态可达 ±2 nA，不切会在每个 sweep 开头产生假事件）。\n'
                 '10 ms 覆盖绝大多数情况；Stitch 模式下每条 sweep 的开头都会切')
_EVT_TIP_SMOOTH = ('检测平滑 —— 检测前按窗宽做中位数压缩。\n'
                   '比窗窄的 spike 被压平、比窗宽的电平台完整保留——spike 密集的\n'
                   '两态数据的关键参数（建议 1–2 ms）。不开它时每个 spike 穿带都\n'
                   '产生碎片；开了它 dwell/边界精度降为窗宽粒度（1 ms 窗 → 1 ms）。0 = 关闭')
_EVT_TIP_DUTY = ('带内占比 —— 合并后事件跨度内真正在带内的时间占比，\n'
                 '低于该值即丢弃：spike 顶部碎片链占比通常 ~3%，真实驻留 >50%，\n'
                 '0.5 一刀分开。只对发生过合并的事件生效；0 = 关闭该过滤')
_evt_params = [
    ('模式', evt_mode, _EVT_TIP_MODE),
    ('滞回 k·σ', evt_k, _EVT_TIP_K),
    ('最短 (ms)', evt_tmin, _EVT_TIP_TMIN),
    ('合并 (s)', evt_merge, _EVT_TIP_MERGE),
    ('忽略开头 (ms)', evt_head, _EVT_TIP_HEAD),
    ('检测平滑 (ms)', evt_smooth, _EVT_TIP_SMOOTH),
    ('带内占比 ≥', evt_duty, _EVT_TIP_DUTY),
    ('对数X', evt_dwell_log, evt_dwell_log.toolTip()),
]
evt_ctrl2.addWidget(pg.QtWidgets.QLabel('<b>边沿判定</b>'))
for _name, _field, _tip in _evt_params:
    _lab = pg.QtWidgets.QLabel(_name)
    _lab.setToolTip(_tip)
    _field.setToolTip(_tip)
    evt_ctrl2.addWidget(_lab)
    evt_ctrl2.addWidget(_field)
evt_ccdf.setToolTip('dwell 直方图切换为存活函数 1−CDF（log-log），\n'
                    '用于区分幂律与多指数驻留分布')
evt_ctrl2.addWidget(evt_ccdf)
evt_ctrl2.addStretch(1)
evt_lay.addLayout(evt_ctrl2)

evt_ctrl3 = pg.QtWidgets.QHBoxLayout()          # workflow step 3: the result
evt_headline = pg.QtWidgets.QLabel('')
evt_clear_btn = pg.QtWidgets.QPushButton('清空')
evt_clear_btn.setToolTip('清除全部检测结果并隐藏带子；\n'
                         '之后切走再切回本标签页也不会自动放带，\n'
                         '直到重新画出（Shift+竖向拖拽或输入数值）新的范围')
evt_table_btn = pg.QtWidgets.QPushButton('事件表')
evt_csv_btn = pg.QtWidgets.QPushButton('导出 CSV')
evt_ctrl3.addWidget(evt_headline)
evt_ctrl3.addStretch(1)
evt_ctrl3.addWidget(evt_clear_btn)
evt_ctrl3.addWidget(evt_table_btn)
evt_ctrl3.addWidget(evt_csv_btn)
evt_lay.addLayout(evt_ctrl3)

evt_split = pg.QtWidgets.QSplitter(pg.QtCore.Qt.Horizontal)
dwell_plot = pg.PlotWidget()
dwell_plot.getPlotItem().setLogMode(x=True)
level_plot = pg.PlotWidget()
evt_split.addWidget(dwell_plot)
evt_split.addWidget(level_plot)
evt_split.setStretchFactor(0, 1)
evt_split.setStretchFactor(1, 1)
evt_lay.addWidget(evt_split, 1)

# Measure lines: one draggable A/B pair on each Events histogram (always on
# while the tab is active); the readout line reports both pairs + deltas
dwell_ma = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(THEME['A'], width=1))
dwell_mb = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(THEME['B'], width=1))
level_ma = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(THEME['A'], width=1))
level_mb = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(THEME['B'], width=1))
evt_meas_lbl = pg.QtWidgets.QLabel('')
evt_meas_lbl.setStyleSheet('color:#666;')
evt_lay.addWidget(evt_meas_lbl)

evt_stats = pg.QtWidgets.QLabel('')
evt_stats.setWordWrap(True)
evt_lay.addWidget(evt_stats)
dist_tabs.addTab(evt_tab, 'Events')


# -- Analysis pipeline ------------------------------------------------------------

def amp_values(r0, r1, stride):
    """Raw samples of the displayed data inside a time region.

    With Stitch on the regions live on the continuous stitched axis, so the
    values come from the cached stitched raw arrays; otherwise per trace.
    """
    if _stitch_active and _stitched_display is not None:
        x, y = _stitched_display
        v = y[(x >= r0) & (x <= r1)]
        if stride > 1:
            v = v[::stride]
        return [v] if v.size else []
    vals = []
    for x, y, label, trace in last_data:
        v = y[(x >= r0) & (x <= r1)]
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
        amp_stats.setText('<span style="color:#999">本页已激活：按住 <b>Shift</b> 在主图'
                          '内<b>横向拖拽</b>框选时间区域（普通拖拽 = 平移，轴条拖拽 = 缩放）；'
                          '切到其他标签页会清除全部区域。</span>')
        return
    stride = 1 if full else max(1, total_points() // 200000)
    regs = [r.getRegion() for r in amp_regions]
    per_region = [amp_values(r0, r1, stride) for r0, r1 in regs]
    pooled = [v for vals in per_region for v in vals]
    if not pooled:
        amp_stats.setText('regions cover no samples')
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
    f, prefix = _yunit_scale()
    unit_s = '%s%s' % (prefix, cur_yunit)
    for k, ((r0, r1), vals) in enumerate(zip(regs, per_region)):
        if not vals:
            continue
        v = np.concatenate(vals)
        _, counts, under, over = analysis.all_point_histogram(
            v, bins=edges)
        frac = counts * 100.0 / max(1, v.size)
        maxc = max(maxc, float(frac.max()))
        color = THEME['cycle'][k % len(THEME['cycle'])]
        # vertical histogram: X = current (display unit), Y = % of samples
        pi.addItem(pg.BarGraphItem(
            x0=edges[:-1] / f, x1=edges[1:] / f,
            y0=np.zeros(len(frac)), y1=frac,
            brush=_tint(color, 150), pen=pg.mkPen(color, width=1)))
        p1, p99 = np.percentile(v, [1, 99])
        lines.append(
            '<span style="color:%s">#%d: N=%d  mean=%s  σ=%s  '
            'p1..p99=%s .. %s  out-of-range=%d</span>'
            % (color, k, v.size, fmt_si(float(v.mean()), cur_yunit),
               fmt_si(float(v.std()), cur_yunit), fmt_si(float(p1), cur_yunit),
               fmt_si(float(p99), cur_yunit), under + over))
    amp_plot.setLabels(bottom=unit_s, left='% of region samples')
    if maxc > 0:
        pi.getViewBox().setYRange(0, maxc * 1.1, padding=0)
    pi.getViewBox().setXRange(edges[0] / f, edges[-1] / f, padding=0)
    amp_stats.setText('<br>'.join(lines))
    _update_ruler()


def amp_preview():
    amp_recompute(full=False)


def _attach_evt_meas():
    """(Re-)attach the measure line pairs after a histogram rebuild and
    give unset lines a sensible start position inside the view."""
    for pi, (ma, mb) in ((dwell_plot.getPlotItem(), (dwell_ma, dwell_mb)),
                         (level_plot.getPlotItem(), (level_ma, level_mb))):
        for ln in (ma, mb):
            if ln.scene() is None:
                pi.addItem(ln, ignoreBounds=True)
        x0, x1 = pi.getViewBox().viewRange()[0]
        if not x0 <= ma.value() <= x1:
            ma.setValue(x0 + 0.3 * (x1 - x0))
        if not x0 <= mb.value() <= x1:
            mb.setValue(x0 + 0.7 * (x1 - x0))


def _update_evt_meas(*_):
    if not _evt_active():
        evt_meas_lbl.setText('')
        return
    f, prefix = _yunit_scale()
    unit_s = '%s%s' % (prefix, cur_yunit)

    def _pair(va, vb_, unit):
        return 'A=%s B=%s Δ=%s' % (fmt_si(va, unit), fmt_si(vb_, unit),
                                   fmt_si(abs(vb_ - va), unit))

    # the measure lines live in DISPLAY units: scale back to the native axis
    # before formatting so siFormat picks the prefix exactly once
    lvl = lambda v: fmt_si(v * f, cur_yunit)
    lvl_txt = 'A=%s B=%s Δ=%s' % (lvl(level_ma.value()), lvl(level_mb.value()),
                                  lvl(abs(level_mb.value() - level_ma.value())))
    evt_meas_lbl.setText('dwell: %s &nbsp;│&nbsp; level: %s'
                         % (_pair(dwell_ma.value(), dwell_mb.value(), 's'),
                            lvl_txt))


def update_event_hists(events):
    """Redraw the Events histograms: dwell (linear by default, log optional,
    or 1-CDF) and the absolute event-level histogram, in display units."""
    dwell_pi = dwell_plot.getPlotItem()
    level_pi = level_plot.getPlotItem()
    dwell_pi.clear()
    level_pi.clear()
    if not len(events):
        _attach_evt_meas()
        _update_evt_meas()
        return
    f, prefix = _yunit_scale()
    unit_s = '%s%s' % (prefix, cur_yunit)
    if evt_ccdf.isChecked():
        sv = analysis.survival_function(events['dwell'])
        if sv is not None:
            dwell_pi.setLogMode(x=True, y=True)
            dwell_pi.addItem(pg.PlotCurveItem(
                sv[0], sv[1], pen=pg.mkPen(THEME['event'], width=2)))
            dwell_plot.setLabels(bottom='dwell (s, log-log)', left='S(t) = 1-CDF')
    elif evt_dwell_log.isChecked():
        dwell_pi.setLogMode(x=True, y=False)
        hist = analysis.log_histogram(events['dwell'])
        if hist is not None:
            edges, counts = hist
            # stepMode='center' takes the bin EDGES (len = N+1) and draws
            # each bar centred on its bin
            dwell_pi.addItem(pg.PlotCurveItem(
                edges, counts, stepMode='center',
                pen=pg.mkPen(THEME['event'], width=1),
                fillLevel=0, brush=_tint(THEME['event'], 120)))
            dwell_plot.setLabels(bottom='dwell (s, log bins)', left='events')
    else:
        dwell_pi.setLogMode(x=False, y=False)
        hist = analysis.all_point_histogram(events['dwell'])
        if hist is not None:
            edges, counts, under, over = hist
            dwell_pi.addItem(pg.PlotCurveItem(
                edges, counts, stepMode='center',
                pen=pg.mkPen(THEME['event'], width=1),
                fillLevel=0, brush=_tint(THEME['event'], 120)))
            dwell_plot.setLabels(bottom='dwell (s)', left='events')
    hist = analysis.all_point_histogram(events['y_level'])
    if hist is not None:
        edges, counts, under, over = hist
        level_pi.addItem(pg.BarGraphItem(
            x0=edges[:-1] / f, x1=edges[1:] / f,
            y0=np.zeros(len(counts)), y1=counts,
            brush=_tint(THEME['event'], 140), pen=pg.mkPen(THEME['event'], width=1)))
        level_plot.setLabels(bottom='level (%s)' % unit_s, left='events')
    _attach_evt_meas()
    _update_evt_meas()


def run_detection(full=True):
    """Threshold-band event detection: overlay on the traces + Events tab.

    full=False runs on a strided subsample (live band drags); release
    recomputes in full. Raises of heka.analysis (bad band vs hysteresis)
    land in the stats label instead of a dialog.
    """
    global _evt_overlays, _last_events, _last_labels
    f, prefix = _yunit_scale()
    evt_ylab.setText('(%s%s)' % (prefix, cur_yunit))
    pi = plot.getPlotItem()
    for it in _evt_overlays:
        if it.scene() is not None:
            pi.removeItem(it)
    _evt_overlays = []
    if not _evt_active() or not last_data or not _band_placed:
        band_region.hide()
        dwell_plot.getPlotItem().clear()
        level_plot.getPlotItem().clear()
        _last_events = None
        if _band_cleared:
            evt_headline.setText('<b>已清空</b>')
            evt_stats.setText('<span style="color:#999">已清空：按住 Shift 在主图内'
                              '<b>竖向拖拽</b>画出新的 Y 范围带后重新检测；切到其他标签页'
                              '再切回也不会自动放带。</span>')
        else:
            evt_headline.setText('<b>0 个事件</b>')
            evt_stats.setText('<span style="color:#999">切到本标签页即启用检测：按住 Shift '
                              '在主图内<b>竖向拖拽</b>画出 Y 范围带（或拖带子边线、输入数值），'
                              '信号进入带内=事件开始、离开带=事件结束；切走后自动停止。</span>')
        return
    band_region.show()
    lo, hi = band_region.getRegion()
    head_s = evt_head.value() * 1e-3
    smooth_ms = evt_smooth.value()
    # 最短 (ms) -> 原始采样点数；平滑压缩后检测序列变稀，再除以窗宽
    dt0 = float(last_data[0][3].XInterval) if last_data else 0.0
    t_min_pts = max(1, int(round(evt_tmin.value() * 1e-3 / dt0))) if dt0 > 0 else 1
    w = max(1, int(round(smooth_ms * 1e-3 / dt0))) if (dt0 > 0 and smooth_ms > 0) else 1
    t_min_dec = max(1, int(round(t_min_pts / w)))
    total = total_points()
    stride = 1 if full else max(1, total // 200000)
    segs = analysis_segments(stride, head_s=head_s, smooth_ms=smooth_ms)
    # the overlay is a visual indicator only: cap it to ~2M points so a
    # whole-Group view (tens of millions of samples) stays fluid. Detection
    # and all statistics below always run on the full-resolution segs.
    if stride == 1 and total > 2000000:
        osegs = analysis_segments(max(1, total // 2000000), head_s=head_s,
                                  smooth_ms=smooth_ms)
    else:
        osegs = segs
    try:
        res = analysis.detect_events_segments(
            segs, mode=evt_mode.currentText(), lo=lo, hi=hi, h=None,
            k=evt_k.value(), t_min=t_min_dec,
            merge_gap=evt_merge.value(), duty_min=evt_duty.value())
    except ValueError as exc:
        dwell_plot.getPlotItem().clear()
        level_plot.getPlotItem().clear()
        _last_events = None
        evt_headline.setText('<b>0 个事件</b>')
        evt_stats.setText('<span style="color:%s">%s</span>' % (THEME['A'], exc))
        return
    events = res.events
    _last_events = events
    _last_labels = [label for _, _, label, _ in last_data]

    # highlight the event stretches on the displayed traces (NaN outside
    # events + connect='finite' breaks the line there)
    for k, (x, y) in enumerate(osegs):
        ev = events[events['i_seg'] == k]
        if not len(ev):
            continue
        mask = np.zeros(len(x), dtype=bool)
        lo_i = np.searchsorted(x, ev['t_start'], side='left')
        hi_i = np.searchsorted(x, ev['t_end'], side='right')
        for a, b in zip(lo_i, hi_i):
            mask[a:max(b, a + 1)] = True
        curve = pg.PlotDataItem(x, np.where(mask, y, np.nan),
                                pen=pg.mkPen(THEME['event'], width=2),
                                connect='finite')
        pi.addItem(curve, ignoreBounds=True)
        _evt_overlays.append(curve)

    update_event_hists(events)
    dur = sum(float(x[-1] - x[0]) for x, _ in segs if len(x) > 1)
    if len(events) and dur > 0:
        head = '<b>发现 %d 个事件 · %s</b>' % (len(events),
                                              fmt_si(len(events) / dur, 'Hz'))
    else:
        head = '<b>0 个事件</b>'
    frac = analysis.in_band_fraction(segs, evt_mode.currentText(), lo, hi)
    if frac is not None and frac > 0.5:
        head += ('<br><span style="color:%s">信号 %.0f%% 的时间在带内：带子圈住了'
                 '基线/主态，inside 模式会把它整体判成事件——请把带子收窄到'
                 '单一电平台</span>' % (THEME['A'], frac * 100))
    if len(events) > 50000:
        head += ('<br><span style="color:%s">事件数异常大（%d）：建议开启'
                 '「检测平滑」1–2 ms、增大「最短 (ms)」，并检查 Y 范围是否'
                 '圈住了基线</span>' % (THEME['A'], len(events)))
    evt_headline.setText(head)
    if len(events):
        txt = ('dwell: median=%s  mean=%s   level: median=%s'
               % (fmt_si(float(np.median(events['dwell'])), 's'),
                  fmt_si(float(events['dwell'].mean()), 's'),
                  fmt_si(float(np.median(events['y_level'])), cur_yunit)))
    else:
        txt = ''
    notes = ['h=%s (= %.4g·σ, σ=%s)'
             % (fmt_si(res.h, cur_yunit), res.h / res.sigma if res.sigma else 0,
                fmt_si(res.sigma, cur_yunit))]
    if res.boundary_discarded:
        notes.append('%d 个边界事件被丢弃（进入或离开未被观测到，即事件跨越数据首尾）'
                     % res.boundary_discarded)
    if res.duty_discarded:
        notes.append('%d 个合并事件因带内占比 < %.0f%% 被丢弃'
                     '（多为 spike 顶部碎片链）'
                     % (res.duty_discarded, evt_duty.value() * 100))
    evt_stats.setText(txt + '<br>' + '<br>'.join(notes))


def _evt_clear():
    """清空：remove all results and hide the band. Detection stays off and
    the tab stays silent on re-entry until a new band is drawn."""
    global _band_placed, _band_cleared
    _band_placed = False
    _band_cleared = True
    band_region.hide()
    run_detection()


def clear_analysis():
    """Clear Amp regions, event overlays and panel contents. The Detect band
    stays while Detect is on (it is a mode control, not a result)."""
    clear_amp_regions()
    run_detection()
    amp_recompute()


def _place_band():
    """Auto-place the Y-range band on the event side of the amplitude
    distribution -- never on the baseline: an inside-mode band hugging the
    baseline flags half the trace as "events" (the G0 S19 green-wash bug).
    No-op without data; remembers that the band was placed."""
    global _band_placed, _band_syncing
    if not last_data:
        return
    pooled = np.concatenate([y[::max(1, len(y) // 100000)]
                             for _, y, _, _ in last_data])
    p1, p25, p50, p75, p99 = np.percentile(pooled, [1, 25, 50, 75, 99])
    if p99 - p50 >= p50 - p1:
        rng = (float(p75), float(p99))            # heavier upper tail
    else:
        rng = (float(p1), float(p25))             # heavier lower tail
    if rng[1] > rng[0]:
        _band_syncing = True
        try:
            band_region.setRegion(rng)
        finally:
            _band_syncing = False
        _band_placed = True
        _sync_fields_from_band()


def _amp_active():
    """Amplitude mode is armed: its tab is open and the panel is expanded."""
    return (not sec_dist.is_collapsed()
            and dist_tabs.currentIndex() == 0)


def _evt_active():
    """Detection is armed: its tab is open and the panel is expanded."""
    return (not sec_dist.is_collapsed()
            and dist_tabs.currentIndex() == 1)


_dist_tab_prev = [0]


def _dist_view_changed(*_):
    """Tab switch / panel collapse: opening Amplitude or Events activates
    that mode; leaving Amplitude deletes its regions, leaving Events (or
    collapsing the panel) stops the detection and clears its highlights.
    Re-entering restores the band (and re-runs)."""
    idx = dist_tabs.currentIndex()
    was = _dist_tab_prev[0]
    if was == 0 and idx != 0:
        clear_amp_regions()             # 切走即清除全部区域（用户要求）
    amp_recompute()
    if _evt_active():
        band_region.setMovable(True)
        if not _band_placed and not _band_cleared:
            _place_band()                     # [清空] keeps the tab silent
    _dist_tab_prev[0] = idx
    run_detection()                     # off-state hides band + clears results


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


# -- Y-range numeric fields <-> threshold band, two-way sync --------------------

_band_syncing = False

_yunit_cache = None   # (_data_stamp, factor, si_prefix)


def _yunit_scale():
    """(factor, prefix) for the Y-range fields: an SI prefix chosen so the
    band numbers are readable (an A-native trace is edited in pA)."""
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


def _sync_fields_from_band(*_):
    global _band_placed, _band_cleared
    _band_placed = True                       # the band was moved: user intent
    _band_cleared = False
    if _band_syncing:
        return
    lo, hi = band_region.getRegion()
    f, _ = _yunit_scale()
    evt_lo.setText(evt_lo._fmt(lo / f))       # native axis -> display unit
    evt_hi.setText(evt_hi._fmt(hi / f))


def _sync_band_from_fields(*_):
    global _band_syncing, _band_placed, _band_cleared
    if _band_syncing:
        return
    lo, hi = sorted((evt_lo.value(), evt_hi.value()))
    if not hi > lo:
        return
    f, _ = _yunit_scale()
    _band_syncing = True
    _band_placed = True
    try:
        band_region.setRegion((lo * f, hi * f))   # display unit -> native axis
        run_detection()
    finally:
        _band_syncing = False


def band_drag_update(y0, y1):
    """Shift+drag Events gesture: live preview of the Y-range band.

    Guarded so the programmatic setRegion does not trigger the band's own
    signals (which would run a full detection on every mouse-move)."""
    global _band_syncing
    lo, hi = sorted((float(y0), float(y1)))
    _band_syncing = True
    try:
        band_region.setRegion((lo, hi))
    finally:
        _band_syncing = False
    band_region.show()


def band_drag_finish(y0, y1):
    """Commit the drawn band: extents below 3% of the view height are
    treated as accidental drags and ignored (the previous band stays)."""
    global _band_placed, _band_cleared, _band_syncing
    view_h = vb.viewRange()[1][1] - vb.viewRange()[1][0]
    lo, hi = sorted((float(y0), float(y1)))
    if hi - lo <= 0.03 * view_h:
        return
    _band_syncing = True
    try:
        band_region.setRegion((lo, hi))
    finally:
        _band_syncing = False
    _band_placed = True
    _sync_fields_from_band()
    run_detection()


# -- Event table + CSV export -----------------------------------------------------

_evt_dialog = None
_last_events = None
_last_labels = []


def _write_events_csv(path):
    """Full event list as CSV (the on-screen table is capped; this is not)."""
    if _last_events is None or not len(_last_events):
        return False
    np.savetxt(path, _last_events, delimiter=',',
               header='t_start,t_end,dwell,y_level,i_seg', comments='')
    return True


def _export_events_csv():
    if _last_events is None or not len(_last_events):
        return
    path, _ = pg.QtWidgets.QFileDialog.getSaveFileName(
        win, '导出事件 CSV',
        os.path.join(settings.value('last_dir', ''), 'events.csv'),
        'CSV (*.csv)')
    if path:
        _write_events_csv(path)


def _show_event_table():
    """Non-modal table of the detected events; double-click a row to jump
    the main view onto that event."""
    global _evt_dialog
    if _last_events is None or not len(_last_events):
        return
    ev = _last_events
    if _evt_dialog is not None:
        _evt_dialog.close()
    dlg = pg.QtWidgets.QDialog(win)
    dlg.setAttribute(pg.QtCore.Qt.WA_DeleteOnClose)
    dlg.setWindowTitle('事件表（共 %d 个）' % len(ev))
    lay = pg.QtWidgets.QVBoxLayout(dlg)
    shown = ev[:1000]
    table = pg.QtWidgets.QTableWidget(len(shown), 6)
    table.setHorizontalHeaderLabels(
        ['#', 'sweep', 't_start (s)', 't_end (s)', 'dwell (s)',
         'level (%s)' % cur_yunit])
    table.setEditTriggers(pg.QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    for i, e in enumerate(shown):
        seg = int(e['i_seg'])
        name = _last_labels[seg] if seg < len(_last_labels) else str(seg)
        for c, val in enumerate(('%d' % i, name,
                                 '%.6g' % e['t_start'], '%.6g' % e['t_end'],
                                 '%.6g' % e['dwell'], '%.6g' % e['y_level'])):
            table.setItem(i, c, pg.QtWidgets.QTableWidgetItem(val))
    table.resizeColumnsToContents()
    lay.addWidget(table)
    if len(ev) > len(shown):
        lay.addWidget(pg.QtWidgets.QLabel(
            '仅显示前 %d 行；CSV 导出包含全部 %d 个事件' % (len(shown), len(ev))))

    def _jump(row, _col):
        e = ev[row]
        pad = max((e['t_end'] - e['t_start']) * 2.0, 0.02)
        vb.setXRange(e['t_start'] - pad, e['t_end'] + pad, padding=0)

    table.cellDoubleClicked.connect(_jump)
    btns = pg.QtWidgets.QHBoxLayout()
    b_csv = pg.QtWidgets.QPushButton('导出 CSV')
    b_csv.clicked.connect(_export_events_csv)
    b_close = pg.QtWidgets.QPushButton('关闭')
    b_close.clicked.connect(dlg.close)
    btns.addStretch(1)
    btns.addWidget(b_csv)
    btns.addWidget(b_close)
    lay.addLayout(btns)
    _evt_dialog = dlg
    dlg.show()


# Debounced refresh of the amplitude histogram while the user zooms the main
# view with "range = view Y" on
_follow_timer = pg.QtCore.QTimer()
_follow_timer.setSingleShot(True)
_follow_timer.setInterval(150)
_follow_timer.timeout.connect(amp_recompute)


def _main_range_changed(*_):
    if _amp_active() and amp_follow.isChecked() and amp_regions:
        _follow_timer.start()


# Band drag: ZERO detection while dragging -- computation and marking only
# happen after the gesture finishes. pyqtgraph's setRegion emits BOTH
# sigRegionChanged and sigRegionChangeFinished (even programmatically), so
# every handler is guarded by _band_syncing/_amp_syncing: only real user
# drags of the lines reach the commit.
def _band_region_changed(*_):
    _sync_fields_from_band()          # field echo only -- no computation


def _band_region_commit(*_):
    if not _band_syncing:
        run_detection()               # the gesture is finished: full run


band_region.sigRegionChanged.connect(_band_region_changed)
band_region.sigRegionChangeFinished.connect(_band_region_commit)
evt_mode.currentIndexChanged.connect(lambda *_: run_detection())
evt_k._cb = lambda *_: run_detection()
evt_tmin._cb = lambda *_: run_detection()
evt_merge._cb = lambda *_: run_detection()
evt_head._cb = lambda *_: run_detection()
evt_smooth._cb = lambda *_: run_detection()
evt_duty._cb = lambda *_: run_detection()
evt_ccdf.toggled.connect(lambda *_: run_detection())
evt_lo._cb = _sync_band_from_fields
evt_hi._cb = _sync_band_from_fields
evt_clear_btn.clicked.connect(_evt_clear)
evt_table_btn.clicked.connect(_show_event_table)
evt_csv_btn.clicked.connect(_export_events_csv)
evt_dwell_log.toggled.connect(lambda *_: run_detection())
for _ln in (dwell_ma, dwell_mb, level_ma, level_mb):
    _ln.sigPositionChanged.connect(_update_evt_meas)
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
vb.sigRangeChanged.connect(_main_range_changed)
clear_btn.clicked.connect(clear_analysis)
dist_tabs.currentChanged.connect(_dist_view_changed)
sec_dist.btn.clicked.connect(_dist_view_changed)


# initial hints + persisted state. Deliberately NOT persisted: the
# Add-region arm / detection arm (the open tab IS the arm now) -- the app
# always starts clean, like Measure. The last active tab is remembered.
run_detection()
amp_recompute()
_refresh_region_list()
dist_tabs.setCurrentIndex(int(settings.value('dist/tab', 0, type=int)))

# load Heka's demo bundle if it is present
demo = 'DemoV9Bundle.dat'
if os.path.isfile(demo):
    load(demo)


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
        vsplit.setSizes((380, 200, 150))
    ds = settings.value('layout/distsplit')
    if ds:
        dist_split.setSizes([int(s) for s in ds])
    else:
        dist_split.setSizes((600, 220))
    for key, sec in (('tree', sec_tree), ('nano', sec_nano), ('info', sec_info),
                     ('dist', sec_dist)):
        sec.set_collapsed(settings.value('layout/collapsed/' + key, False, type=bool))


_restore_layout()


def _save_layout():
    settings.setValue('layout/hsplit', list(hsplit.sizes()))
    settings.setValue('layout/vsplit', list(vsplit.sizes()))
    settings.setValue('layout/distsplit', list(dist_split.sizes()))
    for key, sec in (('tree', sec_tree), ('nano', sec_nano), ('info', sec_info),
                     ('dist', sec_dist)):
        settings.setValue('layout/collapsed/' + key, sec.is_collapsed())
    settings.setValue('dist/mode', evt_mode.currentText())
    settings.setValue('dist/k', evt_k.value())
    settings.setValue('dist/t_min_ms', evt_tmin.value())
    settings.setValue('dist/merge', evt_merge.value())
    settings.setValue('dist/head', evt_head.value())
    settings.setValue('dist/smooth', evt_smooth.value())
    settings.setValue('dist/duty', evt_duty.value())
    settings.setValue('dist/dwell_log', evt_dwell_log.isChecked())
    settings.setValue('dist/ccdf', evt_ccdf.isChecked())
    settings.setValue('dist/tab', dist_tabs.currentIndex())
    settings.setValue('amp/bins_auto', amp_auto_bins.isChecked())
    settings.setValue('amp/bins', amp_bins.value())
    settings.setValue('amp/follow', amp_follow.isChecked())


app.aboutToQuit.connect(_save_layout)

# Start the Qt event loop unless the user is in an interactive prompt
if sys.flags.interactive == 0:
    app.exec_()
    