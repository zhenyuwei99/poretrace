import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyqtgraph as pg
import numpy as np
from heka import reader as heka_reader
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
hsplit.addWidget(plot)

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
    """

    def __init__(self, value, minimum, maximum, change_cb=None):
        super().__init__(self._fmt(value))
        self._min = float(minimum)
        self._max = float(maximum)
        self._cb = change_cb
        self._valid = float(value)
        self._normalizing = False
        self.textChanged.connect(self._on_text_changed)
        self.editingFinished.connect(self._on_editing_finished)

    @staticmethod
    def _fmt(v):
        return '%.6g' % v

    def value(self):
        return self._valid

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
            if self._cb is not None:
                self._cb(v)

    def _on_editing_finished(self):
        v = self._parse()
        if v is not None:
            self._valid = min(max(v, self._min), self._max)
        self.setText(self._fmt(self._valid))

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


def build_stitched(items):
    """Concatenate (index, trace) items end-to-end on a continuous time axis.

    Each segment continues at the previous segment's end time using its own
    XInterval, so traces with different sampling rates or lengths mix fine.
    Returns (x, y, seams, segments): seams holds the junction times between
    consecutive segments (len(items) - 1 entries); segments holds
    (x_start, x_end, 'SeriesLabel W# (T#)') per segment for the measure
    cursor lookup.
    """
    xs = []
    ys = []
    seams = []
    segments = []
    t = items[0][1].XStart
    for index, trace in items:
        data = bundle.data[list(index)]
        n = len(data)
        t0 = t
        ys.append(data)
        xs.append(t + np.arange(n) * trace.XInterval)
        t += n * trace.XInterval
        seams.append(t)
        segments.append((t0, t, trace_label(index)))
    return np.concatenate(xs), np.concatenate(ys), seams[:-1], segments


def replot():
    """Show data associated with the selected tree node(s).

    For all nodes, the meta-data is updated in the bottom tree.
    Group/Series/Sweep nodes expand to all traces they contain;
    trace nodes plot individually. Multi-selection plots the union
    (deduplicated) of all expanded traces.
    """
    global cur_xunit, cur_yunit, last_snap, stitch_segments
    plot.clear()
    legend.clear()
    data_tree.clear()
    clear_meas()
    add_crosshair()
    add_zoom_regions()
    add_readout()
    zoom_history.clear()
    stitch_segments = []

    selected = tree.selectedItems()
    if len(selected) < 1 or bundle is None:
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

    if len(items) > 20:
        legend.hide()
    else:
        legend.show()

    if stitch_btn.isChecked() and len(items) > 1:
        index0, trace0 = items[0]
        plot.setLabels(bottom=('Time', trace0.XUnit), left=(trace0.Label, trace0.YUnit))
        cur_xunit = trace0.XUnit
        cur_yunit = trace0.YUnit
        x, y, seams, seg_infos = build_stitched(items)
        stitch_segments = seg_infos
        plot.plot(x, y, pen=pg.mkPen(THEME['cycle'][0], width=1), name='stitched ×%d' % len(items))
        for t in seams:
            line = pg.InfiniteLine(pos=t, angle=90, movable=False,
                                   pen=pg.mkPen(THEME['seam'], width=1, style=pg.QtCore.Qt.DashLine))
            plot.getPlotItem().addItem(line, ignoreBounds=True)
    else:
        for i, (index, trace) in enumerate(items):
            plot.setLabels(bottom=('Time', trace.XUnit), left=(trace.Label, trace.YUnit))
            cur_xunit = trace.XUnit
            cur_yunit = trace.YUnit
            data = bundle.data[list(index)]
            time = np.linspace(trace.XStart, trace.XStart + trace.XInterval * (len(data)-1), len(data))
            plot.plot(time, data, pen=trace_pen(i, len(items)), name=trace_label(index))

    fit_view()


# replot when ever the user selects a new item
tree.itemSelectionChanged.connect(replot)


def stitch_toggled(checked):
    settings.setValue('stitch', checked)
    replot()


stitch_btn.toggled.connect(stitch_toggled)

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
    for key, sec in (('tree', sec_tree), ('nano', sec_nano), ('info', sec_info)):
        sec.set_collapsed(settings.value('layout/collapsed/' + key, False, type=bool))


_restore_layout()


def _save_layout():
    settings.setValue('layout/hsplit', list(hsplit.sizes()))
    settings.setValue('layout/vsplit', list(vsplit.sizes()))
    for key, sec in (('tree', sec_tree), ('nano', sec_nano), ('info', sec_info)):
        settings.setValue('layout/collapsed/' + key, sec.is_collapsed())


app.aboutToQuit.connect(_save_layout)

# Start the Qt event loop unless the user is in an interactive prompt
if sys.flags.interactive == 0:
    app.exec_()
    