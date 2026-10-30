"""Long-horizon simulation figures."""

from __future__ import annotations

import pandas as pd
from matplotlib.figure import Figure

from nordic_bess.reporting.style import BLUE, INK, INK_SECONDARY, ORANGE, RED, new_figure


def _shade(ax, mask: pd.Series, color: str, label: str) -> None:
    """Shade the time spans where ``mask`` is true."""
    if not mask.any():
        return
    edges = mask.astype(int).diff().fillna(mask.iloc[0].astype(int))
    starts = mask.index[edges == 1]
    ends = mask.index[edges == -1]
    if len(ends) < len(starts):
        ends = ends.append(pd.DatetimeIndex([mask.index[-1]]))
    for i, (a, b) in enumerate(zip(starts, ends, strict=True)):
        ax.axvspan(a, b, color=color, alpha=0.15, linewidth=0, label=label if i == 0 else None)


def day_overview(df: pd.DataFrame, day: pd.Timestamp, strategy: str) -> Figure:
    """Frequency, power and stored energy over one day with NEM/AEM shading."""
    d = df[(df.index >= day) & (df.index < day + pd.Timedelta(days=1))]
    fig, (ax_f, ax_p, ax_e) = new_figure(9.0, 6.6, nrows=3, sharex=True, height_ratios=(1, 1.3, 1))
    nem = (d[["nem_current_n", "nem_current_dup", "nem_current_ddown"]] != 0).any(axis=1)
    aem = d[["aem_n", "aem_dup", "aem_ddown"]].any(axis=1)
    ax_f.plot(d.index, d["f_hz"], color=INK_SECONDARY, linewidth=0.6)
    ax_f.axhspan(49.9, 50.1, color=BLUE, alpha=0.06, linewidth=0)
    ax_f.set_ylabel("Frequency [Hz]")
    ax_f.set_title(f"{strategy} schedule on measured frequency, {day:%Y-%m-%d} (UTC)", loc="left")
    ax_p.plot(d.index, d["p_out_mw"], color=ORANGE, linewidth=0.6, label="BESS output")
    ax_p.plot(d.index, d["p_base_mw"], color=INK, linewidth=1.0, label="Day-ahead baseline")
    ax_p.set_ylabel("Power [MW]")
    ax_e.plot(d.index, d["e_mwh"], color=INK, linewidth=1.2)
    ax_e.set_ylabel("Stored energy [MWh]")
    for ax in (ax_p, ax_e):
        _shade(ax, nem, BLUE, "NEM active")
        _shade(ax, aem, RED, "AEM active")
    ax_p.legend(loc="upper right", ncols=4)
    ax_e.set_xlabel("Time (UTC)")
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def week_energy(df: pd.DataFrame, planned: pd.DataFrame, strategy: str) -> Figure:
    """Simulated stored energy against the MILP plan (FCR activation is not planned)."""
    fig, ax = new_figure(9.0, 3.6)
    ax.plot(df.index, df["e_mwh"], color=ORANGE, linewidth=1.0, label="Simulated")
    ax.step(
        planned.index,
        planned["e_start_mwh"],
        where="post",
        color=INK,
        linewidth=1.0,
        label="MILP plan (no FCR activation)",
    )
    ax.set_ylabel("Stored energy [MWh]")
    ax.set_title(f"{strategy} week: stored energy, plan versus simulation", loc="left")
    ax.legend(loc="upper right")
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig
