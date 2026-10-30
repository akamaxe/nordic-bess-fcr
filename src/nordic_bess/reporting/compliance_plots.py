"""Compliance figures (PLAN M4): step and ramp responses, Nyquist, closed loop, LER test."""

from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.patches import Circle

from nordic_bess.compliance import freqdomain as fd
from nordic_bess.compliance.evaluate import R2_SHARE, T_EVAL_S
from nordic_bess.compliance.ler import LerRun
from nordic_bess.compliance.runner import activated_power
from nordic_bess.compliance.signals import TestSignal
from nordic_bess.reporting.style import (
    AQUA,
    BLUE,
    INK,
    INK_SECONDARY,
    ORANGE,
    RED,
    YELLOW,
    new_figure,
)
from nordic_bess.sim.engine import SUFFIX
from nordic_bess.spec import Product

PRODUCT_COLORS = {Product.FCR_N: ORANGE, Product.FCR_D_UP: AQUA, Product.FCR_D_DOWN: YELLOW}
PRODUCT_LABELS = {
    Product.FCR_N: "FCR-N",
    Product.FCR_D_UP: "FCR-D up",
    Product.FCR_D_DOWN: "FCR-D down",
}


def fcr_n_step(sig: TestSignal, df: pd.DataFrame, c_mw: float) -> Figure:
    """Input frequency and activated power of the FCR-N step test (Table 3)."""
    fig, (ax_f, ax_p) = new_figure(8.0, 4.8, nrows=2, sharex=True, height_ratios=(1, 1.6))
    t_min = sig.t_s / 60
    ax_f.plot(t_min, sig.f_hz, color=INK_SECONDARY)
    ax_f.set_ylabel("Frequency [Hz]")
    ax_f.set_title("FCR-N step test (Table 3)", loc="left")
    ax_p.plot(t_min, activated_power(df), color=ORANGE, label="BESS activated power")
    ax_p.axhline(c_mw, color=INK_SECONDARY, linestyle="--", linewidth=0.8)
    ax_p.axhline(-c_mw, color=INK_SECONDARY, linestyle="--", linewidth=0.8)
    ax_p.annotate(
        f"+-{c_mw:g} MW (theoretical)",
        (0.3, c_mw),
        color=INK_SECONDARY,
        fontsize=8,
        xytext=(0, 3),
        textcoords="offset points",
    )
    ax_p.set_ylabel("Power [MW]")
    ax_p.set_xlabel("Time [min]")
    fig.tight_layout()
    return fig


def fcr_d_ramp(sig: TestSignal, df: pd.DataFrame, c_mw: float) -> Figure:
    """FCR-D ramp test overview and ramp 5 detail with the 7.5 s requirements."""
    fig = new_figure(10.0, 4.8)[0]
    fig.clf()
    gs = fig.add_gridspec(2, 2, width_ratios=(1.6, 1), height_ratios=(1, 1.4))
    ax_f = fig.add_subplot(gs[0, 0])
    ax_p = fig.add_subplot(gs[1, 0], sharex=ax_f)
    ax_z = fig.add_subplot(gs[:, 1])
    color = PRODUCT_COLORS[sig.product]
    p = activated_power(df)
    ax_f.plot(sig.t_s, sig.f_hz, color=INK_SECONDARY)
    ax_f.set_ylabel("Frequency [Hz]")
    ax_f.set_title(f"{PRODUCT_LABELS[sig.product]} fast ramp test (Table 4)", loc="left")
    ax_p.plot(sig.t_s, p, color=color)
    ax_p.set_ylabel("Activated power [MW]")
    ax_p.set_xlabel("Time [s]")

    t0 = sig.segment("ramp5").t_start_s
    sgn = 1.0 if sig.product is Product.FCR_D_UP else -1.0
    mask = (sig.t_s >= t0 - 2) & (sig.t_s <= t0 + 20)
    tz = sig.t_s[mask] - t0
    dp = sgn * (p[mask] - np.interp(t0, sig.t_s, p))
    ax_z.fill_between(
        tz,
        0,
        dp,
        where=(tz >= 0) & (tz <= T_EVAL_S),
        color=color,
        alpha=0.25,
        linewidth=0,
        label="E(7.5 s), Requirement 3",
    )
    ax_z.plot(tz, dp, color=color, label="Activated power")
    ax_z.axvline(T_EVAL_S, color=INK, linewidth=0.8)
    ax_z.axhline(
        R2_SHARE * c_mw,
        color=RED,
        linestyle="--",
        linewidth=1.0,
        label=f"{R2_SHARE:.2f} x |dP_th|, Requirement 2",
    )
    ax_z.set_xlabel("Time after the start of ramp 5 [s]")
    ax_z.set_ylabel("|Activated power| [MW]")
    ax_z.set_title("Ramp 5 detail", loc="left")
    ax_z.legend(loc="lower right")
    fig.tight_layout()
    return fig


