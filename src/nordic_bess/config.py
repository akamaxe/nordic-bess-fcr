"""Typed configuration loaded from ``configs/*.yaml``.

Every model parameter (battery size, efficiencies, costs, FCR reservation factors,
backtest window, time steps) lives in the YAML file and reaches the code through the
frozen dataclasses below. :func:`load_config` validates the values and fails loudly on
unknown or missing keys.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

PRODUCTS: tuple[str, ...] = ("FCR_N", "FCR_D_UP", "FCR_D_DOWN")


class ConfigError(ValueError):
    """Raised when a configuration file is malformed or violates a validation rule."""


def _utc_timestamp(value: Any, name: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ConfigError(f"{name} must carry a timezone (use a trailing 'Z' for UTC)")
    return ts.tz_convert("UTC")


@dataclass(frozen=True)
class SolverConfig:
    """MILP solver settings (Pyomo solver name, relative MIP gap, time limit)."""

    name: str
    mip_rel_gap: float
    time_limit_s: float

    def __post_init__(self) -> None:
        if not 0 <= self.mip_rel_gap < 1:
            raise ConfigError("market.solver.mip_rel_gap must be in [0, 1)")
        if self.time_limit_s <= 0:
            raise ConfigError("market.solver.time_limit_s must be positive")


@dataclass(frozen=True)
class MarketConfig:
    """Market layer settings (PLAN M2)."""

    bidding_zone: str
    backtest_start: pd.Timestamp
    backtest_end: pd.Timestamp  # exclusive
    resolution_minutes: int
    products: tuple[str, ...]
    fcr_price_series: str
    lookback_days: int
    solver: SolverConfig

    def __post_init__(self) -> None:
        if self.fcr_price_series not in ("total", "fcrAuction1", "fcrAuction2"):
            raise ConfigError("market.fcr_price_series must be total, fcrAuction1 or fcrAuction2")
        if self.lookback_days < 0:
            raise ConfigError("market.lookback_days must be >= 0")
        if self.backtest_end <= self.backtest_start:
            raise ConfigError("market.backtest_end must be after backtest_start")
        if self.resolution_minutes not in (15, 60):
            raise ConfigError("market.resolution_minutes must be 15 or 60")
        unknown = set(self.products) - set(PRODUCTS)
        if unknown:
            raise ConfigError(f"market.products has unknown products: {sorted(unknown)}")


@dataclass(frozen=True)
class BessConfig:
    """Battery parameters. SOC values are fractions of ``e_nom_mwh``."""

    p_max_mw: float
    e_nom_mwh: float
    soc_min: float
    soc_max: float
    soc_target: float
    eta_charge: float
    eta_discharge: float
    degradation_cost_eur_per_mwh: float
    converter_time_constant_s: float

    def __post_init__(self) -> None:
        for name in ("p_max_mw", "e_nom_mwh"):
            if not getattr(self, name) > 0:
                raise ConfigError(f"bess.{name} must be positive")
        for name in ("eta_charge", "eta_discharge"):
            if not 0 < getattr(self, name) <= 1:
                raise ConfigError(f"bess.{name} must be in (0, 1]")
        if not 0 <= self.soc_min < self.soc_max <= 1:
            raise ConfigError("bess SOC window must satisfy 0 <= soc_min < soc_max <= 1")
        if not self.soc_min <= self.soc_target <= self.soc_max:
            raise ConfigError("bess.soc_target must lie inside [soc_min, soc_max]")
        if self.degradation_cost_eur_per_mwh < 0:
            raise ConfigError("bess.degradation_cost_eur_per_mwh must be >= 0")
        if self.converter_time_constant_s < 0:
            raise ConfigError("bess.converter_time_constant_s must be >= 0")

    @property
    def e_min_mwh(self) -> float:
        """Lower end of the usable energy window [MWh]."""
        return self.soc_min * self.e_nom_mwh

    @property
    def e_max_mwh(self) -> float:
        """Upper end of the usable energy window [MWh]."""
        return self.soc_max * self.e_nom_mwh

    @property
    def e_usable_mwh(self) -> float:
        """Usable energy window [MWh]; the energy range used for FCR (E in Table 11)."""
        return self.e_max_mwh - self.e_min_mwh

    @property
    def e_target_mwh(self) -> float:
        """Daily start and end energy content [MWh]."""
        return self.soc_target * self.e_nom_mwh


@dataclass(frozen=True)
class ThresholdMinutes:
    """Table 11 SOC thresholds expressed as minutes of full activation (FCR v1.1, 3.5.1)."""

    aem_enable: float
    aem_disable: float
    nem_enable: float
    nem_disable: float

    def __post_init__(self) -> None:
        if not 0 < self.aem_enable <= self.aem_disable <= self.nem_enable <= self.nem_disable:
            raise ConfigError(
                "Table 11 minutes must satisfy 0 < aem_enable <= aem_disable <= nem_enable"
                " <= nem_disable"
            )


@dataclass(frozen=True)
class FcrRequirementsConfig:
    """LER reservation and energy-management parameters (FCR v1.1, Tables 10-11, 3.5)."""

    version: str
    power_factor_n: float
    power_factor_d_opposite: float
    energy_hours_n: float
    energy_hours_d: float
    nem_rate_n: float
    nem_rate_d: float
    nem_window_s: int
    aem_window_s: int
    max_per_product_mw: float
    thresholds_fcr_n: ThresholdMinutes
    thresholds_fcr_d: ThresholdMinutes

    def __post_init__(self) -> None:
        if not 0 < self.nem_rate_n <= 0.50:
            raise ConfigError("fcr_requirements.nem_rate_n must be in (0, 0.50] (eq. 16)")
        if not 0 < self.nem_rate_d <= 0.34:
            raise ConfigError("fcr_requirements.nem_rate_d must be in (0, 0.34] (eq. 17)")
        # Table 10 power factors are full activation plus the NEM rate: a raised NEM rate
        # must be matched by the power the market layer reserves.
        if self.power_factor_n < 1.0 + self.nem_rate_n - 1e-9:
            raise ConfigError("power_factor_n must be >= 1 + nem_rate_n (Table 10, eq. 16)")
        if self.power_factor_d_opposite < self.nem_rate_d - 1e-9:
            raise ConfigError("power_factor_d_opposite must be >= nem_rate_d (Table 10, eq. 17)")
        for name in ("energy_hours_n", "energy_hours_d", "max_per_product_mw"):
            if not getattr(self, name) > 0:
                raise ConfigError(f"fcr_requirements.{name} must be positive")
        if self.nem_window_s <= 0 or self.aem_window_s <= 0:
            raise ConfigError("NEM/AEM windows must be positive")


@dataclass(frozen=True)
class SimulationConfig:
    """Time steps and windows for the asset simulation (PLAN M3)."""

    long_horizon_step_s: float
    test_signal_step_s: float
    week_start: pd.Timestamp
    max_frequency_gap_s: float

    def __post_init__(self) -> None:
        if not (self.long_horizon_step_s > 0 and self.test_signal_step_s > 0):
            raise ConfigError("simulation steps must be positive")
        if self.max_frequency_gap_s < 0:
            raise ConfigError("simulation.max_frequency_gap_s must be >= 0")

    @property
    def week_end(self) -> pd.Timestamp:
        """Exclusive end of the one-week long-horizon simulation window."""
        return self.week_start + pd.Timedelta(days=7)


@dataclass(frozen=True)
class ComplianceConfig:
    """Prequalification test settings for the BESS model (PLAN M4)."""

    c_fcr_n_mw: float
    c_fcr_dup_mw: float
    c_fcr_ddown_mw: float
    steady_state_window_s: float
    ler_start_margin_min: float

    def __post_init__(self) -> None:
        for name in ("c_fcr_n_mw", "c_fcr_dup_mw", "c_fcr_ddown_mw", "steady_state_window_s"):
            if not getattr(self, name) > 0:
                raise ConfigError(f"compliance.{name} must be positive")
        if self.ler_start_margin_min < 0:
            raise ConfigError("compliance.ler_start_margin_min must be >= 0")


@dataclass(frozen=True)
class PathsConfig:
    """Absolute project paths, resolved against the repository root."""

    raw: Path
    processed: Path
    sample: Path
    results: Path
    figures: Path


@dataclass(frozen=True)
class Config:
    """Complete project configuration."""

    market: MarketConfig
    bess: BessConfig
    fcr: FcrRequirementsConfig
    simulation: SimulationConfig
    compliance: ComplianceConfig
    paths: PathsConfig
    source: Path


def _require_keys(
    section: dict[str, Any], cls: type, name: str, extra: tuple[str, ...] = ()
) -> None:
    expected = {f.name for f in fields(cls)} - set(extra)
    given = set(section)
    if missing := expected - given:
        raise ConfigError(f"{name}: missing keys {sorted(missing)}")
    if unknown := given - expected:
        raise ConfigError(f"{name}: unknown keys {sorted(unknown)}")


def config_from_dict(raw: dict[str, Any], root: Path, source: Path | None = None) -> Config:
    """Build and validate a :class:`Config` from a parsed YAML mapping.

    Args:
        raw: Mapping with the sections ``market``, ``bess``, ``fcr_requirements``,
            ``simulation`` and ``paths``.
        root: Repository root used to resolve the relative paths.
        source: File the mapping was read from (kept for traceability).
    """
    sections = {"market", "bess", "fcr_requirements", "simulation", "compliance", "paths"}
    if missing := sections - set(raw):
        raise ConfigError(f"missing sections {sorted(missing)}")
    if unknown := set(raw) - sections:
        raise ConfigError(f"unknown sections {sorted(unknown)}")

    m = dict(raw["market"])
    _require_keys(m, MarketConfig, "market")
    _require_keys(m["solver"], SolverConfig, "market.solver")
    market = MarketConfig(
        bidding_zone=str(m["bidding_zone"]),
        backtest_start=_utc_timestamp(m["backtest_start"], "market.backtest_start"),
        backtest_end=_utc_timestamp(m["backtest_end"], "market.backtest_end"),
        resolution_minutes=int(m["resolution_minutes"]),
        products=tuple(m["products"]),
        fcr_price_series=str(m["fcr_price_series"]),
        lookback_days=int(m["lookback_days"]),
        solver=SolverConfig(
            name=str(m["solver"]["name"]),
            mip_rel_gap=float(m["solver"]["mip_rel_gap"]),
            time_limit_s=float(m["solver"]["time_limit_s"]),
        ),
    )

    b = dict(raw["bess"])
    _require_keys(b, BessConfig, "bess")
    bess = BessConfig(**{k: float(v) for k, v in b.items()})

    f = dict(raw["fcr_requirements"])
    thresholds = f.pop("thresholds_min", None)
    if not isinstance(thresholds, dict) or set(thresholds) != {"fcr_n", "fcr_d"}:
        raise ConfigError("fcr_requirements.thresholds_min needs exactly fcr_n and fcr_d")
    _require_keys(
        f, FcrRequirementsConfig, "fcr_requirements", extra=("thresholds_fcr_n", "thresholds_fcr_d")
    )
    th = {}
    for key in ("fcr_n", "fcr_d"):
        _require_keys(thresholds[key], ThresholdMinutes, f"thresholds_min.{key}")
        th[key] = ThresholdMinutes(**{k: float(v) for k, v in thresholds[key].items()})
    fcr = FcrRequirementsConfig(
        version=str(f["version"]),
        power_factor_n=float(f["power_factor_n"]),
        power_factor_d_opposite=float(f["power_factor_d_opposite"]),
        energy_hours_n=float(f["energy_hours_n"]),
        energy_hours_d=float(f["energy_hours_d"]),
        nem_rate_n=float(f["nem_rate_n"]),
        nem_rate_d=float(f["nem_rate_d"]),
        nem_window_s=int(f["nem_window_s"]),
        aem_window_s=int(f["aem_window_s"]),
        max_per_product_mw=float(f["max_per_product_mw"]),
        thresholds_fcr_n=th["fcr_n"],
        thresholds_fcr_d=th["fcr_d"],
    )

    s = dict(raw["simulation"])
    _require_keys(s, SimulationConfig, "simulation")
    simulation = SimulationConfig(
        long_horizon_step_s=float(s["long_horizon_step_s"]),
        test_signal_step_s=float(s["test_signal_step_s"]),
        week_start=_utc_timestamp(s["week_start"], "simulation.week_start"),
        max_frequency_gap_s=float(s["max_frequency_gap_s"]),
    )

    cp = dict(raw["compliance"])
    _require_keys(cp, ComplianceConfig, "compliance")
    compliance = ComplianceConfig(**{k: float(v) for k, v in cp.items()})

    p = dict(raw["paths"])
    _require_keys(p, PathsConfig, "paths")
    paths = PathsConfig(**{k: (root / v).resolve() for k, v in p.items()})

    return Config(
        market=market,
        bess=bess,
        fcr=fcr,
        simulation=simulation,
        compliance=compliance,
        paths=paths,
        source=(source or root).resolve(),
    )


def load_config(path: str | Path, root: str | Path | None = None) -> Config:
    """Load and validate a YAML configuration file.

    Args:
        path: Path to the YAML file, e.g. ``configs/base.yaml``.
        root: Repository root for resolving relative paths. Defaults to the parent of the
            directory that holds the file (``configs/..``).

    Raises:
        ConfigError: If a section or key is missing or unknown, or a value is invalid.
    """
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} does not contain a mapping")
    root_path = Path(root) if root is not None else path.resolve().parent.parent
    return config_from_dict(raw, root=root_path, source=path)
