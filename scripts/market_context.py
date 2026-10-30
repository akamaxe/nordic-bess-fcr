"""Yearly FCR capacity prices since 2021 for the executive summary (PLAN M6).

Reads data/processed/fcr_prices_se3.parquet (written by scripts/fetch_data.py) and writes
results/fcr_price_history.csv: mean price per product and calendar year (UTC), for the
volume-weighted 'total' series. Before 2024-02-01 Svk published average, not marginal,
prices (docs/DATA.md), so earlier years are indicative only.

Usage: uv run python scripts/market_context.py --config configs/base.yaml
"""

from __future__ import annotations

import argparse

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from nordic_bess.config import load_config
from nordic_bess.data import catalog
from nordic_bess.data.svk_fcr import load_fcr_prices
from nordic_bess.reporting.style import DPI, INK, STREAM_COLORS, new_figure


def history_figure(out: pd.DataFrame):
    """Yearly mean FCR capacity price per product (grouped bars)."""
    fig, ax = new_figure(8.0, 3.8)
    x = np.arange(len(out))
    cols = {
        "FCR-N": "fcr_n_eur_per_mw_h",
        "FCR-D up": "fcr_dup_eur_per_mw_h",
        "FCR-D down": "fcr_ddown_eur_per_mw_h",
    }
    width = 0.26
    for i, (label, col) in enumerate(cols.items()):
        ax.bar(
            x + (i - 1) * width,
            out[col],
            width,
            color=STREAM_COLORS[label],
            label=label,
            edgecolor=ax.get_facecolor(),
            linewidth=0.6,
        )
    ax.set_xticks(x, out["year"].astype(str))
    ax.set_ylabel("Mean capacity price [EUR/MW/h]")
    ax.set_title(
        "FCR capacity prices, SE3 (volume-weighted, marginal pricing from 2024)",
        loc="left",
        fontsize=10,
    )
    ax.legend(loc="upper right")
    ax.grid(axis="x", visible=False)
    for xi, v in zip(x, out["fcr_n_eur_per_mw_h"], strict=True):
        ax.annotate(
            f"{v:.0f}",
            (xi - width, v),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            fontsize=7,
            color=INK,
        )
    fig.tight_layout()
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/base.yaml")
    args = parser.parse_args()
    cfg = load_config(args.config)
    prices = load_fcr_prices(catalog.fcr_prices_path(cfg), "total")
    prices = prices[(prices.index >= "2021-01-01") & (prices.index < "2026-01-01")]
    yearly = prices.groupby(prices.index.year).agg(["mean", "count"])
    out = pd.DataFrame(
        {
            "year": yearly.index,
            "fcr_n_eur_per_mw_h": yearly[("price_fcr_n_eur_per_mw_h", "mean")].to_numpy(),
            "fcr_dup_eur_per_mw_h": yearly[("price_fcr_dup_eur_per_mw_h", "mean")].to_numpy(),
            "fcr_ddown_eur_per_mw_h": yearly[("price_fcr_ddown_eur_per_mw_h", "mean")].to_numpy(),
            "hours_fcr_n": yearly[("price_fcr_n_eur_per_mw_h", "count")].to_numpy(),
        }
    )
    out["marginal_pricing"] = out["year"] >= 2024
    out.round(2).to_csv(cfg.paths.results / "fcr_price_history.csv", index=False)
    fig = history_figure(out)
    fig.savefig(cfg.paths.figures / "market_fcr_price_history.png", dpi=DPI)
    plt.close(fig)
    print(out.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
