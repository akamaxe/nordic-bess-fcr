# Data sources

All three sources were downloaded and profiled on 2026-10-30 before the parsers were
written. `scripts/fetch_data.py` rebuilds everything below from scratch. Raw downloads
are cached in `data/raw/` (gitignored) and refreshed with `--force`. Inside the code
every timestamp is tz-aware UTC.

| Dataset | Source | Licence | Native resolution | Source timezone | Processed file |
| --- | --- | --- | --- | --- | --- |
| Day-ahead prices SE3 | ENTSO-E Transparency Platform via `entsoe-py` 0.8.1 | ENTSO-E Transparency Platform terms and conditions | 60 min until 2025-09-30 22:00 UTC, 15 min after | Europe/Stockholm | `data/processed/day_ahead_se3.parquet` |
| FCR capacity prices | Svenska kraftnät data portal, dataset "FCR Capacity Market" | CC BY 4.0 | 60 min | UTC column used | `data/processed/fcr_prices_se3.parquet` |
| Grid frequency 10 Hz | Fingrid open data, dataset 339 "Frequency - historical data" | CC BY 4.0 | 100 ms | Finnish local time (naive) | `data/processed/frequency_{10,1}hz_2025-03.parquet` |

## Day-ahead prices (ENTSO-E)

- Query: `EntsoePandasClient.query_day_ahead_prices("SE_3", start, end)` for
  `[backtest_start - lookback_days, backtest_end)` = 2024-12-04 to 2026-01-01 UTC. The
  28 days before the backtest are needed for the forecasts and scenarios.
- The response is in Europe/Stockholm local time and includes the end timestamp (97 rows
  for one 15-minute day). The loader converts to UTC and keeps `[start, end)`.
- Market time unit: hourly until delivery day 2025-09-30, 15 minutes from delivery day
  2025-10-01 (first 15-minute value at 2025-09-30 22:00 UTC). Validation checks each
  segment at its own resolution. The processed file keeps the native resolution;
  `to_hourly()` takes the arithmetic mean of the four quarters where a model needs hours.
- 2025 profile: 0 gaps, 0 duplicates, 0 NaN; min -25.05, max 518.28 EUR/MWh. The mean
  SE3 price in 2025 was 46.24 EUR/MWh (hourly mean over 8760 h).
- Unit: EUR/MWh (`price_eur_per_mwh`).

## FCR capacity prices (Svenska kraftnät)

- Resource `72ef5ec0-d0d7-4d22-95e9-4f22b3048af4`, CSV dump
  `https://data.svk.se/datastore/dump/72ef5ec0-d0d7-4d22-95e9-4f22b3048af4?format=csv`
  (about 160 MB, 1 194 543 rows). The dataset is marked "Discontinued"; the last data row
  is 2026-04-14 21:00 UTC, so 2025 is fully covered.
- Columns: `_id, start_time_sweden, start_time_utc, bidding_zone, reserve_product,
  reserve_direction, auction_round, price, price_unit, volume, volume_unit,
  soda_hashbyte, soda_identity`. The rows are not in time order.
- Categorical values:

  | Column | Values |
  | --- | --- |
  | `bidding_zone` | SE1, SE2, SE3, SE4, DK2 |
  | `reserve_product` / `reserve_direction` | FCRN / symmetric, FCRD / up, FCRD / down |
  | `auction_round` | fcrAuction1 (D-2), fcrAuction2 (D-1) |
  | `price_unit`, `volume_unit` | EUR-MW, MW |

- Mapping used in the code: (FCRN, symmetric) -> FCR_N, (FCRD, up) -> FCR_D_UP,
  (FCRD, down) -> FCR_D_DOWN. Unknown values make the parser fail.
- Prices are marginal prices in EUR/MW for a one-hour product, i.e. EUR/MW/h
  (`price_eur_per_mw_h`). In 2025 the price is identical in all five zones in every hour
  (joint SE + DK2 market; checked on 51 791 hour-product-round triples).
