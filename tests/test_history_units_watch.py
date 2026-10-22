import csv
import math

import numpy as np
import pytest

from flowapp.core.channel import ChannelInfo, ChannelState
from flowapp.core.watch import SetpointWatch
from flowapp.ui.history import SeriesBuffer
from flowapp.ui.units import common_unit, decimals_for, fmt, fmt_duration


def state(address, t, measure=1.0, setpoint=1.0, ok=True, capacity=10.0):
    if not ok:
        return ChannelState(address, t, ok=False, error="no answer")
    return ChannelState(address, t, measure=measure, setpoint=setpoint, measure_pct=measure / capacity * 100,
                        setpoint_pct=setpoint / capacity * 100, valve_pct=40.0, temperature=22.0)


# --- SeriesBuffer -------------------------------------------------------------------------------

def test_buffer_stores_values_and_gaps():
    buf = SeriesBuffer([4, 5], size=10)
    buf.append(1.0, [state(4, 1.0, 2.0), state(5, 1.0, ok=False)])
    buf.append(2.0, [state(4, 2.0, 3.0)])
    assert list(buf.t) == [1.0, 2.0]
    assert list(buf.series(4, "measure")) == [2.0, 3.0]
    assert np.isnan(buf.series(5, "measure")).all()


def test_buffer_keeps_at_least_size_samples():
    buf = SeriesBuffer([4], size=5)
    for i in range(23):
        buf.append(float(i), [state(4, i, float(i))])
    assert 5 <= len(buf) <= 10
    assert buf.t[-1] == 22.0 and list(buf.series(4, "measure")[-5:]) == [18.0, 19.0, 20.0, 21.0, 22.0]
    assert np.all(np.diff(buf.t) == 1.0)


def test_value_at_nearest_sample():
    buf = SeriesBuffer([4], size=10)
    for i in range(5):
        buf.append(float(i), [state(4, i, i * 10.0)])
    assert buf.value_at(4, "measure", 2.4) == 20.0
    assert buf.value_at(4, "measure", 2.6) == 30.0
    assert buf.value_at(4, "measure", -5) == 0.0
    assert buf.value_at(4, "measure", 50) == 40.0


def test_csv_export(tmp_path):
    buf = SeriesBuffer([4], size=10)
    buf.append(1700000000.0, [state(4, 0, 2.5, 3.0)])
    buf.append(1700000001.0, [state(4, 0, ok=False)])
    path = tmp_path / "out.csv"
    buf.to_csv(path, {4: "O2"}, {4: "mln/min"})
    rows = list(csv.reader(open(path, encoding="utf-8")))
    assert rows[0][:4] == ["time", "unix_time", "O2 measure [mln/min]", "O2 setpoint [mln/min]"]
    assert rows[1][2:6] == ["2.5", "3", "40", "22"]
    assert rows[2][2:] == ["", "", "", ""]


# --- units ----------------------------------------------------------------------------------------

def test_formatting():
    assert [decimals_for(c) for c in (1, 10, 100, 1000, 0)] == [4, 3, 2, 1, 3]
    assert fmt(None) == "–" and fmt(float("nan")) == "–" and fmt(1.23456, 2, " %") == "1.23 %"
    assert fmt_duration(65) == "1:05" and fmt_duration(3723) == "1:02:03" and fmt_duration(math.inf) == "∞"
    assert common_unit([ChannelInfo(4, unit="ln/min"), ChannelInfo(5, unit="ln/min")]) == "ln/min"
    assert common_unit([ChannelInfo(4, unit="ln/min"), ChannelInfo(5, unit="mln/min")]) is None


# --- SetpointWatch --------------------------------------------------------------------------------

def test_watch_flags_low_flow_after_delay():
    watch = SetpointWatch(tolerance_pct=2.0, delay_s=10.0)
    assert watch.update(state(4, 0, measure=0.0, setpoint=5.0), now=0.0) is None
    assert watch.update(state(4, 0, measure=0.0, setpoint=5.0), now=9.0) is None
    assert watch.update(state(4, 0, measure=0.0, setpoint=5.0), now=10.0) == "low"
    assert watch.update(state(4, 0, measure=5.0, setpoint=5.0), now=11.0) is None


def test_watch_restarts_on_setpoint_change_and_ramps():
    watch = SetpointWatch(tolerance_pct=2.0, delay_s=10.0)
    watch.update(state(4, 0, measure=0.0, setpoint=5.0), now=0.0)
    watch.update(state(4, 0, measure=0.0, setpoint=8.0), now=8.0)     # new setpoint: timer restarts
    assert watch.update(state(4, 0, measure=0.0, setpoint=8.0), now=12.0) is None
    assert watch.update(state(4, 0, measure=0.0, setpoint=8.0), now=18.0) == "low"
    assert watch.update(state(4, 0, measure=0.0, setpoint=8.0), now=30.0, suspended=True) is None
    assert watch.update(state(4, 0, measure=9.0, setpoint=8.0), now=31.0) is None
    assert watch.update(state(4, 0, measure=9.0, setpoint=8.0), now=41.0) == "high"


def test_watch_ignores_failed_polls():
    watch = SetpointWatch(delay_s=1.0)
    watch.update(state(4, 0, measure=0.0, setpoint=5.0), now=0.0)
    assert watch.update(state(4, 0, ok=False), now=5.0) is None
    assert watch.update(state(4, 0, measure=0.0, setpoint=5.0), now=5.5) is None


@pytest.mark.parametrize("measure", [4.85, 5.15])
def test_watch_tolerance(measure):
    watch = SetpointWatch(tolerance_pct=2.0, delay_s=0.0)
    watch.update(state(4, 0, measure=measure, setpoint=5.0), now=0.0)
    assert watch.update(state(4, 0, measure=measure, setpoint=5.0), now=1.0) is None
