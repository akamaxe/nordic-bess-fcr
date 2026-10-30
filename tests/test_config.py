import copy

import pytest
import yaml

from nordic_bess.config import ConfigError, config_from_dict, load_config


@pytest.fixture()
def raw(repo_root):
    with (repo_root / "configs" / "base.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_base_config_loads_with_derived_energies(config):
    assert config.bess.e_usable_mwh == pytest.approx(18.0)
    assert config.bess.e_min_mwh == pytest.approx(1.0)
    assert config.bess.e_target_mwh == pytest.approx(10.0)
    assert config.market.backtest_start.tz is not None
    assert str(config.market.backtest_start.tz) == "UTC"
    assert config.fcr.thresholds_fcr_d.nem_enable == config.fcr.thresholds_fcr_d.nem_disable


def test_paths_resolve_against_repo_root(config, repo_root):
    assert config.paths.sample == (repo_root / "data" / "sample").resolve()


def test_load_config_accepts_explicit_root(repo_root, tmp_path):
    cfg = load_config(repo_root / "configs" / "base.yaml", root=tmp_path)
    assert cfg.paths.results == (tmp_path / "results").resolve()


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("bess", "p_max_mw", 0.0),
        ("bess", "e_nom_mwh", -1.0),
        ("bess", "eta_charge", 1.2),
        ("bess", "eta_discharge", 0.0),
        ("bess", "soc_min", 0.96),
        ("bess", "soc_max", 1.1),
        ("bess", "soc_target", 0.99),
        ("fcr_requirements", "nem_rate_n", 0.6),
        ("fcr_requirements", "power_factor_n", 1.2),
        ("fcr_requirements", "power_factor_d_opposite", 0.1),
        ("market", "resolution_minutes", 30),
        ("market", "backtest_end", "2024-01-01T00:00:00Z"),
        ("market", "backtest_start", "2025-01-01T00:00:00"),
    ],
)
def test_invalid_values_raise(raw, repo_root, section, key, value):
    bad = copy.deepcopy(raw)
    bad[section][key] = value
    with pytest.raises(ConfigError):
        config_from_dict(bad, root=repo_root)


def test_raised_nem_rate_requires_matching_headroom(raw, repo_root):
    bad = copy.deepcopy(raw)
    bad["fcr_requirements"]["nem_rate_n"] = 0.50
    with pytest.raises(ConfigError, match="power_factor_n"):
        config_from_dict(bad, root=repo_root)
    bad["fcr_requirements"]["power_factor_n"] = 1.50
    assert config_from_dict(bad, root=repo_root).fcr.power_factor_n == 1.50


def test_unknown_and_missing_keys_raise(raw, repo_root):
    extra = copy.deepcopy(raw)
    extra["bess"]["colour"] = "blue"
    with pytest.raises(ConfigError, match="unknown"):
        config_from_dict(extra, root=repo_root)
    missing = copy.deepcopy(raw)
    del missing["bess"]["p_max_mw"]
    with pytest.raises(ConfigError, match="missing"):
        config_from_dict(missing, root=repo_root)


def test_table11_minutes_must_be_ordered(raw, repo_root):
    bad = copy.deepcopy(raw)
    bad["fcr_requirements"]["thresholds_min"]["fcr_n"]["nem_enable"] = 3.0
    with pytest.raises(ConfigError, match="Table 11"):
        config_from_dict(bad, root=repo_root)
