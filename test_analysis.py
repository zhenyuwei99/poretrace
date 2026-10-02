"""Headless tests for poretrace.analysis (pure numpy, no GUI, no pytest needed).

Run:  python3 test_analysis.py
Every case uses deterministic synthetic series; tolerances are in samples.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # repo root, wherever it is checked out
from poretrace import analysis


def _ramp(n):
    return np.arange(n) * 5e-5          # 20 kHz like the real recordings


def _series(baseline, pulses, n, band):
    """Square pulses (list of (start, end) sample ranges) over a baseline."""
    y = np.full(n, baseline)
    for s, e in pulses:
        y[s:e] = (band[0] + band[1]) / 2.0
    return y


def test_noise_sigma():
    rng = np.random.default_rng(7)
    y = rng.normal(0.0, 3.0, 200000)
    s = analysis.noise_sigma(y)
    assert abs(s - 3.0) < 0.3, s
    assert analysis.noise_sigma(np.zeros(100)) == 0.0


def test_inside_basic_and_level():
    n = 20000
    y = _series(-100.0, [(1000, 2000), (5000, 5500), (9000, 11000)], n, (10, 40))
    res = analysis.detect_events(_ramp(n), y, mode='inside', lo=10.0, hi=40.0,
                                 h=1.0, t_min=3)
    assert len(res.events) == 3, res.events
    dt = 5e-5
    expect = [(1000, 2000), (5000, 5500), (9000, 11000)]
    for ev, (s, e) in zip(res.events, expect):
        assert abs(ev['t_start'] - s * dt) < 2 * dt
        assert abs(ev['t_end'] - e * dt) < 2 * dt
        assert abs(ev['dwell'] - (e - s) * dt) < 3 * dt
        assert abs(ev['y_level'] - 25.0) < 1e-9
        assert ev['i_seg'] == 0
    assert res.boundary_discarded == 0


def test_hysteresis_prevents_split():
    """A brief dip out of the band that stays within +-h must NOT split the
    event; with h=0 it does split."""
    n = 20000
    y = _series(-100.0, [(1000, 2000)], n, (10, 40))
    y[1500:1502] = 6.0                      # noise poke, still > lo - h = 4
    kw = dict(mode='inside', lo=10.0, hi=40.0, t_min=3)
    split = analysis.detect_events(_ramp(n), y, h=0.0, **kw)
    whole = analysis.detect_events(_ramp(n), y, h=6.0, **kw)
    assert len(split.events) == 2, split.events
    assert len(whole.events) == 1, whole.events
    assert abs(whole.events[0]['t_end'] - 2000 * 5e-5) < 3 * 5e-5


def test_t_min():
    n = 5000
    y = _series(-100.0, [(1000, 1002), (3000, 3500)], n, (10, 40))
    res = analysis.detect_events(_ramp(n), y, mode='inside', lo=10.0, hi=40.0,
                                 h=1.0, t_min=3)
    assert len(res.events) == 1
    assert abs(res.events[0]['t_start'] - 3000 * 5e-5) < 3 * 5e-5


def test_merge_gap():
    n = 20000
    y = _series(-100.0, [(1000, 1500), (1503, 2000)], n, (10, 40))
    kw = dict(mode='inside', lo=10.0, hi=40.0, h=1.0, t_min=3)
    apart = analysis.detect_events(_ramp(n), y, merge_gap=0.0, **kw)
    joined = analysis.detect_events(_ramp(n), y, merge_gap=1.0, **kw)
    assert len(apart.events) == 2
    assert len(joined.events) == 1
    assert abs(joined.events[0]['t_start'] - 1000 * 5e-5) < 3 * 5e-5
    assert abs(joined.events[0]['t_end'] - 2000 * 5e-5) < 3 * 5e-5


def test_boundary_discarded():
    n = 5000
    y = _series(-100.0, [(0, 5000)], n, (10, 40))       # always inside
    res = analysis.detect_events(_ramp(n), y, mode='inside', lo=10.0, hi=40.0,
                                 h=1.0)
    assert len(res.events) == 0
    assert res.boundary_discarded == 1

    y = _series(-100.0, [(0, 2000), (4000, 5000)], n, (10, 40))  # both ends open
    res = analysis.detect_events(_ramp(n), y, mode='inside', lo=10.0, hi=40.0,
                                 h=1.0)
    assert len(res.events) == 0
    assert res.boundary_discarded == 2


def test_outside_bipolar():
    """Baseline inside the band, spikes both up and down -> both detected."""
    n = 20000
    y = np.full(n, 25.0)
    y[1000:1500] = 90.0                     # up spike
    y[5000:5600] = -40.0                    # down spike
    res = analysis.detect_events(_ramp(n), y, mode='outside', lo=10.0, hi=40.0,
                                 h=4.0, t_min=3)
    assert len(res.events) == 2, res.events
    assert abs(res.events[0]['y_level'] - 90.0) < 1e-9
    assert abs(res.events[1]['y_level'] - (-40.0)) < 1e-9


def test_below_above():
    n = 10000
    y = np.full(n, 50.0)
    y[1000:1500] = 15.0
    y[5000:5500] = 15.0
    res = analysis.detect_events(_ramp(n), y, mode='below', lo=None, hi=20.0,
                                 h=3.0, t_min=3)
    assert len(res.events) == 2

    y = np.full(n, -50.0)
    y[2000:2500] = 15.0
    res = analysis.detect_events(_ramp(n), y, mode='above', lo=10.0, hi=None,
                                 h=3.0, t_min=3)
    assert len(res.events) == 1


def test_adaptive_h():
    """h=None derives from k * noise_sigma; chatter below k*sigma must not
    split an event."""
    rng = np.random.default_rng(3)
    n = 20000
    y = _series(-100.0, [(1000, 2000)], n, (10, 40)) + rng.normal(0, 1.0, n)
    y[1500:1502] = 8.0                      # poke: 10 - 3*1 = 7 < 8 -> no exit
    res = analysis.detect_events(_ramp(n), y, mode='inside', lo=10.0, hi=40.0,
                                 h=None, k=3.0, t_min=3)
    assert len(res.events) == 1, res.events
    assert 2.0 < res.h < 6.0
    assert 0.5 < res.sigma < 2.0


def test_segments_pooling():
    n = 10000
    segs = []
    for k in range(2):
        y = _series(-100.0, [(1000, 1500)], n, (10, 40))
        segs.append((_ramp(n), y))
    res = analysis.detect_events_segments(segs, mode='inside', lo=10.0,
                                          hi=40.0, h=1.0, t_min=3)
    assert len(res.events) == 2
    assert sorted(res.events['i_seg']) == [0, 1]


def test_moat_exit_no_negative_dwell():
    """Hysteresis exit: a sample barely inside the moat (lo-h, lo) followed
    by a bare crossing of lo-h used to back-extrapolate t_end far before
    t_start (negative dwell).  The interpolated crossing must be clamped
    into the bracketing samples."""
    dt = 5e-5
    t = np.arange(5000) * dt
    y = np.full(5000, 0.0)
    y[1000] = 25.0        # enter
    y[1001] = 25.0
    y[1002] = 9.0001      # barely inside the moat (lo-h, lo) with h = 1
    y[1003] = 8.99999     # barely crosses lo - h -> exit fires here
    res = analysis.detect_events(t, y, mode='inside', lo=10.0, hi=40.0,
                                 h=1.0, t_min=3)
    assert len(res.events) == 1, res.events
    ev = res.events[0]
    assert ev['dwell'] > 0, ev['dwell']
    assert ev['t_start'] <= ev['t_end']
    assert abs(ev['t_end'] - 1002 * dt) < dt        # clamped to t[1002]


def test_y_level_in_band_and_duty_filter():
    """A merge_gap chain of brief spike-top fragments: the merged event's
    y_level must average IN-BAND samples only (not the gaps), and a tiny
    duty cycle chain is dropped when duty_min is set."""
    dt = 5e-5
    n = 5000
    y = np.zeros(n)
    for start in (1000, 1200, 1400):        # 20-sample tops, 100-sample gaps
        y[start:start + 20] = 25.0
    t = _ramp(n)
    kw = dict(mode='inside', lo=10.0, hi=40.0, h=1.0, t_min=3, merge_gap=0.012)
    keep = analysis.detect_events(t, y, duty_min=0.0, **kw)
    assert len(keep.events) == 1, keep.events
    ev = keep.events[0]
    assert ev['y_level'] == 25.0, ev['y_level']     # not diluted by the gaps
    assert abs(ev['dwell'] - 420 * dt) < 3 * dt     # full merged span
    drop = analysis.detect_events(t, y, duty_min=0.5, **kw)
    assert len(drop.events) == 0
    assert drop.duty_discarded == 1


def test_duty_keeps_interrupted_sojourn():
    """A genuine level sojourn merely interrupted by brief spikes stays
    above the duty threshold once merged."""
    n = 5000
    y = np.zeros(n)
    y[1000:3000] = 25.0                     # long sojourn
    y[1500:1505] = 0.0                      # brief spikes out of band
    y[2200:2206] = 0.0
    res = analysis.detect_events(_ramp(n), y, mode='inside', lo=10.0, hi=40.0,
                                 h=1.0, t_min=3, merge_gap=0.05, duty_min=0.5)
    assert len(res.events) == 1, res.events
    ev = res.events[0]
    assert ev['y_level'] == 25.0
    assert ev['dwell'] > 1980 * 5e-5        # spans the whole sojourn
    assert res.duty_discarded == 0


def test_t_head_ignores_transient():
    n = 5000
    y = np.zeros(n)
    y[100:200] = 25.0                       # pulse right after the start
    kw = dict(mode='inside', lo=10.0, hi=40.0, h=1.0, t_min=3)
    full = analysis.detect_events(_ramp(n), y, **kw)
    assert len(full.events) == 1
    cut = analysis.detect_events(_ramp(n), y, t_head=150 * 5e-5, **kw)
    assert len(cut.events) == 0             # pulse falls inside the ignored head
    keep = analysis.detect_events(_ramp(n), y, t_head=50 * 5e-5, **kw)
    assert len(keep.events) == 1
    assert abs(keep.events[0]['t_start'] - 100 * 5e-5) < 3 * 5e-5


def test_slice_segments():
    """Time-scope slicing: keep in-span samples, drop empty segments,
    subsample after slicing."""
    n = 10000
    segs = [(_ramp(n), np.full(n, 25.0)), (_ramp(n), np.full(n, -5.0))]
    out = analysis.slice_segments(segs, 1000 * 5e-5, 2000 * 5e-5)
    assert len(out) == 2
    assert len(out[0][0]) == 1001 and len(out[1][1]) == 1001
    assert abs(out[0][0][0] - 1000 * 5e-5) < 1e-12
    assert abs(out[0][0][-1] - 2000 * 5e-5) < 1e-12
    assert analysis.slice_segments(segs, 2.0, 3.0) == []      # no overlap
    out = analysis.slice_segments(segs, 0.0, 1.0, stride=100)
    assert len(out[0][0]) == 100
    assert analysis.slice_segments([], 0.0, 1.0) == []


def test_slice_scoped_detection_edges():
    """Grab-tab semantics: events straddling a slice edge are discarded
    (boundary), events complete inside the slice are kept with unchanged
    dwell."""
    n = 20000
    y = _series(-100.0, [(1000, 1500), (3000, 3500), (6000, 8000)], n, (10, 40))
    t = _ramp(n)
    kw = dict(mode='inside', lo=10.0, hi=40.0, h=1.0, t_min=3)
    # slice [2000, 6800]: event 1 outside; event 2 complete; event 3 enters
    # before 6800 but never exits inside the slice -> boundary
    segs = analysis.slice_segments([(t, y)], 2000 * 5e-5, 6800 * 5e-5)
    res = analysis.detect_events_segments(segs, **kw)
    assert len(res.events) == 1, res.events
    assert abs(res.events[0]['t_start'] - 3000 * 5e-5) < 2 * 5e-5
    assert abs(res.events[0]['dwell'] - 500 * 5e-5) < 3 * 5e-5
    assert res.boundary_discarded == 1
    # event already inside at the slice start -> boundary as well
    segs = analysis.slice_segments([(t, y)], 3200 * 5e-5, 4000 * 5e-5)
    res = analysis.detect_events_segments(segs, **kw)
    assert len(res.events) == 0, res.events
    assert res.boundary_discarded == 1


def test_in_band_fraction():
    n = 1000
    y = np.full(n, -100.0)
    y[:200] = 25.0                       # 20% of samples at 25
    segs = [(_ramp(n), y)]
    assert abs(analysis.in_band_fraction(segs, 'inside', 10.0, 40.0) - 0.2) < 1e-9
    assert abs(analysis.in_band_fraction(segs, 'outside', 10.0, 40.0) - 0.8) < 1e-9
    assert analysis.in_band_fraction(segs, 'below', 10.0, 40.0) == 1.0
    assert analysis.in_band_fraction([], 'inside', 0.0, 1.0) is None


def test_validation_errors():
    y = np.zeros(100)
    t = _ramp(100)
    for kw in (dict(mode='inside', lo=None, hi=10.0),
               dict(mode='inside', lo=40.0, hi=10.0),
               dict(mode='outside', lo=10.0, hi=12.0, h=2.0),
               dict(mode='below', hi=None),
               dict(mode='above', lo=None),
               dict(mode='nope', lo=0.0, hi=1.0)):
        try:
            analysis.detect_events(t, y, **kw)
        except ValueError:
            continue
        raise AssertionError('expected ValueError for %r' % kw)


def test_histograms():
    rng = np.random.default_rng(11)
    y = np.concatenate([rng.normal(0, 1, 50000), rng.normal(50, 2, 50000),
                        np.array([-1e3, 1e3])])          # 2 outliers
    edges, counts, under, over = analysis.all_point_histogram(y)
    assert counts.sum() + under + over == y.size
    assert under >= 1 and over >= 1
    assert len(edges) - 1 == len(counts)
    assert 32 <= len(counts) <= 256

    edges, counts, under, over = analysis.all_point_histogram(
        y, bins=64, value_range=(-5, 55))
    assert len(counts) == 64 and under > 0 and over > 0

    lh = analysis.log_histogram([1e-4, 1e-3, 1e-2, 5e-3])
    assert lh is not None and lh[0][0] <= 1e-4 and lh[0][-1] >= 1e-2
    assert lh[1].sum() == 4
    assert analysis.log_histogram([-1.0, 0.0]) is None

    sv = analysis.survival_function(np.geomspace(1e-3, 1.0, 100))
    assert sv is not None and len(sv[0]) == 100
    assert np.all(np.diff(sv[1]) < 0) and sv[1][-1] == 0.01

    assert analysis.all_point_histogram(np.array([])) is None


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in tests:
        fn()
        print('ok  %s' % fn.__name__)
    print('%d/%d passed' % (len(tests), len(tests)))


if __name__ == '__main__':
    main()
