from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def tmp_ledger(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("MARKET_SA_DATA_DIR", str(data))
    monkeypatch.setenv("MARKET_SA_CACHE_DIR", str(data / "cache"))
    monkeypatch.setenv("MARKET_SA_LEDGER", str(data / "quotes.sqlite"))
    # Reload path-dependent config / ledger bindings
    import market_sa.config as config
    import market_sa.ledger as ledger

    config.DATA_DIR = data
    config.CACHE_DIR = data / "cache"
    config.LEDGER_PATH = data / "quotes.sqlite"
    config.HTTP_CACHE_PATH = data / "cache" / "http_cache.sqlite"
    return config.LEDGER_PATH
