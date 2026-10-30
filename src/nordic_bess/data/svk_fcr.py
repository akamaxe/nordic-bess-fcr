"""FCR capacity prices from the Svenska kraftnat data portal (dataset "FCR Capacity Market").

The CSV dump has one row per hour, bidding zone, product, direction and procurement
round (``fcrAuction1`` = D-2, ``fcrAuction2`` = D-1). There is no "Total" round in the
data, so the ``total`` series is reconstructed here as the volume-weighted mean price
of the rounds held in each hour (see docs/DATA.md). Prices are marginal prices in
EUR/MW for a one-hour product, i.e. EUR/MW/h, identical for all zones of the joint
SE + DK2 market. Licence: CC BY 4.0.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

from nordic_bess.data.validation import DataValidationError, require_columns, validate_time_index

SVK_FCR_RESOURCE_ID = "72ef5ec0-d0d7-4d22-95e9-4f22b3048af4"
SVK_FCR_CSV_URL = f"https://data.svk.se/datastore/dump/{SVK_FCR_RESOURCE_ID}?format=csv"

#: (reserve_product, reserve_direction) in the Svk data -> product name used in the code.
PRODUCT_MAP: dict[tuple[str, str], str] = {
    ("FCRN", "symmetric"): "FCR_N",
    ("FCRD", "up"): "FCR_D_UP",
    ("FCRD", "down"): "FCR_D_DOWN",
}
AUCTION_ROUNDS = ("fcrAuction1", "fcrAuction2")
PRICE_SERIES = ("total", *AUCTION_ROUNDS)
PRICE_COLUMNS = {
    "FCR_N": "price_fcr_n_eur_per_mw_h",
    "FCR_D_UP": "price_fcr_dup_eur_per_mw_h",
    "FCR_D_DOWN": "price_fcr_ddown_eur_per_mw_h",
}
EXPECTED_COLUMNS = {
    "start_time_utc",
    "bidding_zone",
    "reserve_product",
    "reserve_direction",
    "auction_round",
    "price",
    "price_unit",
    "volume",
    "volume_unit",
}


def raw_csv_path(raw_dir: Path) -> Path:
    return raw_dir / "svk" / "fcr_capacity_market.csv"


def download_svk_fcr(raw_dir: Path, force: bool = False, timeout_s: float = 900.0) -> Path:
    """Download the full CSV dump (about 160 MB) unless it is cached."""
    path = raw_csv_path(raw_dir)
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with requests.get(SVK_FCR_CSV_URL, stream=True, timeout=timeout_s) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    tmp.replace(path)
    return path


def parse_svk_fcr(csv_path: Path, zone: str) -> pd.DataFrame:
    """Read the dump and return long-format rows for one bidding zone.

    Returns:
        Columns ``time_utc`` (tz-aware), ``product`` (FCR_N / FCR_D_UP / FCR_D_DOWN),
        ``auction_round``, ``price_eur_per_mw_h`` and ``volume_mw``.

    Raises:
        DataValidationError: On missing columns, unknown categorical values, unexpected
            units or duplicate (time, product, round) rows.
    """
    df = pd.read_csv(csv_path)
    require_columns(df.columns, EXPECTED_COLUMNS, "Svk FCR CSV")
    units = set(df["price_unit"].unique()) | set(df["volume_unit"].unique())
    if units != {"EUR-MW", "MW"}:
        raise DataValidationError(f"Svk FCR CSV: unexpected units {sorted(units)}")
    pairs = set(zip(df["reserve_product"], df["reserve_direction"], strict=True))
    if unknown := pairs - set(PRODUCT_MAP):
        raise DataValidationError(f"Svk FCR CSV: unknown product/direction {sorted(unknown)}")
    if unknown_rounds := set(df["auction_round"].unique()) - set(AUCTION_ROUNDS):
        raise DataValidationError(f"Svk FCR CSV: unknown auction rounds {sorted(unknown_rounds)}")

    sub = df[df["bidding_zone"] == zone]
    if sub.empty:
        raise DataValidationError(f"Svk FCR CSV: no rows for zone {zone}")
    out = pd.DataFrame(
        {
            "time_utc": pd.to_datetime(sub["start_time_utc"], utc=True),
            "product": [
                PRODUCT_MAP[(p, d)]
                for p, d in zip(sub["reserve_product"], sub["reserve_direction"], strict=True)
            ],
            "auction_round": sub["auction_round"].astype(str),
            "price_eur_per_mw_h": sub["price"].astype("float64"),
            "volume_mw": sub["volume"].astype("float64"),
        }
    )
    key = ["time_utc", "product", "auction_round"]
    if out.duplicated(key).any():
        raise DataValidationError(f"Svk FCR CSV: {int(out.duplicated(key).sum())} duplicate rows")
    return out.sort_values(key).reset_index(drop=True)


def fcr_price_table(long: pd.DataFrame, series: str = "total") -> pd.DataFrame:
    """Hourly FCR capacity prices per product in EUR/MW/h.

    Args:
        long: Output of :func:`parse_svk_fcr`.
        series: ``"total"`` (volume-weighted mean of the rounds held in each hour) or one
            auction round (``"fcrAuction1"``, ``"fcrAuction2"``).

    Returns:
        Wide table on an hourly UTC index with one column per product (see
        ``PRICE_COLUMNS``). Hours without any price for a product are NaN.
    """
    if series not in PRICE_SERIES:
        raise ValueError(f"series must be one of {PRICE_SERIES}, got {series!r}")
    if series == "total":
        weighted = long.assign(pv=long["price_eur_per_mw_h"] * long["volume_mw"])
        grouped = weighted.groupby(["time_utc", "product"])[["pv", "volume_mw"]].sum()
        price = (grouped["pv"] / grouped["volume_mw"]).rename("price")
    else:
        rows = long[long["auction_round"] == series]
        price = rows.set_index(["time_utc", "product"])["price_eur_per_mw_h"].rename("price")
    wide = price.unstack("product").rename(columns=PRICE_COLUMNS)
    wide = wide.reindex(columns=list(PRICE_COLUMNS.values()))
    wide.index.name = "time_utc"
    wide.columns.name = None
    return wide


def all_price_series(long: pd.DataFrame) -> pd.DataFrame:
    """Prices for every series, columns ``<price column>__<series>`` (stored in processed)."""
    parts = []
    for series in PRICE_SERIES:
        table = fcr_price_table(long, series)
        parts.append(table.add_suffix(f"__{series}"))
    out = pd.concat(parts, axis=1).sort_index()
    validate_time_index(out.index, "1h", "FCR prices")
    return out


def select_series(table: pd.DataFrame, series: str) -> pd.DataFrame:
    """Pick one price series from :func:`all_price_series` output, columns without suffix."""
    cols = [f"{c}__{series}" for c in PRICE_COLUMNS.values()]
    if missing := [c for c in cols if c not in table.columns]:
        raise DataValidationError(f"FCR prices: missing columns {missing}")
    out = table[cols].copy()
    out.columns = list(PRICE_COLUMNS.values())
    return out


def load_fcr_prices(path: Path, series: str) -> pd.DataFrame:
    """Read processed FCR prices and return the hourly table for ``series``."""
    table = pd.read_parquet(path)
    validate_time_index(table.index, "1h", "FCR prices")
    return select_series(table, series)
