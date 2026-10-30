"""Shared fixtures. Tests use only committed files (configs/, data/sample/): no network."""

from pathlib import Path

import pytest

from nordic_bess.config import Config, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def config() -> Config:
    return load_config(REPO_ROOT / "configs" / "base.yaml")