- There is no "Total" round. The `total` series used as the reference is the
  volume-weighted mean price of the rounds held in each hour. The last round on its own is
  kept as the sensitivity series `fcrAuction2`. It is not the reference because round 2 is
  thin (mean volume 10-74 MW against 39-203 MW in round 1) and spiky (FCR-D down up to
  2690 EUR/MW/h), and a price taker selling 10 MW would not get those prices.
- 2025 SE3 coverage: round 1 has all 8760 hours for every product; round 2 has all hours
  for FCR-D and 8611 hours for FCR-N. When a single round is selected, an hour without
  that round means no capacity can be sold in it (price 0 in the market model).
- 2025 means (EUR/MW/h):

  | Series | FCR-N | FCR-D up | FCR-D down |
  | --- | --- | --- | --- |
  | total (volume-weighted) | 26.43 | 5.86 | 5.39 |
  | fcrAuction1 | 27.21 | 5.87 | 4.92 |
  | fcrAuction2 | 23.52 | 6.37 | 8.18 |

- Before 2024-02-01 the published prices are averages, not marginal prices (Svk). They
  are not used in the backtest.
- Successor dataset: a search of the data.svk.se catalogue (CKAN API,
  `package_search?q=fcr`) on 2026-10-30 returned four FCR datasets, all marked
  "Discontinued" (capacity market, accepted aggregated offers, aggregated volumes,
  activated energy). No 15-minute successor is published there yet. Data after
  2026-04-14 would have to come from the TSO's market platform; the 2025 backtest does
  not need it.

## Grid frequency (Fingrid)

- Monthly 7z archives at `https://data.fingrid.fi/files/339/<YYYY>/<YYYY>-<MM>.7z`
  (March 2025: 67 MB compressed, 865 MB extracted, 31 daily CSVs
  `Taajuusdata2025-03-DD.csv` with columns `Time,Value`). The format is 7z, not zip, so
  `fetch_data.py` extracts it with the system `tar` (bsdtar/libarchive, part of
  Windows 10+ and macOS; on Linux install `libarchive-tools`). This avoids another Python
  dependency.
- The download is automated: the archive URLs are listed on the dataset page and need
  no API key.
- Timestamps are naive Finnish local time. The DST-start day 2025-03-30 confirms it: it
  has no 03:xx hour (825 822 rows instead of about 828 000). The loader localises to
  Europe/Helsinki (`ambiguous="infer"` for the repeated autumn hour) and converts to
  UTC. The March archive spans 2025-02-28 22:00 to 2025-03-31 21:00 UTC.
- Quality (March 2025): 26 738 231 rows, values 49.796-50.195 Hz, no NaN, 4 duplicate
  timestamps (dropped, first kept). There are 209 steps longer than 100 ms and 9773
  missing samples in total (coverage 0.99963). Longest gaps: 7 min 03 s after
  2025-03-14 18:16:09 UTC, 86 s and 74 s on 2025-03-30 around 10:50 UTC, 58 s on
  2025-03-18 17:22 UTC.
- 1 Hz version: mean of the 10 samples in each second (label = start of the second).
  Seconds with no sample stay NaN (807 in March). For simulation, `fill_short_gaps`
  interpolates linearly up to `simulation.max_frequency_gap_s` (600 s) and fails on
  longer gaps.
- Simulation week 2025-03-03 to 2025-03-10: 19 empty seconds, longest run 7 s; mean
  49.99981 Hz, standard deviation 32 mHz, 0.86 % of the time outside 49.9-50.1 Hz.

## Committed samples (`data/sample/`, 3.7 MB)

Written by `fetch_data.py --samples` and used by the tests and CI.

| File | Content |
| --- | --- |
| `day_ahead_se3_week.parquet` | DA prices 2025-03-03 to 2025-03-10 (hourly) |
| `day_ahead_se3_15min_day.parquet` | DA prices 2025-10-15 (96 quarter hours) |
| `fcr_prices_se3_week.parquet` | All FCR price series, same week |
| `frequency_1hz_week.parquet` | 1 Hz frequency, same week (float32, NaN kept) |
| `frequency_10hz_hour.parquet` | 10 Hz frequency, 2025-03-03 00:00-01:00 UTC |
