"""Run every prequalification test on the BESS model and evaluate the requirements.

The BESS (plant + controllers of ``nordic_bess.sim``) is driven by each test signal
with only the tested product enabled, starting at the target SOC. The activated power
passed to the evaluators is ``P_out - baseline - P_NEM``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from nordic_bess.compliance.evaluate import (
    RequirementResult,
    evaluate_fcr_d_ramp,
    evaluate_frequency_domain,
    evaluate_r1_fcr_n,
    evaluate_sine_tests,
)
from nordic_bess.compliance.freqdomain import TransferPoint
from nordic_bess.compliance.ler import LerRun, evaluate_r12_ler, run_ler_test
from nordic_bess.compliance.signals import (
    TABLE12_FCR_N,
    TABLE13_FCR_D,
    TestSignal,
    fcr_d_ramp_sequence,
    fcr_n_step_sequence,
    sine_periods,
    sine_test,
)
from nordic_bess.config import Config
from nordic_bess.plant.battery import BatteryParams
from nordic_bess.sim.engine import FcrUnitSimulator, Schedule, simulate
from nordic_bess.sim.kpis import NEM_COLUMNS
from nordic_bess.spec import Product


@dataclass
class ComplianceRun:
    """Results and the traces needed for the report figures."""

    results: list[RequirementResult] = field(default_factory=list)
    traces: dict[str, tuple[TestSignal, pd.DataFrame]] = field(default_factory=dict)
    transfer: dict[Product, list[TransferPoint]] = field(default_factory=dict)
    ler: dict[Product, LerRun] = field(default_factory=dict)


def tested_capacity(cfg: Config, product: Product) -> float:
    c = cfg.compliance
    return {
        Product.FCR_N: c.c_fcr_n_mw,
        Product.FCR_D_UP: c.c_fcr_dup_mw,
        Product.FCR_D_DOWN: c.c_fcr_ddown_mw,
    }[product]


def single_product_schedule(product: Product, c_mw: float) -> Schedule:
    return Schedule.constant(
        c_n_mw=c_mw if product is Product.FCR_N else 0.0,
        c_dup_mw=c_mw if product is Product.FCR_D_UP else 0.0,
        c_ddown_mw=c_mw if product is Product.FCR_D_DOWN else 0.0,
    )


def activated_power(df: pd.DataFrame) -> np.ndarray:
    """Activated FCR power [MW]: output minus baseline and NEM power."""
    return (df["p_out_mw"] - df["p_base_mw"] - df[list(NEM_COLUMNS)].sum(axis=1)).to_numpy()


def simulate_signal(cfg: Config, sig: TestSignal, battery: BatteryParams) -> pd.DataFrame:
    c = tested_capacity(cfg, sig.product)
    sched = single_product_schedule(sig.product, c)
    return simulate(sig.f_hz, sig.dt_s, sched, battery, cfg.fcr, cfg.bess.e_target_mwh)


def ler_initial_energy(cfg: Config, product: Product, battery: BatteryParams) -> float:
    """Start the LER test a few minutes of full activation before the NEM threshold."""
    c = tested_capacity(cfg, product)
    sim = FcrUnitSimulator(battery, cfg.fcr, single_product_schedule(product, c), 0.0, 1.0)
    th = sim.thresholds(product)
    margin = c * cfg.compliance.ler_start_margin_min / 60.0
    if product is Product.FCR_D_UP:
        return th.nem_enable_low + margin  # step 1 discharges at 49.5 Hz
    return th.nem_enable_high - margin  # FCR-N step 1 (50.09 Hz) and FCR-D down charge


def run_bess_compliance(cfg: Config, dt_s: float | None = None) -> ComplianceRun:
    """Run the step, ramp, sine and LER tests on the configured BESS."""
    dt = dt_s or cfg.simulation.test_signal_step_s
    window = cfg.compliance.steady_state_window_s
    battery = BatteryParams.from_config(cfg)
    run = ComplianceRun()

    sig = fcr_n_step_sequence(dt)
    df = simulate_signal(cfg, sig, battery)
    run.traces["fcr_n_step"] = (sig, df)
    run.results += evaluate_r1_fcr_n(sig, activated_power(df), cfg.compliance.c_fcr_n_mw, window)

    for product in (Product.FCR_D_UP, Product.FCR_D_DOWN):
        sig = fcr_d_ramp_sequence(product, dt)
        df = simulate_signal(cfg, sig, battery)
        run.traces[sig.name] = (sig, df)
        c = tested_capacity(cfg, product)
        run.results += evaluate_fcr_d_ramp(sig, activated_power(df), c, window)

    for product in (Product.FCR_N, Product.FCR_D_UP, Product.FCR_D_DOWN):
        periods = sine_periods(product)
        runs = []
        for period, _stationary, total in periods:
            sig = sine_test(product, period, total, dt)
            runs.append((sig, activated_power(simulate_signal(cfg, sig, battery))))
        c = tested_capacity(cfg, product)
        stationary = {p: s for p, s, _ in periods}
        points = evaluate_sine_tests(product, runs, c, stationary)
        run.transfer[product] = points
        run.results += evaluate_frequency_domain(product, points)

    for product, steps in (
        (Product.FCR_N, TABLE12_FCR_N),
        (Product.FCR_D_UP, TABLE13_FCR_D),
        (Product.FCR_D_DOWN, TABLE13_FCR_D),
    ):
        c = tested_capacity(cfg, product)
        e0 = ler_initial_energy(cfg, product, battery)
        sim = FcrUnitSimulator(battery, cfg.fcr, single_product_schedule(product, c), e0, 1.0)
        ler = run_ler_test(sim, product, steps)
        run.ler[product] = ler
        run.results.append(evaluate_r12_ler(ler))
    return run


def results_table(results: list[RequirementResult]) -> pd.DataFrame:
    """Requirement results as a table (one row per check)."""
    return pd.DataFrame(
        [
            {
                "requirement": r.requirement,
                "product": r.product,
                "measured": r.measured,
                "unit": r.unit,
                "threshold": r.threshold,
                "passed": r.passed,
                "explanation": r.explanation,
            }
            for r in results
        ]
    )
