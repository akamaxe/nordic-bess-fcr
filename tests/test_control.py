"""Control-law tests: droop (Table 1, eq. 12/23), NEM/AEM building blocks, endurance."""

import dataclasses

import numpy as np
import pytest

from nordic_bess.config import ThresholdMinutes
from nordic_bess.control.droop import activation, activation_scalar, saturated_frequency
from nordic_bess.control.endurance import endurance_minutes
from nordic_bess.control.energy_mgmt import (
    aem_update,
    f_aem,
    limit_output,
    nem_update,
    stacked_thresholds,
    table11_thresholds,
)
from nordic_bess.spec import Product

N, DUP, DDOWN = Product.FCR_N, Product.FCR_D_UP, Product.FCR_D_DOWN


@pytest.mark.parametrize(
    ("product", "f", "expected_share"),
    [
        (N, 50.0, 0.0),
        (N, 49.9, 1.0),
        (N, 50.1, -1.0),
        (N, 49.8, 1.0),  # saturated outside the band (eq. 20)
        (N, 49.95, 0.5),
        (DUP, 49.9, 0.0),
        (DUP, 50.2, 0.0),
        (DUP, 49.7, 0.5),
        (DUP, 49.5, 1.0),
        (DUP, 49.0, 1.0),  # saturates at the sold volume (3.6.2)
        (DDOWN, 50.1, 0.0),
        (DDOWN, 50.5, -1.0),
        (DDOWN, 51.0, -1.0),
        (DDOWN, 49.8, 0.0),
    ],
)
def test_table1_activation_points(product, f, expected_share):
    assert activation(product, f, 10.0) == pytest.approx(10.0 * expected_share)


def test_fcr_d_without_saturation_keeps_increasing():
    assert activation(DUP, 49.0, 10.0, saturate_fcr_d=False) == pytest.approx(22.5)


def test_scalar_and_vector_activation_agree():
    rng = np.random.default_rng(0)
    f = rng.uniform(48.8, 51.2, 500)
    f_ref = rng.uniform(49.4, 50.6, 500)
    for prod in (N, DUP, DDOWN):
        vec = activation(prod, f, 7.0, f_ref)
        sca = [activation_scalar(prod, fi, 7.0, ri) for fi, ri in zip(f, f_ref, strict=True)]
        np.testing.assert_allclose(vec, sca, rtol=0, atol=1e-12)


def test_saturations_eq20_22():
    f = np.array([49.0, 49.95, 50.5])
    np.testing.assert_allclose(saturated_frequency(N, f), [49.9, 49.95, 50.1])
    np.testing.assert_allclose(saturated_frequency(DUP, f), [49.0, 49.9, 49.9])
    np.testing.assert_allclose(saturated_frequency(DDOWN, f), [50.1, 50.1, 50.5])
    assert f_aem(DUP, 49.6, aem_active=False) == 49.9
    assert f_aem(DUP, 49.6, aem_active=True) == 49.6
    assert f_aem(DUP, 50.05, aem_active=True) == 49.9
    assert f_aem(N, 49.7, aem_active=True) == 49.9
    assert f_aem(DDOWN, 49.95, aem_active=True) == 50.1


def test_table11_matches_pdf_example():
    # PDF Figure 20: C_N = 1 MW, E = 2 MWh reserved for FCR-N.
    th = table11_thresholds(N, 1.0, 0.0, 2.0, ThresholdMinutes(5, 10, 30, 57.5))
    e = 2.0
    assert th.nem_enable_high / e == pytest.approx(1 - 0.5 / 2)  # SOC 0.75
    assert th.nem_disable_high / e == pytest.approx(1 - 57.5 / 60 / 2)
    assert th.aem_enable_high / e == pytest.approx(1 - 5 / 60 / 2)
    assert th.nem_enable_low / e == pytest.approx(0.5 / 2)
    assert th.aem_disable_low / e == pytest.approx(10 / 60 / 2)
    d_up = table11_thresholds(DUP, 3.0, 0.0, 1.0, ThresholdMinutes(5, 10, 20, 20))
    assert np.isnan(d_up.nem_enable_high)
    assert d_up.nem_enable_low == pytest.approx(1.0)


