"""Run the 2025 market backtest for strategies S0-S3.

Writes results/revenue_summary.csv, one schedule per strategy in
results/backtest_<strategy>.parquet (input to the simulation) and three figures in
docs/figures/. Every solved day is checked against constraints 1-7.

Usage: uv run python scripts/run_backtest.py --config configs/base.yaml
"""

from __future__ import annotations

import argparse
import logging

import matplotlib.pyplot as plt
import pandas as pd

from nordic_bess.config import load_config
from nordic_bess.market import kpis
from nordic_bess.market.inputs import load_backtest_prices
from nordic_bess.market.milp import MilpParams
from nordic_bess.market.strategies import STRATEGIES, run_backtest
from nordic_bess.reporting import market_plots
from nordic_bess.reporting.style import DPI

log = logging.getLogger("run_backtest")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--strategies", nargs="+", default=list(STRATEGIES))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("pyomo").setLevel(logging.WARNING)  # HiGHS logs every solve at INFO

    cfg = load_config(args.config)
    params = MilpParams.from_config(cfg)
    prices = load_backtest_prices(cfg)
    log.info(
        "%d days, FCR series '%s', %d hours without an auction",
        len(prices.days),
        cfg.market.fcr_price_series,
        prices.n_fcr_hours_without_auction,
    )
    cfg.paths.results.mkdir(parents=True, exist_ok=True)
    cfg.paths.figures.mkdir(parents=True, exist_ok=True)

    rows, results = [], {}
    for name in args.strategies:
        result = run_backtest(prices, params, STRATEGIES[name], cfg.market.solver)
        results[name] = result
        result.schedule.to_parquet(cfg.paths.results / f"backtest_{name}.parquet")
        rows.append(kpis.summarise(result, params))
        log.info(
            "%s solved in %.1f s, max violation %.2e",
            name,
            result.solve_time_s,
            result.max_violation,
        )

    summary = pd.DataFrame(rows)
    summary.round(4).to_csv(cfg.paths.results / "revenue_summary.csv", index=False)

    fig = market_plots.revenue_by_strategy(summary, params.p_max_mw)
    fig.savefig(cfg.paths.figures / "market_revenue_by_strategy.png", dpi=DPI)
    plt.close(fig)
    if "S3" in results:
        s3 = results["S3"]
        fig = market_plots.monthly_revenue(kpis.monthly_revenue(s3, params), "S3")
        fig.savefig(cfg.paths.figures / "market_monthly_revenue_s3.png", dpi=DPI)
        plt.close(fig)
        fig = market_plots.allocation_heatmap(
            kpis.allocation_by_hour_and_month(s3), "S3", params.p_max_mw
        )
        fig.savefig(cfg.paths.figures / "market_allocation_heatmap_s3.png", dpi=DPI)
        plt.close(fig)
        binding = kpis.binding_shares(s3, params)
        print("S3 share of hours with a binding constraint:", binding)

    cols = {
        "strategy": "strategy",
        "rev_da_eur": "DA kEUR",
        "rev_fcr_n_eur": "N kEUR",
        "rev_fcr_dup_eur": "Dup kEUR",
        "rev_fcr_ddown_eur": "Ddown kEUR",
        "cost_degradation_eur": "deg kEUR",
        "net_eur": "net kEUR",
        "eur_per_mw_year": "kEUR/MW-yr",
        "cycles_per_year": "cycles/yr",
        "solve_time_s": "solve s",
    }
    view = summary[list(cols)].rename(columns=cols)
    for c in view.columns[1:8]:
        view[c] = view[c] / 1e3
    print(view.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
