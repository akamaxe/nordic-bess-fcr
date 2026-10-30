"""Time-index validation shared by all loaders.

Every loader calls :func:`validate_time_index` before returning data. It fails loudly
on a naive or non-UTC index, a non-monotonic index, duplicate timestamps or steps that
are not a multiple of the expected resolution, and returns a :class:`GapReport` that
lists the missing periods.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


class DataValidationError(ValueError):
    """Raised when a time series violates the loader contract."""


@dataclass(frozen=True)
class Gap:
    """A run of missing samples between two consecutive timestamps."""

    after: pd.Timestamp  # last timestamp before the gap
    before: pd.Timestamp  # first timestamp after the gap
    n_missing: int


@dataclass(frozen=True)
class GapReport:
    """Summary of the coverage of a time series at a given resolution."""

    name: str
    resolution: pd.Timedelta
    start: pd.Timestamp
    end: pd.Timestamp  # last timestamp
    n_points: int
    n_missing: int
    gaps: tuple[Gap, ...] = field(default_factory=tuple)

    @property
    def coverage(self) -> float:
        """Share of expected samples that are present (1.0 = no gaps)."""
        expected = self.n_points + self.n_missing
        return self.n_points / expected if expected else 1.0

    @property
    def longest_gap(self) -> pd.Timedelta:
        """Duration of the longest gap (zero when there are none)."""
        if not self.gaps:
            return pd.Timedelta(0)
        return max(g.before - g.after for g in self.gaps) - self.resolution

    def summary(self) -> str:
        """One-line ASCII summary for logs."""
        return (
            f"{self.name}: {self.n_points} points at {self.resolution}, "
            f"{self.start} -> {self.end}, {len(self.gaps)} gaps, "
            f"{self.n_missing} missing samples (coverage {self.coverage:.5f}, "
            f"longest gap {self.longest_gap})"
        )


def validate_time_index(
    index: pd.DatetimeIndex,
    resolution: pd.Timedelta | str,
    name: str,
    *,
    max_gaps_listed: int = 50,
) -> GapReport:
    """Check that ``index`` is a clean UTC grid at ``resolution`` and report its gaps.

    Args:
        index: Timestamps to check.
        resolution: Expected spacing, e.g. ``"1h"`` or ``"100ms"``.
        name: Series name used in messages.
        max_gaps_listed: Number of gaps kept in the report (the largest ones).

    Raises:
        DataValidationError: If the index is empty, naive, not UTC, not strictly
            increasing, or has a step that is not a positive multiple of ``resolution``.
    """
    res = pd.Timedelta(resolution)
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        raise DataValidationError(f"{name}: expected a non-empty DatetimeIndex")
    if index.tz is None or str(index.tz) != "UTC":
        raise DataValidationError(f"{name}: index must be tz-aware UTC, got {index.tz}")
    if index.has_duplicates:
        n = int(index.duplicated().sum())
        raise DataValidationError(f"{name}: {n} duplicate timestamps")
    if not index.is_monotonic_increasing:
        raise DataValidationError(f"{name}: index is not monotonic increasing")

    steps = index.to_series().diff().dropna()
    off_grid = steps[(steps % res) != pd.Timedelta(0)]
    if len(off_grid):
        raise DataValidationError(
            f"{name}: {len(off_grid)} steps are not multiples of {res}, "
            f"first at {off_grid.index[0]} ({off_grid.iloc[0]})"
        )
    if (index.as_unit("ns").asi8 % res.value != 0).any():
        raise DataValidationError(f"{name}: timestamps are not aligned to a {res} grid")

    big = steps[steps > res]
    gaps = [
        Gap(after=ts - step, before=ts, n_missing=int(step / res) - 1) for ts, step in big.items()
    ]
    n_missing = sum(g.n_missing for g in gaps)
    gaps.sort(key=lambda g: g.n_missing, reverse=True)
    return GapReport(
        name=name,
        resolution=res,
        start=index[0],
        end=index[-1],
        n_points=len(index),
        n_missing=n_missing,
        gaps=tuple(gaps[:max_gaps_listed]),
    )


def require_columns(columns: pd.Index, expected: set[str], name: str) -> None:
    """Fail loudly when a table lacks expected columns."""
    if missing := expected - set(columns):
        raise DataValidationError(f"{name}: missing columns {sorted(missing)}")
