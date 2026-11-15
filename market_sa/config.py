"""Paths, scoring constants, and documented FX rates."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

DATA_DIR = Path(os.environ.get("MARKET_SA_DATA_DIR", PROJECT_ROOT / "data")).expanduser()
CACHE_DIR = Path(os.environ.get("MARKET_SA_CACHE_DIR", DATA_DIR / "cache")).expanduser()
LEDGER_PATH = Path(os.environ.get("MARKET_SA_LEDGER", DATA_DIR / "quotes.sqlite")).expanduser()
MOLBLOOM_CACHE = CACHE_DIR / "molbloom"
HTTP_CACHE_PATH = CACHE_DIR / "http_cache.sqlite"

USER_AGENT = (
    "MarketSA/0.1 (local research tool; synthesizability evidence; "
    "does not place orders or submit quote forms)"
)

# PubChem requests no more than ~5 req/s. Stay well under that.
PUBCHEM_MIN_INTERVAL_SEC = float(os.environ.get("MARKET_SA_PUBCHEM_INTERVAL", "0.3"))
HTTP_TIMEOUT_SEC = float(os.environ.get("MARKET_SA_HTTP_TIMEOUT", "25"))

# Default bloom catalogs always queried. zinc20 is huge (~2 GB) and only
# used if already cached or MARKET_SA_BLOOM_EXTRA is set.
DEFAULT_BLOOM_CATALOGS = ("zinc-instock", "zinc-instock-mini")
OPTIONAL_BLOOM_CATALOGS = ("surechembl", "zinc20")

# surechembl is a patent database, not a storefront.
BLOOM_CATALOG_KIND = {
    "zinc-instock": "purchasability",
    "zinc-instock-mini": "purchasability",
    "zinc20": "purchasability",
    "surechembl": "patent_literature",
}

# Approximate USD per 1 unit of currency, frozen for reproducible scoring.
# These are NOT live market rates and must be labeled whenever used.
FX_TABLE_DATE = "2026-11-15"
FX_USD_PER_UNIT: dict[str, float] = {
    "USD": 1.0,
    "CNY": 0.1404,  # ≈ 7.12 CNY / USD
    "RMB": 0.1404,
    "EUR": 1.085,
    "GBP": 1.310,
    "JPY": 0.00645,  # ≈ 155 JPY / USD
    "CHF": 1.125,
    "KRW": 0.00069,
    "INR": 0.0113,
    "CAD": 0.715,
    "AUD": 0.650,
    "HKD": 0.1285,
}
FX_NOTE_ZH = f"汇率为 {FX_TABLE_DATE} 冻结的近似值，仅用于把价格归一到美元后打分，不是实时牌价。"
FX_NOTE_EN = (
    f"Approximate FX rates frozen on {FX_TABLE_DATE} for reproducible "
    "USD-normalized scoring; not live market rates."
)

SCORE_DIRECTION_ZH = "1 = 更易合成，10 = 更难合成（与 RDKit SA Score 方向一致）"
SCORE_DIRECTION_EN = "1 = easier to synthesize, 10 = harder (same direction as RDKit SA Score)"

DEFAULT_RFQ_AMOUNTS = ((100, "mg"), (1, "g"))

DECISIONS = ("accepted", "declined", "no_response", "conditional")
REASON_CODES = ("chemically_infeasible", "out_of_scope", "capacity", "other")
AMOUNT_UNITS = ("g", "mg", "kg", "ug", "mmol")

# Declined / weak human-quote point scores (1=easy, 10=hard).
DECLINED_SCORES = {
    "chemically_infeasible": 9.8,
    "out_of_scope": 8.7,
    "capacity": 8.8,
    "other": 9.2,
    None: 9.2,
}
NO_RESPONSE_SCORE = 6.5
CONDITIONAL_PENALTY = 0.8
ACCEPTED_NO_PRICE_BASE = 3.5

# Catalog-listed (no price) band.
CATALOG_LISTED_SCORE_MAX = 3.5  # few vendors
CATALOG_LISTED_SCORE_MIN = 2.5  # many vendors
BLOOM_ONLY_INSTOCK_SCORE = 3.2
BLOOM_ONLY_MINI_SCORE = 3.4
INSTOCK_PRICE_BONUS = -0.5  # slightly easier if marked in-stock with a price


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MOLBLOOM_CACHE.mkdir(parents=True, exist_ok=True)