def nyquist(transfer: dict[Product, list[fd.TransferPoint]]) -> Figure:
    """Open loop G0 = F G (stability parameters) near the critical point (Requirement 8)."""
    fig, ax = new_figure(6.4, 5.4)
    for product, points in transfer.items():
        pts = sorted(points, key=lambda tp: tp.omega_rad_s)
        w = np.array([tp.omega_rad_s for tp in pts])
        g0 = np.array([tp.f_complex for tp in pts]) * fd.power_system(
            w, fd.table7(product, "stability")
        )
        curve = fd.interpolate_curve(g0)
        style = "--" if product is Product.FCR_D_DOWN else "-"
        ax.plot(
            curve.real,
            curve.imag,
            style,
            color=PRODUCT_COLORS[product],
            label=PRODUCT_LABELS[product],
        )
        ax.plot(g0.real, g0.imag, "o", color=PRODUCT_COLORS[product], markersize=4)
    ax.add_patch(Circle((-1, 0), fd.NYQUIST_RADIUS, fill=False, color=RED, linewidth=1.2))
    ax.add_patch(
        Circle(
            (-1, 0),
            fd.NYQUIST_RADIUS * fd.NYQUIST_MARGIN,
            fill=False,
            color=RED,
            linewidth=0.8,
            linestyle=":",
        )
    )
    ax.plot(-1, 0, "x", color=RED)
    ax.set_xlim(-2.2, 3.0)
    ax.set_ylim(-3.2, 1.2)
    ax.set_aspect("equal")
    ax.axhline(0, color=INK_SECONDARY, linewidth=0.6)
    ax.axvline(0, color=INK_SECONDARY, linewidth=0.6)
    ax.set_xlabel("Re G0")
    ax.set_ylabel("Im G0")
    ax.set_title(
        "Nyquist, G0 = F G (curves continue to the right at long periods)", loc="left", fontsize=10
    )
    ax.annotate(
        "r = 0.43 around (-1, 0)",
        (-1, fd.NYQUIST_RADIUS),
        xytext=(0, 6),
        textcoords="offset points",
        ha="center",
        color=RED,
        fontsize=8,
    )
    ax.legend(loc="lower right")
    fig.tight_layout()
    return fig


def closed_loop(transfer: dict[Product, list[fd.TransferPoint]]) -> Figure:
    """Closed-loop magnitude against the performance requirement |1/D| (Requirement 9)."""
    groups = [(Product.FCR_N,), (Product.FCR_D_UP, Product.FCR_D_DOWN)]
    fig, axes = new_figure(9.0, 3.8, ncols=2, sharey=True)
    for ax, group in zip(axes, groups, strict=True):
        for product in group:
            if product not in transfer:
                continue
            grid, f_dense = fd.interpolate_f(transfer[product])
            perf = fd.table7(product, "performance")
            g = fd.power_system(grid, perf)
            gc = fd.K_MARGIN * np.abs(g / (1 + f_dense * g))
            style = "--" if product is Product.FCR_D_DOWN else "-"
            ax.loglog(
                1 / (grid / (2 * np.pi)),
                gc,
                style,
                color=PRODUCT_COLORS[product],
                label=f"{PRODUCT_LABELS[product]} closed loop",
            )
        grid = np.geomspace(2 * np.pi / 300, 2 * np.pi / 10, 200)
        ax.loglog(
            2 * np.pi / grid,
            np.abs(1 / fd.disturbance_profile(grid)),
            color=INK,
            linewidth=1.0,
            label="Requirement |1/D|",
        )
        ax.set_xlabel("Sine period [s]")
        ax.legend(loc="upper right")
    axes[0].set_ylabel("Magnitude [p.u.]")
    axes[0].set_title("Frequency-domain performance (Requirement 9)", loc="left")
    fig.tight_layout()
    return fig


def ler_test(run: LerRun, c_mw: float) -> Figure:
    """Frequency, power, stored energy and NEM/AEM states during an LER test."""
    sfx = SUFFIX[run.product]
    df = run.frame
    t = df["t_s"] / 60
    fig, axes = new_figure(9.0, 7.0, nrows=4, sharex=True, height_ratios=(1, 1.3, 1.3, 0.8))
    ax_f, ax_p, ax_e, ax_s = axes
    color = PRODUCT_COLORS[run.product]
    ax_f.plot(t, df["f_hz"], color=INK_SECONDARY)
    ax_f.set_ylabel("Hz")
    ax_f.set_title(
        f"{PRODUCT_LABELS[run.product]} energy-management test "
        f"(Table {'12' if run.product is Product.FCR_N else '13'}), C = {c_mw:g} MW",
        loc="left",
    )
    ax_p.plot(t, df["p_out_mw"], color=color, label="Output")
    ax_p.plot(t, df[f"p_nem_{sfx}_mw"], color=BLUE, label="NEM power")
    ax_p.set_ylabel("MW")
    ax_p.legend(loc="upper right", ncols=2)
    ax_e.plot(t, df["e_mwh"], color=INK)
    ax_e.set_ylabel("Stored energy [MWh]")
    ax_s.step(t, df[f"nem_allowed_{sfx}"].abs(), where="post", color=BLUE, label="NEM on")
    ax_s.step(t, df[f"aem_{sfx}"].astype(float) * 0.5, where="post", color=RED, label="AEM on")
    ax_s.set_yticks([0, 0.5, 1], ["off", "AEM", "NEM"])
    ax_s.set_xlabel("Time [min]")
    ax_s.legend(loc="upper right", ncols=2)
    for a, _b in run.bounds_s[1:]:
        for ax in axes:
            ax.axvline(a / 60, color="#d0cfca", linewidth=0.6)
    fig.tight_layout()
    return fig
