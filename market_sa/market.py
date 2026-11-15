"""Public catalog / vendor lookups. Never submits quote forms or orders."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx

from market_sa.cache import cache_get, cache_set
from market_sa.config import (
    BLOOM_CATALOG_KIND,
    DEFAULT_BLOOM_CATALOGS,
    HTTP_TIMEOUT_SEC,
    MOLBLOOM_CACHE,
    OPTIONAL_BLOOM_CATALOGS,
    PUBCHEM_MIN_INTERVAL_SEC,
    USER_AGENT,
    ensure_dirs,
)

logger = logging.getLogger(__name__)

_PUBCHEM_LOCK = threading.Lock()
_LAST_PUBCHEM = 0.0

PUBCHEM_PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUBCHEM_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"


def _bloom_catalogs_to_query() -> list[str]:
    names = list(DEFAULT_BLOOM_CATALOGS)
    extra = os.environ.get("MARKET_SA_BLOOM_EXTRA", "").strip() in {"1", "true", "yes"}
    ensure_dirs()
    for name in OPTIONAL_BLOOM_CATALOGS:
        cached = MOLBLOOM_CACHE / f"{name}.bloom"
        if extra or cached.exists():
            if name not in names:
                names.append(name)
    return names


def configure_molbloom_cache() -> None:
    ensure_dirs()
    try:
        import molbloom

        molbloom._DEFAULT_PATH = str(MOLBLOOM_CACHE)
    except Exception:
        logger.exception("Could not patch molbloom cache path")


def query_molbloom(smiles: str) -> dict[str, Any]:
    """Return purchasability flags. True = may be purchasable (small FPR); False = not in catalog."""
    configure_molbloom_cache()
    import molbloom

    hits: dict[str, Any] = {}
    errors: dict[str, str] = {}
    descriptions = {}
    try:
        descriptions = dict(molbloom.catalogs() or {})
    except Exception as exc:
        logger.warning("molbloom.catalogs() failed: %s", exc)

    for name in _bloom_catalogs_to_query():
        try:
            flag = bool(molbloom.buy(smiles, catalog=name, canonicalize=True))
            hits[name] = flag
        except Exception as exc:
            errors[name] = str(exc)
            logger.warning("molbloom catalog %s failed: %s", name, exc)

    purch_true = [
        n for n, v in hits.items() if v and BLOOM_CATALOG_KIND.get(n) == "purchasability"
    ]
    return {
        "hits": hits,
        "errors": errors,
        "descriptions": {k: descriptions.get(k) for k in hits},
        "kinds": {k: BLOOM_CATALOG_KIND.get(k, "other") for k in hits},
        "any_purchasability_hit": bool(purch_true),
        "purchasability_hits": purch_true,
        "note_zh": (
            "True 表示可能可购（布隆过滤器有很小的假阳性率），False 表示不在该目录中。"
            "SureChEMBL 是专利文献库，不是商店。"
        ),
        "note_en": (
            "True means the molecule may be purchasable (small false-positive rate); "
            "False means it is not in that catalog. SureChEMBL is a patent database, not a storefront."
        ),
    }


def _pubchem_wait() -> None:
    global _LAST_PUBCHEM
    with _PUBCHEM_LOCK:
        now = time.monotonic()
        wait = PUBCHEM_MIN_INTERVAL_SEC - (now - _LAST_PUBCHEM)
        if wait > 0:
            time.sleep(wait)
        _LAST_PUBCHEM = time.monotonic()


def _http_client() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT_SEC,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


def _pubchem_request(method: str, url: str, **kwargs) -> dict:
    _pubchem_wait()
    with _http_client() as client:
        if method == "POST":
            resp = client.post(url, **kwargs)
        else:
            resp = client.get(url, **kwargs)
        if resp.status_code == 404:
            return {"_not_found": True, "_status": 404}
        resp.raise_for_status()
        return resp.json()


def resolve_pubchem_cid(smiles: str) -> dict[str, Any]:
    cached = cache_get("pubchem_cid", smiles)
    if cached is not None:
        return cached
    url = f"{PUBCHEM_PUG}/compound/smiles/cids/JSON"
    data = _pubchem_request("POST", url, data={"smiles": smiles})
    if data.get("_not_found"):
        result = {"cid": None, "cids": [], "not_found": True}
        cache_set("pubchem_cid", smiles, result)
        return result
    cids = data.get("IdentifierList", {}).get("CID") or []
    result = {"cid": int(cids[0]) if cids else None, "cids": [int(c) for c in cids], "not_found": not cids}
    cache_set("pubchem_cid", smiles, result)
    return result


def fetch_pubchem_properties(cid: int) -> dict[str, Any]:
    key = str(cid)
    cached = cache_get("pubchem_props", key)
    if cached is not None:
        return cached
    props = "Title,MolecularFormula,MolecularWeight,InChIKey,IUPACName"
    url = f"{PUBCHEM_PUG}/compound/cid/{cid}/property/{props}/JSON"
    data = _pubchem_request("GET", url)
    row = {}
    if not data.get("_not_found"):
        rows = (data.get("PropertyTable") or {}).get("Properties") or []
        if rows:
            row = rows[0]
    result = {
        "cid": cid,
        "title": row.get("Title"),
        "iupac_name": row.get("IUPACName"),
        "formula": row.get("MolecularFormula"),
        "mw": row.get("MolecularWeight"),
        "inchikey": row.get("InChIKey"),
    }
    cache_set("pubchem_props", key, result)
    return result


def _parse_vendors(payload: dict) -> list[dict[str, Any]]:
    categories = ((payload or {}).get("SourceCategories") or {}).get("Categories") or []
    vendors: list[dict[str, Any]] = []
    for cat in categories:
        if (cat.get("Category") or "") != "Chemical Vendors":
            continue
        for src in cat.get("Sources") or []:
            vendors.append(
                {
                    "name": src.get("SourceName"),
                    "registry_id": src.get("RegistryID"),
                    "sid": src.get("SID"),
                    "source_url": src.get("SourceURL"),
                    "record_url": src.get("SourceRecordURL"),
                    "source_detail": src.get("SourceDetail"),
                }
            )
    return vendors


def group_vendors(vendors: list[dict]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for v in vendors:
        name = v.get("name") or "(unknown)"
        rec = grouped.setdefault(
            name,
            {
                "name": name,
                "n_listings": 0,
                "registry_ids": [],
                "source_url": v.get("source_url"),
                "record_urls": [],
            },
        )
        rec["n_listings"] += 1
        rid = v.get("registry_id")
        if rid and rid not in rec["registry_ids"]:
            rec["registry_ids"].append(rid)
        url = v.get("record_url")
        if url and url not in rec["record_urls"] and len(rec["record_urls"]) < 5:
            rec["record_urls"].append(url)
        if not rec["source_url"] and v.get("source_url"):
            rec["source_url"] = v.get("source_url")
    out = sorted(grouped.values(), key=lambda r: (-r["n_listings"], r["name"].lower()))
    return out


def fetch_pubchem_vendors(cid: int) -> dict[str, Any]:
    key = str(cid)
    cached = cache_get("pubchem_vendors", key)
    if cached is not None:
        return cached
    url = f"{PUBCHEM_VIEW}/categories/compound/{cid}/JSON"
    data = _pubchem_request("GET", url)
    vendors: list[dict] = []
    if not data.get("_not_found"):
        vendors = _parse_vendors(data)
    grouped = group_vendors(vendors)
    result = {
        "cid": cid,
        "listings": vendors,
        "listing_count": len(vendors),
        "vendors": grouped,
        "vendor_count": len(grouped),
        "prices_available": False,
        "lead_times_available": False,
        "note_zh": "PubChem 供应商名录通常不提供价格或货期。本工具不会编造价格。",
        "note_en": "PubChem vendor listings usually do not include prices or lead times. This tool does not invent prices.",
    }
    cache_set("pubchem_vendors", key, result)
    return result


def query_pubchem(smiles: str, inchikey: str | None = None) -> dict[str, Any]:
    """Resolve SMILES → CID, properties, and chemical vendors. Cached. No prices invented."""
    warnings: list[str] = []
    try:
        cid_info = resolve_pubchem_cid(smiles)
    except Exception as exc:
        logger.warning("PubChem CID lookup failed: %s", exc)
        return {
            "ok": False,
            "error": f"PubChem unreachable or failed: {exc}",
            "cid": None,
            "vendors": [],
            "vendor_count": 0,
            "listing_count": 0,
            "prices_available": False,
            "lead_times_available": False,
            "warnings": [f"PubChem 不可用，已跳过在线供应商查询：{exc}"],
        }

    cid = cid_info.get("cid")
    if not cid:
        return {
            "ok": True,
            "cid": None,
            "not_found": True,
            "title": None,
            "vendors": [],
            "vendor_count": 0,
            "listing_count": 0,
            "prices_available": False,
            "lead_times_available": False,
            "warnings": ["PubChem 未找到该 SMILES 对应的 CID。"],
        }

    props: dict[str, Any] = {}
    vendors: dict[str, Any] = {}
    try:
        props = fetch_pubchem_properties(int(cid))
    except Exception as exc:
        warnings.append(f"PubChem 属性查询失败：{exc}")
        logger.warning("PubChem properties failed: %s", exc)
    try:
        vendors = fetch_pubchem_vendors(int(cid))
    except Exception as exc:
        warnings.append(f"PubChem 供应商查询失败：{exc}")
        logger.warning("PubChem vendors failed: %s", exc)

    if inchikey and props.get("inchikey") and props["inchikey"] != inchikey:
        warnings.append(
            f"PubChem InChIKey（{props['inchikey']}）与本地计算（{inchikey}）不一致，已照实记录。"
        )

    return {
        "ok": True,
        "cid": int(cid),
        "cids": cid_info.get("cids") or [int(cid)],
        "title": props.get("title"),
        "iupac_name": props.get("iupac_name"),
        "formula": props.get("formula"),
        "mw": props.get("mw"),
        "inchikey": props.get("inchikey"),
        "vendors": vendors.get("vendors") or [],
        "vendor_count": vendors.get("vendor_count") or 0,
        "listings": vendors.get("listings") or [],
        "listing_count": vendors.get("listing_count") or 0,
        "prices_available": False,
        "lead_times_available": False,
        "note_zh": vendors.get("note_zh"),
        "note_en": vendors.get("note_en"),
        "compound_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{int(cid)}",
        "warnings": warnings,
    }
