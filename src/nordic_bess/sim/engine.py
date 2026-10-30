"""Time-domain simulation of the BESS with per-product FCR controllers, NEM and AEM.

Two modes share this engine: long horizon (1 s steps on 1 Hz measured
frequency with the hourly MILP schedule) and high resolution (0.1 s steps on the
prequalification test signals). The control laws are the pure functions in
``nordic_bess.control``; this module only holds the state between steps:

- every second: AEM and NEM latches (Table 11 hysteresis), NEM_allowed and f_AEM are
  pushed into 300-sample windows whose means give NEM_current (eq. 15) and the AEM
  reference frequency (eq. 18), computed from the 300 previous samples;
- every step: activation per product (eq. 23), NEM power (eq. 16-17), output limits
  (eq. 24-26), total setpoint = baseline + sum of products, plant step.

The simulator is resumable: :meth:`FcrUnitSimulator.run` continues from the last state,
which the condition-driven LER test sequences (Tables 12-13) need.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from nordic_bess.config import FcrRequirementsConfig
from nordic_bess.control.droop import activation_scalar
from nordic_bess.control.energy_mgmt import (
    aem_update,
    f_aem,
    limit_output,
    nem_rate,
    nem_update,
    stacked_thresholds,
)
from nordic_bess.plant.battery import BatteryParams, lag_coefficient, plant_step
from nordic_bess.spec import F0_HZ, Product

PRODUCTS = (Product.FCR_N, Product.FCR_D_UP, Product.FCR_D_DOWN)
SUFFIX = {Product.FCR_N: "n", Product.FCR_D_UP: "dup", Product.FCR_D_DOWN: "ddown"}


@dataclass(frozen=True)
class Schedule:
    """Piecewise-constant baseline and capacities; block ``k`` starts at ``start_s[k]``."""

    start_s: np.ndarray
    baseline_mw: np.ndarray
    c_n_mw: np.ndarray
    c_dup_mw: np.ndarray
    c_ddown_mw: np.ndarray

    @classmethod
    def constant(
        cls, c_n_mw: float = 0.0, c_dup_mw: float = 0.0, c_ddown_mw: float = 0.0, baseline_mw=0.0
    ) -> Schedule:
        def one(x: float) -> np.ndarray:
            return np.array([float(x)])

        return cls(one(0.0), one(baseline_mw), one(c_n_mw), one(c_dup_mw), one(c_ddown_mw))

    @classmethod
    def from_backtest(
        cls, schedule: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
    ) -> Schedule:
        """Hourly blocks from a MILP schedule (``results/backtest_<S>.parquet``)."""
        s = schedule[(schedule.index >= start) & (schedule.index < end)]
        if s.empty:
            raise ValueError("schedule does not cover the simulation window")
        return cls(
            start_s=(s.index - start).total_seconds().to_numpy(dtype=float),
            baseline_mw=(s["p_d_mw"] - s["p_c_mw"]).to_numpy(dtype=float),
            c_n_mw=s["c_n_mw"].clip(lower=0).to_numpy(dtype=float),
            c_dup_mw=s["c_dup_mw"].clip(lower=0).to_numpy(dtype=float),
            c_ddown_mw=s["c_ddown_mw"].clip(lower=0).to_numpy(dtype=float),
        )

    def capacities(self, k: int) -> dict[Product, float]:
        return {
            Product.FCR_N: float(self.c_n_mw[k]),
            Product.FCR_D_UP: float(self.c_dup_mw[k]),
            Product.FCR_D_DOWN: float(self.c_ddown_mw[k]),
        }


@dataclass(frozen=True)
class SimOptions:
    """Switches for test variants (all on for normal operation)."""

    nem: bool = True
    aem: bool = True
    saturate_fcr_d: bool = True
    window_samples: int = 300  # eq. 15 and 18: N = 300 at 1 s resolution


@dataclass
class _ProductState:
    nem_low: bool = False
    nem_high: bool = False
    aem_low: bool = False
    aem_high: bool = False
    nem_buf: np.ndarray = field(default_factory=lambda: np.zeros(0))
    faem_buf: np.ndarray = field(default_factory=lambda: np.zeros(0))
    nem_current: float = 0.0
    nem_allowed: int = 0
    f_ref: float = 0.0


COLUMNS = (
    "t_s",
    "f_hz",
    "p_base_mw",
    "p_fcr_n_mw",
    "p_fcr_dup_mw",
    "p_fcr_ddown_mw",
    "p_nem_n_mw",
    "p_nem_dup_mw",
    "p_nem_ddown_mw",
    "p_ideal_mw",
    "p_set_mw",
    "p_out_mw",
    "e_mwh",
    "nem_current_n",
    "nem_current_dup",
    "nem_current_ddown",
    "nem_allowed_n",
    "nem_allowed_dup",
    "nem_allowed_ddown",
    "aem_n",
    "aem_dup",
    "aem_ddown",
    "c_n_mw",
    "c_dup_mw",
    "c_ddown_mw",
    "energy_limited",
)


class FcrUnitSimulator:
    """Resumable simulator of one BESS providing FCR-N and FCR-D.

    Args:
        battery: Plant parameters.
        fcr: FCR requirement parameters (NEM rates, Table 11 minutes, Table 10 factors).
        schedule: Baseline and capacities per block.
        e0_mwh: Initial stored energy [MWh].
        dt_s: Step length [s]; ``1 / dt_s`` must be an integer number of steps per second
            when ``dt_s < 1`` (NEM and AEM run at 1 s resolution).
        options: Variant switches.
    """

    def __init__(
        self,
        battery: BatteryParams,
        fcr: FcrRequirementsConfig,
        schedule: Schedule,
        e0_mwh: float,
        dt_s: float,
        options: SimOptions | None = None,
    ) -> None:
        self.b = battery
        self.fcr = fcr
        self.schedule = schedule
        self.dt_s = float(dt_s)
        self.opts = options or SimOptions()
        ratio = 1.0 / self.dt_s
        if self.dt_s < 1.0 and abs(ratio - round(ratio)) > 1e-9:
            raise ValueError("1 / dt_s must be an integer for dt_s < 1 s")
        if self.dt_s > 1.0 and abs(self.dt_s - round(self.dt_s)) > 1e-9:
            raise ValueError("dt_s above 1 s must be a whole number of seconds")
        self.steps_per_tick = max(int(round(ratio)), 1)
        self.alpha = lag_coefficient(self.dt_s, battery.tau_s)
        self.e = float(e0_mwh)
        self.p_out = 0.0
        self.step_index = 0
        n = self.opts.window_samples
        self.state = {
            p: _ProductState(nem_buf=np.zeros(n), faem_buf=np.full(n, F0_HZ[p]), f_ref=F0_HZ[p])
            for p in PRODUCTS
        }
        self._buf_pos = 0
        self._block = -1
        self._caps: dict[Product, float] = {}
        self._th = {}

    def thresholds(self, product: Product):
        """Energy thresholds of ``product`` in the current schedule block (Table 11)."""
        if self._block < 0:
            self._enter_block(0)
        return self._th[product]

    def _enter_block(self, k: int) -> None:
        self._block = k
        self._caps = self.schedule.capacities(k)
        self._th = stacked_thresholds(
            self._caps[Product.FCR_N],
            self._caps[Product.FCR_D_UP],
            self._caps[Product.FCR_D_DOWN],
            self.b.e_min_mwh,
            self.b.e_max_mwh,
            self.fcr,
        )

    def _tick(self, f: float) -> None:
        """1 s update of AEM/NEM latches and the rolling windows (eq. 14, 15, 18-19)."""
        pos = self._buf_pos
        for prod in PRODUCTS:
            st = self.state[prod]
            st.nem_current = float(st.nem_buf.mean())  # previous 300 samples (eq. 15)
            st.f_ref = float(st.faem_buf.mean())  # previous 300 samples (eq. 18)
            if self._caps[prod] <= 0.0:
                st.nem_low = st.nem_high = st.aem_low = st.aem_high = False
                st.nem_allowed = 0
                st.nem_buf[pos] = 0.0
                st.faem_buf[pos] = F0_HZ[prod]
                continue
            th = self._th[prod]
            if self.opts.aem:
                st.aem_low, st.aem_high = aem_update(self.e, st.aem_low, st.aem_high, th)
            allowed = 0
            if self.opts.nem:
                allowed, st.nem_low, st.nem_high = nem_update(
                    f, self.e, st.nem_low, st.nem_high, th
                )
            st.nem_allowed = allowed
            st.nem_buf[pos] = allowed
            st.faem_buf[pos] = f_aem(prod, f, st.aem_low or st.aem_high)
        self._buf_pos = (pos + 1) % self.opts.window_samples

    def run(self, f_hz: np.ndarray) -> dict[str, np.ndarray]:
        """Simulate ``len(f_hz)`` steps from the current state; returns column arrays."""
        f_arr = np.asarray(f_hz, dtype=float)
        n = len(f_arr)
        out = {c: np.zeros(n) for c in COLUMNS}
        b, fcr, opts = self.b, self.fcr, self.opts
        t_arr = (self.step_index + np.arange(n)) * self.dt_s
        blocks = np.searchsorted(self.schedule.start_s, t_arr + 1e-9, side="right") - 1
        f0 = {prod: F0_HZ[prod] for prod in PRODUCTS}
        for i in range(n):
            f = float(f_arr[i])
            t = float(t_arr[i])
            k = int(blocks[i])
            if k != self._block:
                self._enter_block(max(k, 0))
            if self.step_index % self.steps_per_tick == 0:
                self._tick(f)
            base = float(self.schedule.baseline_mw[self._block])
            p_set = base
            p_ideal = 0.0
            for prod in PRODUCTS:
                c = self._caps[prod]
                st = self.state[prod]
                sfx = SUFFIX[prod]
                if c <= 0.0:
                    out[f"p_fcr_{sfx}_mw"][i] = 0.0
                    out[f"p_nem_{sfx}_mw"][i] = 0.0
                    continue
                rate = nem_rate(prod, fcr)
                p_x = activation_scalar(prod, f, c, st.f_ref, opts.saturate_fcr_d)
                p_ideal += activation_scalar(prod, f, c, f0[prod], opts.saturate_fcr_d)
                p_nem = rate * c * st.nem_current
                p_tot = limit_output(prod, p_x + p_nem, c, rate * c)
                p_set += p_tot
                out[f"p_fcr_{sfx}_mw"][i] = p_tot - p_nem
                out[f"p_nem_{sfx}_mw"][i] = p_nem
                out[f"nem_current_{sfx}"][i] = st.nem_current
                out[f"nem_allowed_{sfx}"][i] = st.nem_allowed
                out[f"aem_{sfx}"][i] = float(st.aem_low or st.aem_high)
                out[f"c_{sfx}_mw"][i] = c
            p_out, e_next, limited = plant_step(self.p_out, self.e, p_set, self.dt_s, b, self.alpha)
            out["t_s"][i] = t
            out["f_hz"][i] = f
            out["p_base_mw"][i] = base
            out["p_ideal_mw"][i] = p_ideal
            out["p_set_mw"][i] = p_set
            out["p_out_mw"][i] = p_out
            out["e_mwh"][i] = e_next  # energy at the end of the step
            out["energy_limited"][i] = float(limited)
            self.p_out, self.e = p_out, e_next
            self.step_index += 1
        return out


def to_frame(columns: dict[str, np.ndarray], start: pd.Timestamp | None = None) -> pd.DataFrame:
    """Simulation output as a DataFrame (UTC index when ``start`` is given, else ``t_s``)."""
    df = pd.DataFrame(columns)
    for c in ("aem_n", "aem_dup", "aem_ddown", "energy_limited"):
        df[c] = df[c].astype(bool)
    if start is not None:
        df.index = start + pd.to_timedelta(df["t_s"], unit="s")
        df.index.name = "time_utc"
    return df


def simulate(
    f_hz: np.ndarray,
    dt_s: float,
    schedule: Schedule,
    battery: BatteryParams,
    fcr: FcrRequirementsConfig,
    e0_mwh: float,
    options: SimOptions | None = None,
    start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Run a whole frequency series through a fresh simulator (see :class:`FcrUnitSimulator`)."""
    sim = FcrUnitSimulator(battery, fcr, schedule, e0_mwh, dt_s, options)
    return to_frame(sim.run(f_hz), start)
