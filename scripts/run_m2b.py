"""Market realism cases for the S3 strategy (PLAN M2b).

Compares the perfect-foresight S3 backtest with sequential decisions on naive forecasts
(value of perfect information), with 15-minute day-ahead prices and with the single
auction-round FCR price series. Writes results/m2b_summary.csv and
docs/figures/market_m2b_cases.png. Run scripts/fetch_data.py first.

Usage: uv run python scripts/run_m2b.py --config configs/base.yaml
"""

from __future__ import annotations

import argparse
import dataclasses
import logging

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from nordic_bess.config import load_config
from nordic_bess.market import kpis
from nordic_bess.market.inputs import load_backtest_prices
from nordic_bess.market.milp import MilpParams
from nordic_bess.market.sequential import FORECAST_LAG, naive_forecast, run_sequential
from nordic_bess.market.stochastic import run_stochastic
from nordic_bess.market.strategies import STRATEGIES, run_backtest
from nordic_bess.reporting.style import BLUE, DPI, INK, INK_SECONDARY, new_figure

log = logging.getLogger("run_m2b")
REFERENCE = "S3 perfect foresight (hourly, total FCR prices)"


def cases_figure(summary: pd.DataFrame):
    fig, ax = new_figure(8.5, 3.8)
    y = np.arange(len(summary))[::-1]
    vals = summary["eur_per_mw_year"].to_numpy() / 1e3
    colors = [INK_SECONDARY if c == REFERENCE else BLUE for c in summary["case"]]
    ax.barh(y, vals, color=colors, height=0.6)
    for yi, v in zip(y, vals, strict=True):
        ax.annotate(
            f"{v:.1f}",
            (v, yi),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            color=INK,
            fontsize=8,
        )
    ax.set_yticks(y, summary["case"])
    ax.set_xlabel("Net revenue [kEUR per MW-year]")
    ax.set_title("S3 under market realism (SE3, 2025)", loc="left")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, vals.max() * 1.12)
    fig.tight_layout()
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/base.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("pyomo").setLevel(logging.WARNING)
    cfg = load_config(args.config)
    params = MilpParams.from_config(cfg)
    solver = cfg.market.solver
    s, e = cfg.market.backtest_start, cfg.market.backtest_end
    s3 = STRATEGIES["S3"]

    rows = []

    def add(case: str, result) -> None:
        row = kpis.summarise(result, params)
        rows.append(
            {
                "case": case,
                **{
                    k: row[k]
                    for k in ("net_eur", "eur_per_mw_year", "cycles_per_year", "solve_time_s")
                },
            }
        )
        log.info(
            "%s: %.1f kEUR/MW-yr (%.0f s)", case, row["eur_per_mw_year"] / 1e3, row["solve_time_s"]
        )

    hourly = load_backtest_prices(cfg)
    add(REFERENCE, run_backtest(hourly, params, s3, solver))

    extended = load_backtest_prices(cfg, start=s - FORECAST_LAG)
    forecast = naive_forecast(extended, s, e)
    add(
        "S3 sequential: FCR bids on forecast, DA perfect",
        run_sequential(hourly, forecast, params, solver, "fcr_forecast"),
    )
    add(
        "S3 sequential: FCR and DA on forecast",
        run_sequential(hourly, forecast, params, solver, "all_forecast"),
    )

    n = cfg.market.scenario_weeks
    history = load_backtest_prices(cfg, start=s - pd.Timedelta(weeks=n))
    add(
        f"S3 stochastic: FCR bids on {n} past-week scenarios, DA perfect",
        run_stochastic(hourly, history, params, solver, n),
    )

    quarter = load_backtest_prices(cfg, periods_per_hour=4)
    add("S3 perfect foresight, 15-min day-ahead", run_backtest(quarter, params, s3, solver))
    for series in ("fcrAuction1", "fcrAuction2"):
        prices = load_backtest_prices(cfg, series=series)
        log.info("%s: %d hours without an auction", series, prices.n_fcr_hours_without_auction)
        add(
            f"S3 perfect foresight, FCR prices of {series} only",
            run_backtest(prices, params, s3, solver),
        )

    # Regulatory sensitivity: the TSOs foresee 1-1.5 h of FCR-N energy per direction
    # (FCR v1.1, section 3.5 note); 1.5 h tightens the energy reservation (constraints 5-6).
    params_15 = dataclasses.replace(params, energy_hours_n=1.5)
    add(
        "S3 perfect foresight, FCR-N energy reservation 1.5 h",
        run_backtest(hourly, params_15, s3, solver),
    )

    summary = pd.DataFrame(rows)
    ref = summary.loc[summary["case"] == REFERENCE, "eur_per_mw_year"].iloc[0]
    summary["delta_vs_reference_eur_per_mw_year"] = summary["eur_per_mw_year"] - ref
    is_forecast = summary["case"].str.contains("forecast|stochastic")
    summary["vpi_eur_per_mw_year"] = np.where(is_forecast, ref - summary["eur_per_mw_year"], np.nan)
    cfg.paths.results.mkdir(parents=True, exist_ok=True)
    summary.round(2).to_csv(cfg.paths.results / "m2b_summary.csv", index=False)
    fig = cases_figure(summary)
    fig.savefig(cfg.paths.figures / "market_m2b_cases.png", dpi=DPI)
    plt.close(fig)
    view = summary[
        ["case", "eur_per_mw_year", "delta_vs_reference_eur_per_mw_year", "cycles_per_year"]
    ].copy()
    view.iloc[:, 1:3] = view.iloc[:, 1:3] / 1e3
    print(view.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
