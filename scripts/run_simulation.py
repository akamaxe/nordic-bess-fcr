"""Simulate one week of measured frequency with the S3 schedule (PLAN M3).

Drives the BESS model at 1 s with Fingrid 1 Hz frequency and the hourly baseline and
capacities from results/backtest_S3.parquet (run scripts/run_backtest.py first; without
it the script falls back to a constant C_N = 5 MW as PLAN M3 allows). Writes
results/simulation_kpis.csv, results/simulation_week_<S>.parquet and two figures.

Usage: uv run python scripts/run_simulation.py --config configs/base.yaml [--strategy S3]
"""

from __future__ import annotations

import argparse
import logging
import time

import matplotlib.pyplot as plt
import pandas as pd

from nordic_bess.config import load_config
from nordic_bess.control.endurance import endurance_minutes
from nordic_bess.data import catalog
from nordic_bess.data.fingrid import FREQ_COLUMN, fill_short_gaps, months_covering
from nordic_bess.plant.battery import BatteryParams
from nordic_bess.reporting import simulation_plots
from nordic_bess.reporting.style import DPI
from nordic_bess.sim.engine import Schedule, simulate
from nordic_bess.sim.kpis import simulation_kpis

log = logging.getLogger("run_simulation")


def load_week_frequency(cfg) -> pd.Series:
    w0, w1 = cfg.simulation.week_start, cfg.simulation.week_end
    parts = [
        pd.read_parquet(catalog.frequency_path(cfg, y, m, 1))[FREQ_COLUMN]
        for y, m in months_covering(w0, w1)
    ]
    f = pd.concat(parts).sort_index()
    f = f[(f.index >= w0) & (f.index < w1)].astype(float)
    expected = pd.date_range(w0, w1, freq="1s", inclusive="left")
    f = f.reindex(expected)
    f, n_filled = fill_short_gaps(f, cfg.simulation.max_frequency_gap_s)
    log.info("frequency week: %d s, %d s interpolated", len(f), n_filled)
    return f


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--strategy", default="S3")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = load_config(args.config)
    w0, w1 = cfg.simulation.week_start, cfg.simulation.week_end
    f = load_week_frequency(cfg)
    bt_path = cfg.paths.results / f"backtest_{args.strategy}.parquet"
    if bt_path.exists():
        planned = pd.read_parquet(bt_path)
        planned = planned[(planned.index >= w0) & (planned.index < w1)]
        schedule = Schedule.from_backtest(planned, w0, w1)
        label = args.strategy
    else:
        log.warning("%s not found: constant C_N = 5 MW", bt_path.name)
        planned, schedule, label = None, Schedule.constant(c_n_mw=5.0), "constant C_N = 5 MW"

    battery = BatteryParams.from_config(cfg)
    e0 = cfg.bess.e_target_mwh
    t0 = time.perf_counter()
    df = simulate(
        f.to_numpy(), cfg.simulation.long_horizon_step_s, schedule, battery, cfg.fcr, e0, start=w0
    )
    elapsed = time.perf_counter() - t0

    kpis = simulation_kpis(df, battery, e0)
    # Endurance per product while it is sold (FCR v1.1, eq. 27-28): FCR-N = min(up, down).
    nem_p = df[["p_nem_n_mw", "p_nem_dup_mw", "p_nem_ddown_mw"]].sum(axis=1)
    setpoint = df["p_base_mw"] + nem_p
    for sfx, use_up, use_down in (("n", True, True), ("dup", True, False), ("ddown", False, True)):
        c = df[f"c_{sfx}_mw"]
        sold = (c > 0).to_numpy()
        l_up, l_dn = endurance_minutes(
            df["e_mwh"], battery.e_min_mwh, battery.e_max_mwh, setpoint, c, c
        )
        parts = [x for x, used in ((l_up, use_up), (l_dn, use_down)) if used]
        endurance = pd.Series(
            parts[0]
            if len(parts) == 1
            else pd.concat([pd.Series(parts[0]), pd.Series(parts[1])], axis=1)
            .min(axis=1)
            .to_numpy()
        )
        kpis[f"endurance_{sfx}_min_minutes"] = float(endurance[sold].min()) if sold.any() else None
    kpis["strategy"] = label
    kpis["simulation_runtime_s"] = elapsed

    cfg.paths.results.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cfg.paths.results / f"simulation_week_{args.strategy}.parquet")
    pd.DataFrame([kpis]).round(5).to_csv(cfg.paths.results / "simulation_kpis.csv", index=False)

    nem_any = (df[["nem_current_n", "nem_current_dup", "nem_current_ddown"]] != 0).any(axis=1)
    busiest = nem_any.groupby(df.index.floor("D")).sum().idxmax()
    fig = simulation_plots.day_overview(df, busiest, label)
    fig.savefig(cfg.paths.figures / f"simulation_day_{args.strategy.lower()}.png", dpi=DPI)
    plt.close(fig)
    if planned is not None:
        fig = simulation_plots.week_energy(df, planned, label)
        fig.savefig(
            cfg.paths.figures / f"simulation_week_energy_{args.strategy.lower()}.png", dpi=DPI
        )
        plt.close(fig)

    for k, v in kpis.items():
        print(f"{k:32s} {v:.4f}" if isinstance(v, float) else f"{k:32s} {v}")


if __name__ == "__main__":
    main()
