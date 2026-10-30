"""Condition-driven LER energy-management tests and Requirement 12 (FCR v1.1, 3.5.3).

Tables 12 and 13 give example durations; each step must be held at least its minimum
duration and until its condition holds (for example "5 min after AEM turns on"). The
runner advances a resumable :class:`~nordic_bess.sim.engine.FcrUnitSimulator` step by
step and checks the condition every ``chunk_s`` seconds.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nordic_bess.compliance.evaluate import RequirementResult
from nordic_bess.compliance.signals import LerStep
from nordic_bess.sim.engine import SUFFIX, FcrUnitSimulator, to_frame
from nordic_bess.spec import Product


@dataclass(frozen=True)
class LerRun:
    """Simulation output of an LER test and the time span of each step."""

    product: Product
    frame: pd.DataFrame
    steps: tuple[LerStep, ...]
    bounds_s: tuple[tuple[float, float], ...]
    conditions_met: tuple[bool, ...]


def _concat(parts: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def _condition(
    name: str | None, cols: dict[str, np.ndarray], sfx: str, dt: float, sim, product
) -> bool:
    if name is None:
        return True
    nem_cur = cols[f"nem_current_{sfx}"]
    nem_ok = cols[f"nem_allowed_{sfx}"]
    aem = cols[f"aem_{sfx}"] > 0.5
    n60, n300 = int(round(60 / dt)), int(round(300 / dt))
    if name == "nem_full_1min":
        return len(nem_cur) >= n60 and bool(np.all(np.abs(nem_cur[-n60:]) > 1 - 1e-9))
    if name == "aem_on_5min":
        return len(aem) >= n300 and bool(np.all(aem[-n300:]))
    if name == "nem_aem_off":
        return bool(nem_cur[-1] == 0 and nem_ok[-1] == 0 and not aem[-1])
    if name == "nem_aem_off_then_nem_full_1min":
        off = np.flatnonzero((nem_ok == 0) & ~aem)
        if not len(off):
            return False
        tail = nem_cur[off[0] :]
        return len(tail) >= n60 and bool(np.all(np.abs(tail[-n60:]) > 1 - 1e-9))
    if name == "nem_threshold_reached":
        th = sim.thresholds(product)
        e = cols["e_mwh"][-1]
        if product is Product.FCR_D_UP:
            return bool(e < th.nem_enable_low)
        return bool(e > th.nem_enable_high)
    raise ValueError(f"unknown LER condition {name!r}")


def run_ler_test(
    sim: FcrUnitSimulator,
    product: Product,
    steps: tuple[LerStep, ...],
    chunk_s: float = 10.0,
    max_extension_s: float = 6 * 3600.0,
) -> LerRun:
    """Run an LER test sequence (Table 12 or 13) on a simulator in its initial state."""
    dt, sfx = sim.dt_s, SUFFIX[product]
    parts, bounds, met = [], [], []
    t = sim.step_index * dt
    for step in steps:
        f = step.f_down_hz if product is Product.FCR_D_DOWN else step.f_up_hz
        step_parts = [sim.run(np.full(int(round(step.min_duration_s / dt)), f))]
        cols = _concat(step_parts)
        extra, ok = 0.0, _condition(step.condition, cols, sfx, dt, sim, product)
        while not ok and extra < max_extension_s:
            step_parts.append(sim.run(np.full(int(round(chunk_s / dt)), f)))
            extra += chunk_s
            cols = _concat(step_parts)
            ok = _condition(step.condition, cols, sfx, dt, sim, product)
        parts.extend(step_parts)
        t_end = sim.step_index * dt
        bounds.append((t, t_end))
        met.append(ok)
        t = t_end
    return LerRun(product, to_frame(_concat(parts)), steps, tuple(bounds), tuple(met))


def _states(on: np.ndarray) -> list[str]:
    """Run-length encoded on/off sequence, e.g. ['on', 'off', 'on']."""
    seq: list[str] = []
    for v in on:
        s = "on" if v else "off"
        if not seq or seq[-1] != s:
            seq.append(s)
    return seq


def _matches(observed: list[str], expected: str) -> bool:
    """True if the observed on/off sequence ends with the expected pattern.

    ``"on->off"`` means NEM (or AEM) was on and then turned off within the step; extra
    earlier states are allowed (the step may start in a state left by the previous one).
    """
    want = expected.split("->")
    return observed[-len(want) :] == want


def evaluate_r12_ler(run: LerRun) -> RequirementResult:
    """Requirement 12 for LER units: NEM and AEM behave as Tables 12-13 expect and the
    response never ceases abruptly (no BMS energy limit hit during the test)."""
    sfx = SUFFIX[run.product]
    df, failures = run.frame, []
    t = df["t_s"].to_numpy()
    for step, (t0, t1), met in zip(run.steps, run.bounds_s, run.conditions_met, strict=True):
        mask = (t >= t0 - 1e-9) & (t < t1 - 1e-9)
        nem = _states(df[f"nem_allowed_{sfx}"].to_numpy()[mask] != 0)
        aem = _states(df[f"aem_{sfx}"].to_numpy()[mask])
        if not met:
            failures.append(f"step {step.number}: condition '{step.condition}' never met")
        if not _matches(nem, step.expect_nem):
            failures.append(f"step {step.number}: NEM {'->'.join(nem)} vs {step.expect_nem}")
        if not _matches(aem, step.expect_aem):
            failures.append(f"step {step.number}: AEM {'->'.join(aem)} vs {step.expect_aem}")
    limited_s = float(df["energy_limited"].sum()) * (t[1] - t[0])
    if limited_s > 0:
        failures.append(f"BMS energy limit hit for {limited_s:.0f} s (abrupt stop)")
    name = {Product.FCR_N: "FCR-N", Product.FCR_D_UP: "FCR-D up", Product.FCR_D_DOWN: "FCR-D down"}
    n_ok = len(run.steps) - len({f.split(":")[0] for f in failures if f.startswith("step")})
    explanation = (
        f"{n_ok}/{len(run.steps)} steps as Table {'12' if run.product is Product.FCR_N else '13'}"
        f" expects, {(t[-1] + t[1] - t[0]) / 60:.0f} min test"
        + ("; " + "; ".join(failures) if failures else "; no abrupt stop")
    )
    return RequirementResult(
        "R12 (LER)",
        name[run.product],
        float(n_ok),
        f"{len(run.steps)} steps",
        not failures,
        explanation,
        "steps",
    )
