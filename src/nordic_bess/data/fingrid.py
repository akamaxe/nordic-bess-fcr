"""Nordic grid frequency at 10 Hz from Fingrid open data (dataset 339, CC BY 4.0).

Fingrid publishes one 7z archive per month with one CSV per day (``Time,Value``).
Timestamps are naive Finnish local time (UTC+2, UTC+3 in DST): the DST-start day has
no 03:xx hour. :func:`read_day_csv` localises to Europe/Helsinki and converts to UTC.
The archives contain a few duplicate timestamps (dropped, first kept) and short gaps
(kept as gaps; :func:`fill_short_gaps` fills them for simulation when they are short).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from nordic_bess.data.validation import DataValidationError, GapReport, validate_time_index

FINGRID_DATASET_ID = 339
FINGRID_URL = "https://data.fingrid.fi/files/339/{year}/{year}-{month:02d}.7z"
FREQ_COLUMN = "f_hz"


def archive_path(raw_dir: Path, year: int, month: int) -> Path:
    return raw_dir / "fingrid" / f"{year}-{month:02d}.7z"


def download_month(
    raw_dir: Path, year: int, month: int, force: bool = False, timeout_s: float = 900.0
) -> Path:
    """Download the monthly 7z archive unless it is cached."""
    path = archive_path(raw_dir, year, month)
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    url = FINGRID_URL.format(year=year, month=month)
    with requests.get(url, stream=True, timeout=timeout_s) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    tmp.replace(path)
    return path


def extract_month(archive: Path, force: bool = False) -> Path:
    """Extract a monthly archive next to it and return the folder with the daily CSVs.

    Uses the system ``tar`` (bsdtar/libarchive, shipped with Windows 10+ and macOS),
    which reads 7z; GNU tar does not, so on Linux install ``bsdtar`` or extract by hand.
    """
    folder = archive.with_suffix("")
    if folder.is_dir() and any(folder.glob("*.csv")) and not force:
        return folder
    tar = shutil.which("bsdtar") or shutil.which("tar")
    if tar is None:
        raise RuntimeError("no tar/bsdtar found to extract the Fingrid 7z archive")
    listing = subprocess.run(
        [tar, "-tf", str(archive)], check=True, capture_output=True, text=True
    ).stdout.split()
    if any(name.startswith(("/", "\\")) or ".." in Path(name).parts for name in listing):
        raise DataValidationError(f"{archive.name}: archive contains unsafe paths")
    subprocess.run([tar, "-xf", str(archive), "-C", str(archive.parent)], check=True)
    if not any(folder.glob("*.csv")):
        raise DataValidationError(f"{archive.name}: expected daily CSVs in {folder}")
    return folder


def read_day_csv(path: Path) -> pd.Series:
    """Read one daily CSV into a 10 Hz frequency series in Hz on a UTC index."""
    df = pd.read_csv(path, dtype={"Value": "float64"})
    if list(df.columns) != ["Time", "Value"]:
        raise DataValidationError(f"{path.name}: expected columns ['Time', 'Value']")
    local = pd.to_datetime(df["Time"], format="%Y-%m-%d %H:%M:%S.%f")
    # ambiguous="infer" resolves the repeated hour on the DST-end day from file order.
    utc = local.dt.tz_localize("Europe/Helsinki", ambiguous="infer", nonexistent="raise")
    s = pd.Series(df["Value"].to_numpy(), index=pd.DatetimeIndex(utc).tz_convert("UTC"))
    s.index.name = "time_utc"
    return s.rename(FREQ_COLUMN)


def load_month(folder: Path) -> tuple[pd.Series, GapReport, int]:
    """Concatenate all daily CSVs of a month.

    Returns:
        The 10 Hz series, its gap report and the number of duplicate timestamps dropped.
    """
    files = sorted(folder.glob("*.csv"))
    if not files:
        raise DataValidationError(f"no CSV files in {folder}")
    s = pd.concat([read_day_csv(f) for f in files]).sort_index(kind="stable")
    dup = s.index.duplicated(keep="first")
    s = s[~dup]
    if s.isna().any() or not ((s > 45.0) & (s < 55.0)).all():
        raise DataValidationError(f"{folder.name}: NaN or implausible frequency values")
    report = validate_time_index(s.index, "100ms", f"Fingrid 10 Hz {folder.name}")
    return s, report, int(dup.sum())


def to_1hz(f_10hz: pd.Series) -> pd.Series:
    """Mean frequency per second (label = start of the second); empty seconds stay NaN."""
    out = f_10hz.resample("1s").mean()
    out.index.name = "time_utc"
    return out.rename(FREQ_COLUMN)


def fill_short_gaps(f: pd.Series, max_gap_s: float) -> tuple[pd.Series, int]:
    """Linearly interpolate NaN runs of at most ``max_gap_s`` seconds.

    Returns:
        The filled series and the number of samples filled.

    Raises:
        DataValidationError: If a NaN run is longer than ``max_gap_s`` or touches either
            end of the series (cannot be interpolated).
    """
    isna = f.isna().to_numpy()
    if not isna.any():
        return f, 0
    if isna[0] or isna[-1]:
        raise DataValidationError("frequency gap at the start or end of the window")
    step_s = (f.index[1] - f.index[0]).total_seconds()
    edges = np.flatnonzero(np.diff(np.r_[0, isna.astype(np.int8), 0]))
    runs = edges.reshape(-1, 2)
    longest = int((runs[:, 1] - runs[:, 0]).max()) * step_s
    if longest > max_gap_s:
        raise DataValidationError(f"frequency gap of {longest:.0f} s exceeds {max_gap_s:.0f} s")
    return f.interpolate(method="time", limit_area="inside"), int(isna.sum())


def months_covering(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[int, int]]:
    """(year, month) archives needed for ``[start, end)`` UTC, in Finnish local months."""
    lo = start.tz_convert("Europe/Helsinki")
    hi = (end - pd.Timedelta("1ns")).tz_convert("Europe/Helsinki")
    months = pd.period_range(lo.strftime("%Y-%m"), hi.strftime("%Y-%m"), freq="M")
    return [(p.year, p.month) for p in months]
