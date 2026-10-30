"""Market-layer figures: revenue by strategy, monthly revenue, S3 allocation.

Functions return matplotlib figures; scripts save them (PNG, dpi 150).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from nordic_bess.market.kpis import STREAMS
from nordic_bess.reporting.style import (
    INK,
    INK_SECONDARY,
    STREAM_COLORS,
    new_figure,
    sequential_cmap,
)

GAP = 0.6  # white gap between stacked segments (points)


def _stacked_bars(ax, labels, table: pd.DataFrame, width: float = 0.6) -> None:
    """Stack positive streams upwards and negative ones downwards from zero."""
    x = np.arange(len(labels))
    pos = np.zeros(len(labels))
    neg = np.zeros(len(labels))
    for stream in table.columns:
        vals = table[stream].to_numpy()
        base = np.where(vals >= 0, pos, neg)
        ax.bar(
            x,
            vals,
            width,
            bottom=base,
            color=STREAM_COLORS[stream],
            label=stream,
            edgecolor=ax.get_facecolor(),
            linewidth=GAP,
        )
        pos = np.where(vals >= 0, pos + vals, pos)
        neg = np.where(vals < 0, neg + vals, neg)
    ax.axhline(0, color=INK_SECONDARY, linewidth=0.8)
    ax.set_xticks(x, labels)


def revenue_by_strategy(summary: pd.DataFrame, p_max_mw: float) -> Figure:
    """Stacked revenue per stream for each strategy, in kEUR per MW-year."""
    fig, ax = new_figure(8.0, 4.6)
    scale = 1e3 * p_max_mw * summary["hours"].to_numpy()[:, None] / 8760.0
    table = pd.DataFrame(summary[list(STREAMS)].to_numpy() / scale, columns=list(STREAMS.values()))
    labels = [f"{s}\n{d}" for s, d in zip(summary["strategy"], summary["description"], strict=True)]
    labels = [lbl.replace(" co-optimised", "\nco-optimised") for lbl in labels]
    _stacked_bars(ax, labels, table)
    for i, total in enumerate(summary["eur_per_mw_year"].to_numpy() / 1e3):
        top = table.clip(lower=0).sum(axis=1).iloc[i]
        ax.annotate(
            f"{total:.0f}",
            (i, top),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            color=INK,
            fontsize=9,
            fontweight="bold",
        )
    ax.set_ylabel("kEUR per MW-year (net in bold)")
    ax.set_title("Revenue by strategy, SE3 2025 (perfect foresight)", loc="left")
    ax.legend(ncols=5, loc="upper left", bbox_to_anchor=(0, -0.22))
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


def monthly_revenue(monthly: pd.DataFrame, strategy: str) -> Figure:
    """Stacked monthly revenue per stream in kEUR for one strategy."""
    fig, ax = new_figure(8.0, 4.2)
    labels = [p.strftime("%b") for p in monthly.index]
    _stacked_bars(ax, labels, monthly / 1e3, width=0.7)
    ax.set_ylabel("kEUR per month")
    ax.set_title(f"Monthly revenue by stream, {strategy}", loc="left")
    ax.legend(ncols=5, loc="upper left", bbox_to_anchor=(0, -0.1))
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig


def allocation_heatmap(heatmaps: dict[str, pd.DataFrame], strategy: str, p_max_mw: float) -> Figure:
    """Mean capacity sold per product by hour of day (UTC) and month."""
    fig, axes = new_figure(10.0, 3.6, ncols=len(heatmaps), sharey=True)
    cmap = sequential_cmap()
    for ax, (label, table) in zip(axes, heatmaps.items(), strict=True):
        im = ax.imshow(
            table.to_numpy(),
            aspect="auto",
            origin="lower",
            cmap=cmap,
            vmin=0,
            vmax=p_max_mw,
            extent=(0.5, 12.5, -0.5, 23.5),
        )
        ax.set_title(label, loc="left", fontsize=10)
        ax.set_xticks([1, 4, 7, 10], ["Jan", "Apr", "Jul", "Oct"])
        ax.grid(visible=False)
    axes[0].set_ylabel("Hour of day (UTC)")
    axes[0].set_yticks([0, 6, 12, 18, 23])
    cbar = fig.colorbar(im, ax=axes, shrink=0.9, pad=0.02)
    cbar.set_label("Mean capacity sold [MW]")
    fig.suptitle(f"{strategy} capacity allocation by hour and month", x=0.01, ha="left")
    return fig
