"""Pure time-series analysis for the heka browser: threshold-band event
detection and histograms.

No Qt / GUI imports here -- every function takes plain numpy arrays, so the
same code runs inside the browser GUI, in notebooks and in headless tests.
Units are agnostic: pass t in seconds and y in whatever native unit the
trace carries; formatting is the caller's business.
"""

from collections import namedtuple

import numpy as np

__all__ = ['noise_sigma', 'detect_events', 'detect_events_segments',
           'all_point_histogram', 'log_histogram', 'survival_function',
           'fd_bin_count', 'EventResult', 'EVENT_DTYPE']

# One detected event: boundary times (sub-sample interpolated), duration,
# absolute mean level inside the event (first/last sample trimmed) and the
# index of the trace segment the event came from.
EVENT_DTYPE = np.dtype([('t_start', 'f8'), ('t_end', 'f8'), ('dwell', 'f8'),
                        ('y_level', 'f8'), ('i_seg', 'i4')])

EventResult = namedtuple('EventResult',
                         'events h sigma boundary_discarded')


def noise_sigma(y):
    """Robust white-noise amplitude: MAD of the first difference / sqrt(2).

    The first difference removes slow baseline drift and level steps and
    keeps white noise (variance 2 sigma^2); the median absolute deviation
    makes the estimate immune to event spikes.  For Gaussian noise
    sigma = 1.4826 * MAD.
    """
    d = np.diff(np.asarray(y, dtype=float))
    d = d[np.isfinite(d)]
    if d.size == 0:
        return 0.0
    return 1.4826 * float(np.median(np.abs(d - np.median(d)))) / np.sqrt(2.0)


def _mode_masks(y, mode, lo, hi, h):
    """(enter, exit) boolean masks for one event semantics.

    One event is a locked run of `enter` samples that only ends once `exit`
    fires; the hysteresis margin h shifts every exit threshold further away
    from the band edges, so noise within +-h of an edge cannot split a
    single event in two.

    inside   event while y is within [lo, hi]      (band = region of interest)
    outside  event while y is outside [lo, hi]     (baseline inside the band)
    below    event while y < hi                    (hi is the single threshold)
    above    event while y > lo                    (lo is the single threshold)
    """
    if mode == 'inside':
        if hi is None or lo is None or not (np.isfinite(lo) and np.isfinite(hi) and hi > lo):
            raise ValueError('inside mode needs a finite band lo < hi')
        enter = (y >= lo) & (y <= hi)
        exit_ = (y < lo - h) | (y > hi + h)
    elif mode == 'outside':
        if hi is None or lo is None or not (np.isfinite(lo) and np.isfinite(hi) and hi > lo):
            raise ValueError('outside mode needs a finite band lo < hi')
        if hi - lo <= 2 * h:
            raise ValueError('hysteresis too wide: outside mode needs hi - lo > 2h')
        enter = (y < lo) | (y > hi)
        exit_ = (y > lo + h) & (y < hi - h)
    elif mode == 'below':
        if hi is None or not np.isfinite(hi):
            raise ValueError('below mode needs a finite upper edge hi')
        enter = y < hi
        exit_ = y > hi + h
    elif mode == 'above':
        if lo is None or not np.isfinite(lo):
            raise ValueError('above mode needs a finite lower edge lo')
        enter = y > lo
        exit_ = y < lo - h
    else:
        raise ValueError('unknown mode: %r' % (mode,))
    return enter, exit_


def _cross_time(t, y, i, thr):
    """Linear-interpolated time at which y crosses thr between samples
    i-1 and i (sub-sample boundary precision)."""
    y0, y1 = y[i - 1], y[i]
    if y1 == y0:
        return float(t[i])
    frac = (thr - y0) / (y1 - y0)
    return float(t[i - 1] + frac * (t[i] - t[i - 1]))


def _edge_for(ys, ye, lo, hi, mode):
    """Band edge crossed by the step ys -> ye (for boundary interpolation)."""
    if mode == 'below':
        return hi
    if mode == 'above':
        return lo
    if (ys - lo) * (ye - lo) < 0:
        return lo
    if (ys - hi) * (ye - hi) < 0:
        return hi
    near_lo = abs(ys - lo) + abs(ye - lo)
    near_hi = abs(ys - hi) + abs(ye - hi)
    return lo if near_lo <= near_hi else hi


