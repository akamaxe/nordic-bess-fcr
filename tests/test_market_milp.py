"""Tests of the daily MILP on synthetic prices (no data files)."""

import numpy as np
import pandas as pd
import pytest

from nordic_bess.market.inputs import prepare_prices
from nordic_bess.market.kpis import revenue_streams, summarise
from nordic_bess.market.milp import DailyMilp, DayPrices, MilpParams, constraint_violations
from nordic_bess.market.strategies import STRATEGIES, run_backtest

TOL = 1e-6


@pytest.fixture(scope="module")
def params(config):
    return MilpParams.from_config(config)


@pytest.fixture(scope="module")
def solver(config):
    return config.market.solver


def _prices(da, n=0.0, dup=0.0, ddown=0.0, pph=1):
    da = np.broadcast_to(np.asarray(da, dtype=float), (24 * pph,)).copy()
    return DayPrices(
        da_eur_per_mwh=da,
        fcr_n_eur_per_mw_h=np.full(24, n, dtype=float),
        fcr_dup_eur_per_mw_h=np.full(24, dup, dtype=float),
        fcr_ddown_eur_per_mw_h=np.full(24, ddown, dtype=float),
    )


def _volatile_da(seed=1, pph=1):
    rng = np.random.default_rng(seed)
    t = np.arange(24 * pph) / pph
    return 60 + 40 * np.sin(2 * np.pi * (t - 6) / 24) + rng.normal(0, 15, t.size)


def test_zero_fcr_prices_make_s3_equal_to_s0(params, solver):
    prices = _prices(_volatile_da())
    s0 = DailyMilp(params, STRATEGIES["S0"], solver).solve(prices)
    s3 = DailyMilp(params, STRATEGIES["S3"], solver).solve(prices)
    assert s3.objective_eur == pytest.approx(s0.objective_eur, rel=1e-6, abs=1e-6)
    assert s0.objective_eur > 0


def test_flat_da_and_fcr_n_price_sell_power_bound(params, solver):
    sol = DailyMilp(params, STRATEGIES["S1"], solver).solve(_prices(50.0, n=20.0))
    expected = params.p_max_mw / params.power_factor_n  # 7.46 MW, power-bound
    energy_bound = params.eta_d * (params.e0_mwh - params.e_min_mwh) / params.energy_hours_n
    assert expected == pytest.approx(7.4627, abs=1e-4)
    assert energy_bound == pytest.approx(8.54, abs=0.01)
    np.testing.assert_allclose(sol.periods["c_n_mw"], expected, atol=1e-6)


def test_fcr_d_only_sells_symmetric_power_bound(params, solver):
    sol = DailyMilp(params, STRATEGIES["S2"], solver).solve(_prices(50.0, dup=5.0, ddown=5.0))
    expected = params.p_max_mw / (1 + params.power_factor_d_opposite)  # 8.33 MW each
    np.testing.assert_allclose(sol.periods["c_dup_mw"], expected, atol=1e-6)
    np.testing.assert_allclose(sol.periods["c_ddown_mw"], expected, atol=1e-6)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_constraints_hold_on_the_solution(params, solver, seed):
    prices = _prices(_volatile_da(seed), n=15.0, dup=8.0, ddown=4.0)
    sol = DailyMilp(params, STRATEGIES["S3"], solver).solve(prices)
    viol = constraint_violations(sol.periods, params, sol.dt_h)
    assert max(viol.values()) <= TOL, viol


def test_energy_balance_closes_and_no_simultaneous_flows(params, solver):
    # Negative prices tempt the model to charge and discharge at once to burn energy.
    da = np.r_[np.full(12, -40.0), np.full(12, 120.0)]
    sol = DailyMilp(params, STRATEGIES["S0"], solver).solve(_prices(da))
    p = sol.periods
    assert (np.minimum(p["p_c_mw"], p["p_d_mw"]) <= TOL).all()
    net_in = (params.eta_c * p["p_c_mw"] - p["p_d_mw"] / params.eta_d).sum() * sol.dt_h
    assert net_in == pytest.approx(0.0, abs=1e-6)
    assert p["e_start_mwh"].iloc[0] == pytest.approx(params.e0_mwh)
    assert p["e_end_mwh"].iloc[-1] == pytest.approx(params.e0_mwh)


def test_objective_matches_revenue_streams(params, solver):
    prices = _prices(_volatile_da(4), n=15.0, dup=8.0, ddown=4.0)
    sol = DailyMilp(params, STRATEGIES["S3"], solver).solve(prices)
    rev = revenue_streams(sol.periods, sol.dt_h, params.c_deg_eur_per_mwh)
    assert rev["net_eur"].sum() == pytest.approx(sol.objective_eur, rel=1e-9)


def test_fifteen_minute_periods_with_hourly_fcr_blocks(params, solver):
    prices = _prices(_volatile_da(5, pph=4), n=15.0, dup=8.0, ddown=4.0, pph=4)
    sol = DailyMilp(params, STRATEGIES["S3"], solver, periods_per_hour=4).solve(prices)
    assert len(sol.periods) == 96
    blocks = sol.periods["c_n_mw"].to_numpy().reshape(24, 4)
    assert np.allclose(blocks, blocks[:, :1])
    assert max(constraint_violations(sol.periods, params, sol.dt_h).values()) <= TOL


def test_fixed_capacity_is_respected(params, solver):
    fixed = np.zeros((24, 3))
    fixed[:, 0] = 3.0
    milp = DailyMilp(params, STRATEGIES["S3"], solver)
    sol = milp.solve(_prices(_volatile_da(6), n=50.0), fixed_capacity=fixed)
    np.testing.assert_allclose(sol.periods["c_n_mw"], 3.0)
    np.testing.assert_allclose(sol.periods["c_dup_mw"], 0.0)
    free = milp.solve(_prices(_volatile_da(6), n=50.0))  # unfixed again
    assert free.periods["c_n_mw"].min() > 3.0


def test_backtest_on_sample_week(config, params, solver):
    from nordic_bess.data import catalog
    from nordic_bess.data.svk_fcr import select_series

    da = pd.read_parquet(catalog.sample_path(config, "day_ahead_week"))["price_eur_per_mwh"]
    fcr = select_series(pd.read_parquet(catalog.sample_path(config, "fcr_prices_week")), "total")
    start = config.simulation.week_start
    prices = prepare_prices(da, fcr, start, start + pd.Timedelta(days=7), 1, "total")
    rows = {}
    for name in ("S0", "S3"):
        result = run_backtest(prices, params, STRATEGIES[name], solver)
        assert len(result.schedule) == 168
        assert result.max_violation <= TOL
        rows[name] = summarise(result, params)
    assert rows["S3"]["net_eur"] >= rows["S0"]["net_eur"] - 1e-6
    assert rows["S3"]["hours"] == 168
