"""PLAN M4 acceptance tests: test signals and evaluators on synthetic units."""

import dataclasses

import numpy as np
import pytest

from nordic_bess.compliance import freqdomain as fd
from nordic_bess.compliance.evaluate import (
    evaluate_fcr_d_ramp,
    evaluate_frequency_domain,
    evaluate_r1_fcr_n,
    evaluate_sine_tests,
)
from nordic_bess.compliance.ler import evaluate_r12_ler, run_ler_test
from nordic_bess.compliance.signals import (
    TABLE4_PRINTED_RAMP_END_S,
    TABLE12_FCR_N,
    fcr_d_ramp_sequence,
    fcr_n_step_sequence,
    sine_periods,
    sine_test,
)
from nordic_bess.compliance.synthetic import synthetic_response
from nordic_bess.plant.battery import BatteryParams
from nordic_bess.sim.engine import FcrUnitSimulator, Schedule
from nordic_bess.spec import Product

C = 10.0
WINDOW = 60.0


def _by_id(results):
    return {r.requirement: r for r in results}


# --- signals -----------------------------------------------------------------------------


def test_fcr_n_step_sequence_follows_table3():
    sig = fcr_n_step_sequence(0.1)
    assert sig.t_s[-1] == pytest.approx(21 * 60 - 0.1)
    assert sig.segment("step1").t_start_s == 360.0
    assert sig.segment("step2").t_start_s == 660.0
    assert sig.f_hz[int(400 / 0.1)] == 49.9
    assert sig.f_hz[int(45 / 0.1)] == 49.95
    assert fcr_n_step_sequence(0.1, endurance=True).segment("step2").t_start_s == 21 * 60


def test_fcr_d_ramps_follow_table4_and_document_pdf_mismatch():
    sig = fcr_d_ramp_sequence(Product.FCR_D_UP, 0.1, combination=True)
    starts = [s.t_start_s for s in sig.segments]
    assert starts == pytest.approx([0, 30, 34.9, 90, 390, 690, 750, 1050, 1350])
    computed = {int(s.name[4:]): s.ramp_end_s for s in sig.segments[1:]}
    for ramp, printed in TABLE4_PRINTED_RAMP_END_S.items():
        agrees = abs(computed[ramp] - printed) < 0.06
        assert agrees == (ramp not in (1, 7, 8)), (ramp, computed[ramp], printed)
    assert sig.f_hz[int(700 / 0.1)] == pytest.approx(49.0)
    down = fcr_d_ramp_sequence(Product.FCR_D_DOWN, 0.1)
    assert down.f_hz.max() == pytest.approx(51.0)
    assert len(down.segments) == 7


def test_sine_test_signal():
    sig = sine_test(Product.FCR_D_UP, 25.0, 10, 0.1)
    assert sig.f_hz.mean() == pytest.approx(49.7, abs=1e-6)
    assert sig.f_hz.max() == pytest.approx(49.8, abs=1e-4)
    assert len(sine_periods(Product.FCR_N)) == 10
    assert len(sine_periods(Product.FCR_D_UP)) == 7


# --- time-domain requirements on synthetic units -----------------------------------------


@pytest.mark.parametrize("product", [Product.FCR_D_UP, Product.FCR_D_DOWN])
def test_ideal_unit_passes_requirements_1_to_4(product):
    sig = fcr_d_ramp_sequence(product, 0.1)
    res = _by_id(evaluate_fcr_d_ramp(sig, synthetic_response(sig, C), C, WINDOW))
    for req in ("R1", "R2", "R2 hold", "R3", "R4"):
        assert res[req].passed, res[req].explanation
    sig_n = fcr_n_step_sequence(0.1)
    for r in evaluate_r1_fcr_n(sig_n, synthetic_response(sig_n, C), C, WINDOW):
        assert r.passed and abs(r.measured) < 1e-9


def test_pure_delays_fail_energy_and_power_after_7_5_s():
    sig = fcr_d_ramp_sequence(Product.FCR_D_UP, 0.1)
    # 5 s delay: full activation is reached 1.67 s after the ramp starts, so the delayed
    # response is already 100 % at 7.5 s (R2 passes) but the energy falls short (R3).
    r5 = _by_id(evaluate_fcr_d_ramp(sig, synthetic_response(sig, C, delay_s=5.0), C, WINDOW))
    assert r5["R2"].passed
    assert not r5["R3"].passed
    # 7 s delay: only 0.5 s of response before 7.5 s, below 86 % of dP_th (R2 fails too).
    r7 = _by_id(evaluate_fcr_d_ramp(sig, synthetic_response(sig, C, delay_s=7.0), C, WINDOW))
    assert not r7["R2"].passed
    assert not r7["R3"].passed


def test_under_delivery_reports_k_red():
    sig = fcr_n_step_sequence(0.1)
    res = _by_id(evaluate_r1_fcr_n(sig, synthetic_response(sig, C, gain=0.8), C, WINDOW))
    assert not res["R1 up"].passed
    assert res["R1 up"].measured == pytest.approx(-0.2)
    assert "K_red,ss = 0.842" in res["R1 up"].explanation
    assert "fails even with" in res["R1 up"].explanation  # 0.842 < 0.9 for FCR-N
    sig_d = fcr_d_ramp_sequence(Product.FCR_D_UP, 0.1)
    r = _by_id(evaluate_fcr_d_ramp(sig_d, synthetic_response(sig_d, C, gain=0.8), C, WINDOW))
    assert "prequalifies with" in r["R1"].explanation  # 0.842 >= 0.75 for FCR-D