def detect_events(t, y, mode='inside', lo=None, hi=None, h=None, k=3.0,
                  t_min=3, merge_gap=0.0, interpolate=True):
    """Detect events in one time series.

    Parameters
    ----------
    t, y       time (s) and signal arrays, finite, same length
    mode       'inside' (default: event = sample inside [lo, hi]),
               'outside', 'below' (event = y < hi), 'above' (event = y > lo)
    lo, hi     band edges; 'below' uses hi only, 'above' uses lo only
    h          absolute hysteresis margin in y units;
               None -> k * noise_sigma(y) (adaptive per series)
    k          hysteresis in noise sigmas, used when h is None
    t_min      minimum event length in samples; shorter runs are dropped
    merge_gap  events separated by less than this (t units) are merged;
               0 disables merging (hysteresis alone usually suffices)
    interpolate  linearly interpolate boundary crossings (sub-sample times)

    Returns EventResult(events, h, sigma, boundary_discarded): events is a
    structured array (t_start, t_end, dwell, y_level, i_seg); an event whose
    entry or exit was not observed (already inside the band at sample 0, or
    never leaving it before the array ends) is discarded and counted in
    boundary_discarded.
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    sigma = noise_sigma(y)
    if h is None:
        h = k * sigma
    if t.size != y.size or t.size < 2:
        return EventResult(np.empty(0, EVENT_DTYPE), float(h), float(sigma), 0)
    if not np.isfinite(t).all() or not np.isfinite(y).all():
        raise ValueError('detect_events needs finite t / y arrays')

    enter, exit_ = _mode_masks(y, mode, lo, hi, float(h))

    # Rising transitions only; a tiny state machine then walks the (few)
    # candidate samples instead of the whole array.
    en = np.diff(enter.astype(np.int8), prepend=np.int8(0))
    ex = np.diff(exit_.astype(np.int8), prepend=np.int8(0))
    cand = np.flatnonzero((en != 0) | (ex != 0))

    spans = []                       # (first enter sample, first exit sample)
    start = -1
    for i in cand:
        if start < 0:
            if en[i] == 1:
                start = i
        elif ex[i] == 1:
            spans.append((start, i))
            start = -1
    boundary = 1 if start >= 0 else 0

    if merge_gap > 0 and spans:
        merged = [spans[0]]
        for s0, e0 in spans[1:]:
            ps, pe = merged[-1]
            if t[s0] - t[pe - 1] <= merge_gap:   # gap from previous last sample
                merged[-1] = (ps, e0)
            else:
                merged.append((s0, e0))
        spans = merged

    # An event is only trustworthy if both its entry and its exit were
    # observed: drop runs that were already inside the band at sample 0
    # (their true start lies before the recording) or never exited.
    boundary += sum(1 for s0, _ in spans if s0 == 0)
    spans = [(s0, e0) for s0, e0 in spans
             if s0 > 0 and e0 - s0 >= t_min]

    out = np.empty(len(spans), dtype=EVENT_DTYPE)
    n = len(t)
    for j, (s0, e0) in enumerate(spans):
        last = e0 - 1                            # last in-event sample
        if interpolate and s0 > 0:
            t0 = _cross_time(t, y, s0, _edge_for(y[s0 - 1], y[s0], lo, hi, mode))
        else:
            t0 = float(t[s0])
        if interpolate and e0 < n:
            t1 = _cross_time(t, y, e0, _edge_for(y[e0 - 1], y[e0], lo, hi, mode))
        else:
            t1 = float(t[last])
        a, b = s0 + 1, last - 1                  # trim transition samples
        if b < a:
            a, b = s0, last
        out[j] = (t0, t1, t1 - t0, float(np.mean(y[a:b + 1])), 0)
    return EventResult(out, float(h), float(sigma), boundary)


def detect_events_segments(segments, **kwargs):
    """detect_events over several (t, y) segments.

    Sweeps of one series share their time axis, so detection must run per
    trace and the results be pooled afterwards -- this function does exactly
    that and fills i_seg per segment.  With h=None the hysteresis adapts to
    each segment's own noise sigma.  boundary_discarded is summed.
    """
    events = []
    h_vals, sig_vals = [], []
    boundary = 0
    for i, (t, y) in enumerate(segments):
        res = detect_events(t, y, **kwargs)
        if len(res.events):
            ev = res.events.copy()
            ev['i_seg'] = i
            events.append(ev)
        h_vals.append(res.h)
        sig_vals.append(res.sigma)
        boundary += res.boundary_discarded
    pooled = np.concatenate(events) if events else np.empty(0, EVENT_DTYPE)
    n = len(h_vals) or 1
    return EventResult(pooled,
                       float(np.sum(h_vals) / n), float(np.sum(sig_vals) / n),
                       boundary)


def fd_bin_count(y, lo=32, hi=256):
    """Freedman-Diaconis bin count, clamped to [lo, hi].

    The IQR is robust, so capacitor-charging spikes do not blow up the bin
    width the way a plain min/max range would.
    """
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    n = y.size
    if n < 2:
        return int(lo)
    q25, q75 = np.percentile(y, [25, 75])
    iqr = q75 - q25
    span = float(y.max() - y.min())
    if iqr <= 0 or span <= 0:
        return int(min(max(int(np.ceil(np.sqrt(n))), lo), hi))
    width = 2.0 * iqr / n ** (1.0 / 3.0)
    k = int(np.ceil(span / width))
    return int(min(max(k, lo), hi))


def all_point_histogram(y, bins='fd', value_range=None):
    """Histogram of raw sample values -> (edges, counts, under, over).

    bins         'fd' (Freedman-Diaconis, clamped to 32..256), an int, or
                 an explicit edges array (then value_range must be None)
    value_range  (lo, hi) binning range; samples outside are counted in
                 under/over instead of being silently dropped.
                 Default: robust p0.5-p99.5 range so rare spikes do not
                 stretch the axis.

    Returns None for empty input.
    """
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if y.size == 0:
        return None
    if isinstance(bins, str) or isinstance(bins, (int, np.integer)):
        if isinstance(bins, str):
            nbins = fd_bin_count(y) if bins == 'fd' else int(bins)
        else:
            nbins = int(bins)
        if value_range is None:
            lo, hi = np.percentile(y, [0.5, 99.5])
            if not hi > lo:
                pad = abs(float(hi)) * 0.05 or 1.0
                lo, hi = lo - pad, hi + pad
            value_range = (float(lo), float(hi))
        counts, edges = np.histogram(y, bins=nbins, range=value_range)
        lo, hi = float(value_range[0]), float(value_range[1])
    else:
        counts, edges = np.histogram(y, bins=bins)
        lo, hi = float(edges[0]), float(edges[-1])
    under = int(np.sum(y < lo))
    over = int(np.sum(y > hi))
    return edges, counts, under, over


def log_histogram(values, bins_per_decade=10):
    """Histogram with logarithmic bin edges -> (edges, counts) or None.

    Dwell-time distributions are commonly log-normal / multi-exponential /
    power-law; linear bins cram everything into the first bar.
    """
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v) & (v > 0)]
    if v.size == 0:
        return None
    elo = float(np.floor(np.log10(v.min())))
    ehi = float(np.ceil(np.log10(v.max())))
    if ehi <= elo:
        ehi = elo + 1
    edges = np.logspace(elo, ehi, int(round((ehi - elo) * bins_per_decade)) + 1)
    counts, _ = np.histogram(v, bins=edges)
    return edges, counts


def survival_function(values):
    """Complementary CDF (1-CDF) -> (sorted_values, S) or None.

    The standard log-log view for telling power-law from multi-exponential
    dwell distributions.
    """
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v) & (v > 0)]
    if v.size == 0:
        return None
    v = np.sort(v)
    n = v.size
    # S(k) = (n-k)/n: log-safe (from 1.0 down to 1/n, never zero, so the
    # log-log plot stays finite)
    return v, (n - np.arange(n)) / float(n)
