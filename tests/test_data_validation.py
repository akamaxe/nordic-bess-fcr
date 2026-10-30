import pandas as pd
import pytest

from nordic_bess.data.validation import DataValidationError, validate_time_index


def _grid(start="2025-03-01T00:00Z", periods=10, freq="1h"):
    return pd.date_range(start, periods=periods, freq=freq)


def test_clean_grid_has_full_coverage():
    report = validate_time_index(_grid(), "1h", "x")
    assert report.n_points == 10
    assert report.n_missing == 0
    assert report.coverage == 1.0
    assert report.longest_gap == pd.Timedelta(0)


def test_gaps_are_counted_and_reported():
    idx = _grid().delete([3, 4, 7])
    report = validate_time_index(idx, "1h", "x")
    assert report.n_missing == 3
    assert len(report.gaps) == 2
    assert report.gaps[0].n_missing == 2  # largest gap first
    assert report.longest_gap == pd.Timedelta("2h")
    assert "3 missing samples" in report.summary()


@pytest.mark.parametrize(
    "idx",
    [
        pd.date_range("2025-03-01", periods=5, freq="1h"),  # naive
        pd.date_range("2025-03-01", periods=5, freq="1h", tz="Europe/Stockholm"),  # not UTC
        _grid(periods=5)[[0, 2, 1, 3, 4]],  # not monotonic
        _grid(periods=5).append(_grid(periods=1)),  # duplicate
        pd.DatetimeIndex(["2025-03-01T00:00Z", "2025-03-01T01:30Z"]),  # off grid
        pd.DatetimeIndex(["2025-03-01T00:10Z", "2025-03-01T01:10Z"]),  # not aligned
        pd.DatetimeIndex([], tz="UTC"),
    ],
)
def test_invalid_indexes_raise(idx):
    with pytest.raises(DataValidationError):
        validate_time_index(idx, "1h", "x")
