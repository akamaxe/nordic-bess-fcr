"""Prequalification test signals of the Nordic FCR technical requirements v1.1.

- FCR-N step sequence (section 3.1.1, Table 3)
- FCR-D fast ramp sequence (section 3.1.2, Table 4), ramps 0-6 plus optional 7-8
- Sine tests (sections 3.2-3.4, Table 6)
- LER energy-management sequences (section 3.5.3, Tables 12-13) as step definitions;
  their durations depend on the unit's state, see ``nordic_bess.compliance.ler``.

Ramp signals are generated from start frequency, ramp speed and target; Table 4's
printed "end of ramp" times are kept in ``TABLE4_PRINTED_RAMP_END_S`` for cross-checks
only (the PDF's own values disagree with the ramp speed for ramps 1, 7 and 8).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nordic_bess.spec import Product


@dataclass(frozen=True)
class Segment:
    """One step or ramp of a test signal; the frequency is held at ``f_hz`` from
    ``ramp_end_s`` to ``t_end_s``."""

    name: str
    t_start_s: float
    ramp_end_s: float
    t_end_s: float
    f_hz: float


@dataclass(frozen=True)
class TestSignal:
    """A frequency test signal sampled every ``dt_s`` seconds, with its segments."""

    name: str
    product: Product
    t_s: np.ndarray
    f_hz: np.ndarray
    segments: tuple[Segment, ...]
    dt_s: float

    def segment(self, name: str) -> Segment:
        for seg in self.segments:
            if seg.name == name:
                return seg
        raise KeyError(f"{self.name}: no segment {name!r}")


def _grid(duration_s: float, dt_s: float) -> np.ndarray:
    n = int(round(duration_s / dt_s))
    return np.arange(n) * dt_s


# --- FCR-N step sequence (Table 3) -------------------------------------------------------
#: (name, duration [min], duration in the non-LER endurance test [min], frequency [Hz])
TABLE3_STEPS: tuple[tuple[str, float, float, float], ...] = (
    ("start", 0.5, 0.5, 50.0),
    ("pre_step", 0.5, 0.5, 49.95),
    ("step0", 5.0, 5.0, 50.0),
    ("step1", 5.0, 15.0, 49.9),
    ("step2", 5.0, 15.0, 50.1),
    ("step3", 5.0, 5.0, 50.0),
)


def fcr_n_step_sequence(dt_s: float = 0.1, endurance: bool = False) -> TestSignal:
    """FCR-N steady-state step sequence (FCR v1.1, section 3.1.1, Table 3).

    Ends at 21 min (41 min for the non-LER endurance variant).
    """
    segments, t = [], 0.0
    for name, dur, dur_end, f in TABLE3_STEPS:
        d = (dur_end if endurance else dur) * 60.0
        segments.append(Segment(name, t, t, t + d, f))
        t += d
    t_s = _grid(t, dt_s)
    f_hz = np.empty_like(t_s)
    for seg in segments:
        f_hz[(t_s >= seg.t_start_s - 1e-9) & (t_s < seg.t_end_s - 1e-9)] = seg.f_hz
    name = "fcr_n_step_endurance" if endurance else "fcr_n_step"
    return TestSignal(name, Product.FCR_N, t_s, f_hz, tuple(segments), dt_s)


# --- FCR-D fast ramp sequence (Table 4) --------------------------------------------------
#: (ramp, speed [Hz/s], f up [Hz], f down [Hz], duration [s], endurance duration [s])
TABLE4_RAMPS: tuple[tuple[int, float, float, float, float, float], ...] = (
    (0, 0.00, 49.90, 50.10, 30.0, 30.0),
    (1, 0.14, 49.45, 50.55, 4.9, 4.9),
    (2, 0.09, 49.90, 50.10, 55.1, 55.1),
    (3, 0.24, 49.50, 50.50, 300.0, 900.0),
    (4, 0.24, 49.90, 50.10, 300.0, 300.0),
    (5, 0.24, 49.00, 51.00, 60.0, 60.0),
    (6, 0.24, 50.00, 50.00, 300.0, 300.0),
    (7, 0.24, 49.70, 50.30, 300.0, 300.0),
    (8, 0.24, 49.89, 50.11, 300.0, 300.0),
)
TABLE4_PRINTED_RAMP_END_S = {
    1: 33.1, 2: 39.9, 3: 91.7, 4: 391.7, 5: 693.8, 6: 754.2, 7: 1050.8, 8: 1350.4
}  # fmt: skip


def fcr_d_ramp_sequence(
    product: Product,
    dt_s: float = 0.1,
    combination: bool = False,
    endurance: bool = False,
) -> TestSignal:
    """FCR-D fast ramp sequence (FCR v1.1, section 3.1.2, Table 4).

    Args:
        product: ``Product.FCR_D_UP`` or ``Product.FCR_D_DOWN``.
        dt_s: Sample time [s].
        combination: Include ramps 7-8 (FCR-N + FCR-D combination test).
        endurance: 900 s hold after ramp 3 (non-LER endurance test).
    """
    if product is Product.FCR_N:
        raise ValueError("the fast ramp test is for FCR-D")
    up = product is Product.FCR_D_UP
    rows = TABLE4_RAMPS if combination else TABLE4_RAMPS[:7]
    segments, t, f_prev = [], 0.0, rows[0][2] if up else rows[0][3]
    for ramp, speed, f_up, f_down, dur, dur_end in rows:
        target = f_up if up else f_down
        d = dur_end if endurance else dur
        ramp_time = 0.0 if speed == 0 else abs(target - f_prev) / speed
        segments.append(Segment(f"ramp{ramp}", t, t + ramp_time, t + d, target))
        t += d
        f_prev = target
    t_s = _grid(t, dt_s)
    f_hz = np.empty_like(t_s)
    f_start = segments[0].f_hz
    for seg in segments:
        mask = (t_s >= seg.t_start_s - 1e-9) & (t_s < seg.t_end_s - 1e-9)
        if seg.ramp_end_s > seg.t_start_s:
            frac = np.clip((t_s[mask] - seg.t_start_s) / (seg.ramp_end_s - seg.t_start_s), 0, 1)
            f_hz[mask] = f_start + (seg.f_hz - f_start) * frac
        else:
            f_hz[mask] = seg.f_hz
        f_start = seg.f_hz
    suffix = "up" if up else "down"
    return TestSignal(f"fcr_d_{suffix}_ramp", product, t_s, f_hz, tuple(segments), dt_s)


# --- Sine tests (Table 6) ----------------------------------------------------------------
#: (period [s], stationary periods, recommended total periods, FCR-N, FCR-D)
#: Periods 90-300 s apply to FCR-D only in high-stability mode (not used by a BESS).
TABLE6_SINES: tuple[tuple[float, int, int, bool, bool], ...] = (
    (10.0, 5, 20, True, True),
    (15.0, 5, 15, True, True),
    (25.0, 5, 10, True, True),
    (40.0, 5, 7, True, True),
    (50.0, 5, 7, True, True),
    (60.0, 5, 7, True, True),
    (70.0, 5, 7, True, True),
    (90.0, 5, 7, True, False),
    (150.0, 3, 4, True, False),
    (300.0, 2, 3, True, False),
)
SINE_CENTRE_HZ = {Product.FCR_N: 50.0, Product.FCR_D_UP: 49.7, Product.FCR_D_DOWN: 50.3}
SINE_AMPLITUDE_HZ = 0.1


def sine_periods(product: Product) -> list[tuple[float, int, int]]:
    """(period, stationary periods, total periods) required for a product (Table 6)."""
    col = 3 if product is Product.FCR_N else 4
    return [(row[0], row[1], row[2]) for row in TABLE6_SINES if row[col]]


def sine_test(product: Product, period_s: float, n_periods: int, dt_s: float = 0.1) -> TestSignal:
    """Sine test signal ``f = centre + 0.1 sin(2 pi t / T)`` (FCR v1.1, 3.2, Table 6).

    The last stationary periods are evaluated; earlier ones let transients settle.
    """
    t_s = _grid(period_s * n_periods, dt_s)
    centre = SINE_CENTRE_HZ[product]
    f_hz = centre + SINE_AMPLITUDE_HZ * np.sin(2 * np.pi * t_s / period_s)
    seg = Segment(f"sine_{period_s:g}s", 0.0, 0.0, period_s * n_periods, centre)
    name = f"sine_{product.value.lower()}_{period_s:g}s"
    return TestSignal(name, product, t_s, f_hz, (seg,), dt_s)


# --- LER energy-management sequences (Tables 12-13) --------------------------------------
@dataclass(frozen=True)
class LerStep:
    """One step of an LER test: minimum duration, frequency, expected NEM/AEM states and
    the condition that must hold before moving on (see ``nordic_bess.compliance.ler``)."""

    number: int
    min_duration_s: float
    f_up_hz: float
    f_down_hz: float
    expect_nem: str  # "on", "off", "off->on", "on->off", "on->off->on"
    expect_aem: str  # "on", "off", "on->off"
    condition: str | None


#: Table 12 (FCR-N). Step 6 lists two NEM states: off when SOC leaves the high side,
#: then on again when SOC reaches the low threshold.
TABLE12_FCR_N: tuple[LerStep, ...] = (
    LerStep(0, 120.0, 50.00, 50.00, "off", "off", None),
    LerStep(1, 1680.0, 50.09, 50.09, "on", "off", "nem_full_1min"),
    LerStep(2, 360.0, 50.11, 50.11, "off", "off", None),
    LerStep(3, 150.0, 50.09, 50.09, "on", "off", None),
    LerStep(4, 450.0, 50.11, 50.11, "off", "on", "aem_on_5min"),
    LerStep(5, 600.0, 50.09, 50.09, "on", "on", None),
    LerStep(6, 3600.0, 49.91, 49.91, "on->off->on", "on->off", "nem_aem_off_then_nem_full_1min"),
    LerStep(7, 300.0, 49.89, 49.89, "off", "off", None),
    LerStep(8, 150.0, 49.91, 49.91, "on", "off", None),
    LerStep(9, 600.0, 49.89, 49.89, "off", "on", "aem_on_5min"),
    LerStep(10, 600.0, 49.91, 49.91, "on", "on", None),
    LerStep(11, 1800.0, 50.00, 50.00, "off", "off", "nem_aem_off"),
)

#: Table 13 (FCR-D up and down; the down test is the mirror of the up test).
TABLE13_FCR_D: tuple[LerStep, ...] = (
    LerStep(0, 30.0, 49.91, 50.09, "off", "off", None),
    LerStep(1, 600.0, 49.50, 50.50, "off", "off", "nem_threshold_reached"),
    LerStep(2, 150.0, 49.91, 50.09, "on", "off", None),
    LerStep(3, 900.0, 49.50, 50.50, "off", "on", "aem_on_5min"),
    LerStep(4, 900.0, 49.91, 50.09, "on->off", "off", "nem_aem_off"),
)
