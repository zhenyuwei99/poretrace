"""Headless tests for heka.analysis (pure numpy, no GUI, no pytest needed).

Run:  python3 test_analysis.py
Every case uses deterministic synthetic series; tolerances are in samples.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from heka import analysis


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