def test_stacking_keeps_fcr_n_above_the_fcr_d_reserve(config):
    th = stacked_thresholds(5.0, 3.0, 2.0, 1.0, 19.0, config.fcr)
    reserve_dup = config.fcr.energy_hours_d * 3.0
    assert th[N].aem_enable_low == pytest.approx(1.0 + reserve_dup + 5.0 * 5 / 60)
    assert th[DUP].aem_enable_low == pytest.approx(1.0 + 3.0 * 5 / 60)
    assert th[N].aem_enable_high == pytest.approx(19.0 - config.fcr.energy_hours_d * 2.0 - 5 / 12)


def test_nem_only_inside_normal_band_and_with_hysteresis():
    th = table11_thresholds(N, 1.0, 0.0, 2.0, ThresholdMinutes(5, 10, 30, 57.5))
    # Below the enable threshold (0.5 MWh) and in the band: charge (-1).
    assert nem_update(50.0, 0.49, False, False, th) == (-1, True, False)
    # Outside the band never: f = 49.9 and 50.1 are outside (strict inequality, eq. 14).
    assert nem_update(49.9, 0.49, False, False, th)[0] == 0
    assert nem_update(50.1, 0.49, True, False, th) == (0, False, False)
    # Between enable (0.5) and disable (0.958): stays on only if already on.
    assert nem_update(50.0, 0.7, False, False, th)[0] == 0
    assert nem_update(50.0, 0.7, True, False, th) == (-1, True, False)
    assert nem_update(50.0, 0.97, True, False, th) == (0, False, False)
    # High side discharges (+1).
    assert nem_update(50.05, 1.6, False, False, th) == (1, False, True)


def test_aem_hysteresis():
    th = table11_thresholds(DUP, 3.0, 0.0, 1.0, ThresholdMinutes(5, 10, 20, 20))
    assert aem_update(0.2, False, False, th) == (True, False)  # below 0.25 MWh
    assert aem_update(0.4, True, False, th) == (True, False)  # below disable 0.5
    assert aem_update(0.4, False, False, th) == (False, False)
    assert aem_update(0.6, True, False, th) == (False, False)


def test_output_limits_eq24_26():
    assert limit_output(N, 1.5, 1.0, 0.34) == pytest.approx(1.34)
    assert limit_output(N, -1.5, 1.0, 0.34) == pytest.approx(-1.34)
    assert limit_output(DUP, -0.5, 1.0, 0.2) == pytest.approx(-0.2)
    assert limit_output(DUP, 2.0, 1.0, 0.2) == pytest.approx(2.0)
    assert limit_output(DDOWN, 0.5, 1.0, 0.2) == pytest.approx(0.2)


def test_endurance_eq27_28():
    l_up, l_dn = endurance_minutes(10.0, 1.0, 19.0, 0.0, 9.0, 9.0)
    assert l_up == pytest.approx(60.0)
    assert l_dn == pytest.approx(60.0)
    l_up, l_dn = endurance_minutes(10.0, 1.0, 19.0, 3.0, 9.0, 9.0)  # discharging setpoint
    assert l_up == pytest.approx(9.0 / 12.0 * 60)
    assert l_dn == pytest.approx(9.0 / 6.0 * 60)
    l_up, _ = endurance_minutes(10.0, 1.0, 19.0, -9.0, 9.0, 9.0)
    assert np.isinf(l_up)


def test_threshold_minutes_dataclass_is_frozen():
    tm = ThresholdMinutes(5, 10, 20, 20)
    with pytest.raises(dataclasses.FrozenInstanceError):
        tm.aem_enable = 1.0