def test_over_delivery_fails_without_k_red():
    sig = fcr_n_step_sequence(0.1)
    res = _by_id(evaluate_r1_fcr_n(sig, synthetic_response(sig, C, gain=1.3), C, WINDOW))
    assert not res["R1 up"].passed
    assert "K_red" not in res["R1 up"].explanation


def test_slow_deactivation_fails_requirement_4():
    # Fast activation, slow release (time constant 30 s when the response decreases).
    sig = fcr_d_ramp_sequence(Product.FCR_D_UP, 0.1)
    ideal = synthetic_response(sig, C)
    p, y, alpha = np.empty_like(ideal), 0.0, 1 - np.exp(-0.1 / 30.0)
    for i, u in enumerate(ideal):
        y = u if u >= y else y + alpha * (u - y)
        p[i] = y
    res = _by_id(evaluate_fcr_d_ramp(sig, p, C, WINDOW))
    assert res["R2"].passed and res["R3"].passed
    assert not res["R4"].passed


# --- frequency domain ----------------------------------------------------------------------


def test_sine_fit_recovers_gain_and_phase():
    t = np.arange(0, 250, 0.1)
    y = (
        3.7 * np.sin(2 * np.pi * t / 25 + 0.6)
        + 1.2
        + np.random.default_rng(0).normal(0, 0.05, t.size)
    )
    fit = fd.fit_sine(t, y, 25.0)
    assert fit.amplitude == pytest.approx(3.7, rel=0.01)
    assert fit.phase_rad == pytest.approx(0.6, rel=0.01)
    assert fit.offset == pytest.approx(1.2, abs=0.01)


def test_transfer_point_of_known_lag():
    period, tau = 40.0, 5.0
    w = 2 * np.pi / period
    t = np.arange(0, 5 * period, 0.1)
    err = 0.1 * np.sin(w * t)
    expected = 1 / (1 + 1j * w * tau)
    p = C / 0.1 * np.abs(expected) * 0.1 * np.sin(w * t + np.angle(expected))
    tp = fd.transfer_point(t, err, p, period, 0.1, C)
    assert tp.gain == pytest.approx(abs(expected), rel=0.01)
    assert np.radians(tp.phase_deg) == pytest.approx(np.angle(expected), rel=0.01)
    assert tp.linearity_ratio < 1e-6


def _sine_points(product, **unit):
    periods = sine_periods(product)
    runs = []
    for period, _stat, total in periods:
        sig = sine_test(product, period, total, 0.1)
        runs.append((sig, synthetic_response(sig, C, **unit)))
    return evaluate_sine_tests(product, runs, C, {p: s for p, s, _ in periods})


@pytest.mark.parametrize("product", [Product.FCR_N, Product.FCR_D_UP])
def test_fast_unit_passes_frequency_domain(product):
    res = _by_id(evaluate_frequency_domain(product, _sine_points(product, tau_s=0.2)))
    for req in ("R8", "R9", "R10"):
        assert res[req].passed, res[req].explanation


def test_heavily_lagged_unit_fails_stability():
    res = _by_id(
        evaluate_frequency_domain(
            Product.FCR_N, _sine_points(Product.FCR_N, delay_s=4.0, tau_s=8.0)
        )
    )
    assert not res["R8"].passed


def test_weak_unit_fails_performance_and_reports_k_red_dyn():
    # 30 % of the theoretical response: the closed loop is too soft at long periods (the
    # longest tested period, 300 s, is binding: |1/D| = 1.78 there).
    res = _by_id(evaluate_frequency_domain(Product.FCR_N, _sine_points(Product.FCR_N, gain=0.3)))
    assert res["R8"].passed
    assert not res["R9"].passed
    k = float(res["R9"].explanation.split("K_red,dyn = ")[1].split()[0])
    assert 0.55 < k < 0.75  # about 0.65 analytically at T = 300 s, below the 0.9 minimum


def test_nonlinear_unit_fails_linearity():
    # A coarse deadband-quantised response is far from a sine.
    sig = sine_test(Product.FCR_N, 60.0, 7, 0.1)
    p = np.sign(synthetic_response(sig, C)) * C
    tp = evaluate_sine_tests(Product.FCR_N, [(sig, p)], C, {60.0: 5})[0]
    assert tp.linearity_ratio > 0.4


def test_power_system_model_low_frequency_gain():
    g = fd.power_system(np.array([1e-6]), fd.table7(Product.FCR_N, "stability"))
    assert abs(g[0]) == pytest.approx(600 / 0.1 * 50 / 23000 / 0.5, rel=1e-6)


# --- LER (Table 12) regression on the PDF example unit -----------------------------------


def test_table12_sequence_on_pdf_example_unit(config):
    # PDF Figure 20: 1.34 MW / 2 MWh battery, C_N = 1 MW, 2 MWh for FCR-N, SOC0 62.5 %.
    battery = dataclasses.replace(
        BatteryParams.from_config(config), p_max_mw=1.34, e_min_mwh=0.0, e_max_mwh=2.0
    )
    sim = FcrUnitSimulator(battery, config.fcr, Schedule.constant(c_n_mw=1.0), 1.25, 1.0)
    run = run_ler_test(sim, Product.FCR_N, TABLE12_FCR_N)
    res = evaluate_r12_ler(run)
    assert res.passed, res.explanation
    assert all(run.conditions_met)
