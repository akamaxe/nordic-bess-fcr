"""PLAN M2b tests: naive forecast and sequential bidding."""

import numpy as np
import pandas as pd
import pytest

from nordic_bess.data.svk_fcr import PRICE_COLUMNS
from nordic_bess.market.inputs import prepare_prices
from nordic_bess.market.kpis import summarise
from nordic_bess.market.milp import MilpParams
from nordic_bess.market.sequential import naive_forecast, run_sequential
from nordic_bess.market.strategies import STRATEGIES, run_backtest

START = pd.Timestamp("2025-03-03T00:00Z")


def _prices(days: int, weekly_periodic: bool, seed: int = 0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(START - pd.Timedelta(days=7), periods=24 * (days + 7), freq="1h")
    hour = idx.hour.to_numpy()
    week = 24 * 7
    noise = rng.normal(0, 12, week if weekly_periodic else len(idx))
    noise = np.resize(noise, len(idx))
    da = pd.Series(60 + 30 * np.sin(2 * np.pi * (hour - 7) / 24) + noise, index=idx)
    fcr_noise = np.resize(rng.uniform(0.5, 1.5, week if weekly_periodic else len(idx)), len(idx))
    fcr = pd.DataFrame(
        {
            PRICE_COLUMNS["FCR_N"]: 15 * fcr_noise,
            PRICE_COLUMNS["FCR_D_UP"]: 4 * fcr_noise[::-1],
            PRICE_COLUMNS["FCR_D_DOWN"]: 3 * fcr_noise,
        },
        index=idx,
    )
    end = START + pd.Timedelta(days=days)
    extended = prepare_prices(da, fcr, START - pd.Timedelta(days=7), end, 1, "total")
    actual = prepare_prices(da, fcr, START, end, 1, "total")
    return actual, extended, end


def test_naive_forecast_is_last_week_shifted():
    actual, extended, end = _prices(3, weekly_periodic=False)
    fc = naive_forecast(extended, START, end)
    assert fc.da.index[0] == START
    assert fc.da.iloc[0] == extended.da.iloc[0]  # value of START - 7 days
    assert len(fc.fcr) == 72
    with pytest.raises(ValueError):
        naive_forecast(actual, START, end)


def test_perfect_weekly_pattern_gives_zero_value_of_information(config):
    params = MilpParams.from_config(config)
    actual, extended, end = _prices(2, weekly_periodic=True)
    fc = naive_forecast(extended, START, end)
    pf = summarise(run_backtest(actual, params, STRATEGIES["S3"], config.market.solver), params)
    for variant in ("fcr_forecast", "all_forecast"):
        seq = run_sequential(actual, fc, params, config.market.solver, variant)
        assert summarise(seq, params)["net_eur"] == pytest.approx(pf["net_eur"], rel=1e-6)


def test_forecast_errors_cost_money_and_fcr_forecast_dominates(config):
    params = MilpParams.from_config(config)
    actual, extended, end = _prices(3, weekly_periodic=False, seed=5)
    fc = naive_forecast(extended, START, end)
    solver = config.market.solver
    pf = summarise(run_backtest(actual, params, STRATEGIES["S3"], solver), params)["net_eur"]
    a = run_sequential(actual, fc, params, solver, "fcr_forecast")
    b = run_sequential(actual, fc, params, solver, "all_forecast")
    net_a, net_b = summarise(a, params)["net_eur"], summarise(b, params)["net_eur"]
    assert net_a <= pf + 1e-6
    assert net_b <= net_a + 1e-6  # same capacities, day-ahead re-optimised on actual prices
    assert a.max_violation <= 1e-6 and b.max_violation <= 1e-6
    # Settled at actual prices: the schedule carries the actual day-ahead prices.
    np.testing.assert_allclose(b.schedule["price_da_eur_per_mwh"], actual.da.to_numpy())


def test_single_actual_scenario_matches_deterministic_s3(config):
    from nordic_bess.market.milp import DailyMilp
    from nordic_bess.market.stochastic import StochasticDailyMilp

    params = MilpParams.from_config(config)
    actual, _, _ = _prices(1, weekly_periodic=False, seed=9)
    day = actual.day(START)
    det = DailyMilp(params, STRATEGIES["S3"], config.market.solver).solve(day)
    caps, objective, _ = StochasticDailyMilp(params, config.market.solver, 1).solve([day])
    assert objective == pytest.approx(det.objective_eur, rel=1e-6)
    fixed = DailyMilp(params, STRATEGIES["S3"], config.market.solver).solve(day, caps)
    assert fixed.objective_eur == pytest.approx(det.objective_eur, rel=1e-6)


def test_stochastic_with_weekly_pattern_equals_perfect_foresight(config):
    from nordic_bess.market.stochastic import run_stochastic

    params = MilpParams.from_config(config)
    actual, extended, _ = _prices(2, weekly_periodic=True)
    pf = summarise(run_backtest(actual, params, STRATEGIES["S3"], config.market.solver), params)
    sto = run_stochastic(actual, extended, params, config.market.solver, n_weeks=1)
    assert summarise(sto, params)["net_eur"] == pytest.approx(pf["net_eur"], rel=1e-6)
    with pytest.raises(ValueError):
        run_stochastic(actual, extended, params, config.market.solver, n_weeks=2)
