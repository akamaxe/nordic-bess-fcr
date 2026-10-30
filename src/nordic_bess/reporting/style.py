"""Shared matplotlib style for all figures (PNG, dpi 150, saved under docs/figures/).

Colours follow the validated categorical palette in fixed order, one colour per entity
in every figure (a revenue stream keeps its colour across charts). Three slots sit
below 3:1 contrast on the light surface, so charts that use them carry a legend plus
direct labels, and the README shows the numbers as a table as well.
"""

from __future__ import annotations

import matplotlib as mpl
import matplotlib.pyplot as plt

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e4e3df"

# Categorical palette, fixed order (validated: lightness, chroma, CVD, normal vision).
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#6250d6",
    "#e34948",
)
STREAM_COLORS = {
    "Day-ahead": BLUE,
    "FCR-N": ORANGE,
    "FCR-D up": AQUA,
    "FCR-D down": YELLOW,
    "Degradation": MAGENTA,
}
SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DPI = 150


def apply_style() -> None:
    """Set recessive axes and grid, thin marks and the chart surface."""
    mpl.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_SECONDARY,
            "axes.titlecolor": INK,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.labelsize": 9,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.color": INK_SECONDARY,
            "ytick.color": INK_SECONDARY,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.frameon": False,
            "legend.fontsize": 8,
            "lines.linewidth": 1.5,
            "font.size": 9,
            "text.color": INK,
        }
    )


def sequential_cmap() -> mpl.colors.Colormap:
    """Single-hue (blue) light-to-dark colormap for magnitudes."""
    return mpl.colors.LinearSegmentedColormap.from_list("seq_blue", SEQUENTIAL_BLUE)


def new_figure(width_in: float = 8.0, height_in: float = 4.5, **kwargs):
    """Create a styled figure and axes."""
    apply_style()
    return plt.subplots(figsize=(width_in, height_in), **kwargs)
