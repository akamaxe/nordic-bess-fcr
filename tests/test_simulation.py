"""PLAN M3 acceptance tests for the plant and the simulator."""

import numpy as np
import pandas as pd
import pytest

from nordic_bess.control.droop import total_activation
from nordic_bess.data import catalog
from nordic_bess.data.fingrid import fill_short_gaps
from nordic_bess.plant.battery import BatteryParams, energy_step, lag_coefficient, plant_step
from nordic_bess.sim.engine import FcrUnitSimulator, Schedule, SimOptions, simulate, to_frame
from nordic_bess.sim.kpis import energy_balance_error, simulation_kpis


@pytest.fixture(scope="module")
def battery(config):
    return BatteryParams.from_config(config)


def _energy_change(df, b):
    p = df["p_out_mw"].to_numpy()
    dt = df["t_s"].diff().iloc[1]
    return (np.where(p < 0, -p * b.eta_c, 0) - np.where(p > 0, p / b.eta_d, 0)).sum() * dt / 3600


def test_zero_lag_response_equals_droop_exactly(config, battery):
    b = BatteryParams.from_config(config, tau_s=0.0)
    rng = np.random.default_rng(3)
    f = 50 + np.cumsum(rng.normal(0, 0.004, 3000)).clip(-0.6, 0.6)
    sched = Schedule.constant(c_n_mw=3.0, c_dup_mw=2.0, c_ddown_mw=1.5, baseline_mw=0.5)
    opts = SimOptions(nem=False, aem=False)
    df = simulate(f, 0.1, sched, b, config.fcr, config.bess.e_target_mwh, opts)
    expected = 0.5 + total_activation(f, 3.0, 2.0, 1.5)
    np.testing.assert_allclose(df["p_out_mw"], expected, rtol=0, atol=1e-12)


def test_first_order_lag_step_response(config, battery):
    df = simulate(np.full(50, 49.9), 0.1, Schedule.constant(c_n_mw=5.0), battery, config.fcr, 10.0)
    tau = battery.tau_s
    t_end = df["t_s"].to_numpy() + 0.1
    np.testing.assert_allclose(df["p_out_mw"], 5.0 * (1 - np.exp(-t_end / tau)), atol=1e-9)


def test_energy_balance_closes_on_a_real_week(config, battery):
    f = pd.read_parquet(catalog.sample_path(config, "frequency_1hz_week"))["f_hz"].astype(float)
    f, _ = fill_short_gaps(f, config.simulation.max_frequency_gap_s)
    day = f.iloc[: 86400 // 2]  # half a day keeps the test fast
    e0 = config.bess.e_target_mwh
    df = simulate(day.to_numpy(), 1.0, Schedule.constant(c_n_mw=5.0), battery, config.fcr, e0)
    assert abs(df["e_mwh"].iloc[-1] - e0 - _energy_change(df, battery)) < 1e-6
    assert energy_balance_error(df, battery, e0) < 1e-6


def test_nem_acts_only_in_band_and_past_thresholds(config, battery):
    # Start below the FCR-N NEM enable threshold: e_min + C * 30/60.
    c = 5.0
    e_enable = battery.e_min_mwh + c * 0.5
    sim = FcrUnitSimulator(battery, config.fcr, Schedule.constant(c_n_mw=c), e_enable - 0.01, 1.0)
    out = to_frame(sim.run(np.full(600, 50.0)))
    # NEM_current ramps from 0 to -1 over 300 s (eq. 15) and charges at 0.34 C.
    assert out["nem_current_n"].iloc[0] == 0.0
    assert out["nem_current_n"].iloc[301] == pytest.approx(-1.0)
    assert out["p_out_mw"].iloc[400] == pytest.approx(-0.34 * c, rel=1e-6)
    # Outside the normal band NEM_allowed drops to 0 and the mean ramps back to 0.
    out2 = to_frame(sim.run(np.full(400, 49.85)))
    assert out2["nem_current_n"].iloc[-1] == pytest.approx(0.0)
    # Above the enable threshold NEM never starts.
    sim3 = FcrUnitSimulator(battery, config.fcr, Schedule.constant(c_n_mw=c), e_enable + 0.5, 1.0)
    out3 = to_frame(sim3.run(np.full(600, 50.0)))
    assert (out3["nem_current_n"] == 0).all()


def test_aem_drives_fcr_d_output_smoothly_to_zero(config, battery):
    c = 9.0
    e_aem = battery.e_min_mwh + c * 5 / 60  # FCR-D up AEM enable threshold
    sim = FcrUnitSimulator(battery, config.fcr, Schedule.constant(c_dup_mw=c), e_aem - 0.02, 1.0)
    out = to_frame(sim.run(np.full(400, 49.5)))
    assert out["aem_dup"].iloc[1]
    p = out["p_fcr_dup_mw"].to_numpy()
    assert p[0] == pytest.approx(c)  # full activation at first
    assert p[150] == pytest.approx(c / 2, rel=0.02)  # f_ref moves linearly over 300 s
    assert abs(p[305]) < 1e-9  # exhausted in a controlled way, no sudden drop
    assert np.all(np.diff(p[:305]) <= 1e-9)


def test_energy_limits_clip_power(config, battery):
    p, e, limited = plant_step(0.0, battery.e_min_mwh + 1e-4, 5.0, 1.0, battery, 1.0)
    assert limited
    assert e == pytest.approx(battery.e_min_mwh)
    assert p == pytest.approx(1e-4 * battery.eta_d * 3600)
    assert lag_coefficient(1.0, 0.0) == 1.0
    assert energy_step(10.0, -3600.0, 1.0, 0.9, 0.9) == pytest.approx(10.9)


def test_schedule_from_backtest_hourly_blocks(config, battery):
    idx = pd.date_range("2025-03-03T00:00Z", periods=3, freq="1h", name="time_utc")
    bt = pd.DataFrame(
        {"p_c_mw": [0, 2, 0], "p_d_mw": [1, 0, 0], "c_n_mw": [1, 1, 2]}, index=idx, dtype=float
    ).assign(c_dup_mw=0.0, c_ddown_mw=0.0)
    sched = Schedule.from_backtest(bt, idx[0], idx[0] + pd.Timedelta(hours=3))
    df = simulate(np.full(3 * 3600, 50.0), 1.0, sched, battery, config.fcr, 10.0)
    np.testing.assert_allclose(df["p_base_mw"].iloc[[0, 3600, 7200]], [1.0, -2.0, 0.0])
    assert simulation_kpis(df, battery, 10.0)["throughput_discharge_mwh"] > 0
