"""Recent measurements for the live graph (numpy, no Qt)."""

import csv
from datetime import datetime

import numpy as np

FIELDS = ("measure", "setpoint", "valve", "temperature")


class SeriesBuffer:
    """Keeps at least `size` samples per channel in contiguous arrays (cheap views for plotting).

    Arrays are allocated for 2 x size samples; when they are full the newest `size` samples
    are moved to the front. Missing or failed readings are stored as NaN, so plots show gaps.
    """

    def __init__(self, addresses, size):
        self.addresses = list(addresses)
        self.size = max(1, int(size))
        self._t = np.full(2 * self.size, np.nan)
        self._data = {a: np.full((len(FIELDS), 2 * self.size), np.nan) for a in self.addresses}
        self.n = 0

    def append(self, t, states):
        if self.n == 2 * self.size:
            keep = self.size
            self._t[:keep] = self._t[-keep:]
            for arr in self._data.values():
                arr[:, :keep] = arr[:, -keep:]
            self.n = keep
        i = self.n
        self._t[i] = t
        by_address = {s.address: s for s in states}
        for address, arr in self._data.items():
            s = by_address.get(address)
            values = (s.measure, s.setpoint, s.valve_pct, s.temperature) if s is not None and s.ok else ()
            for row, field in enumerate(FIELDS):
                v = values[row] if values else None
                arr[row, i] = np.nan if v is None else v
        self.n += 1

    def __len__(self):
        return self.n

    @property
    def t(self):
        return self._t[:self.n]

    def series(self, address, field):
        return self._data[address][FIELDS.index(field), :self.n]

    def value_at(self, address, field, t):
        """Value of the sample nearest to time t (NaN if there is no data)."""
        if self.n == 0:
            return np.nan
        times = self.t
        i = int(np.clip(np.searchsorted(times, t), 1, self.n - 1)) if self.n > 1 else 0
        if self.n > 1 and abs(times[i - 1] - t) < abs(times[i] - t):
            i -= 1
        return self.series(address, field)[i]

    def to_csv(self, path, names, units):
        """Writes every buffered sample. `names`/`units`: address -> display name / capacity unit."""
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            header = ["time", "unix_time"]
            for a in self.addresses:
                header += [f"{names[a]} measure [{units[a]}]", f"{names[a]} setpoint [{units[a]}]",
                           f"{names[a]} valve [%]", f"{names[a]} temperature [C]"]
            writer.writerow(header)
            for i in range(self.n):
                t = self._t[i]
                row = [datetime.fromtimestamp(t).isoformat(timespec="milliseconds"), f"{t:.3f}"]
                for a in self.addresses:
                    row += ["" if np.isnan(v) else f"{v:.6g}" for v in self._data[a][:, i]]
                writer.writerow(row)
