"""Optional commercial catalog APIs. Skipped unless keys are set. Never prints secrets.

These adapters only perform search / availability lookups. They must not submit
quote-request or order forms. If an endpoint shape changes, the failure is
reported and ignored — prices are never invented.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from market_sa.cache import cache_get, cache_set
from market_sa.config import HTTP_TIMEOUT_SEC, USER_AGENT

logger = logging.getLogger(__name__)

# Environment variable names only — never log values.
KEY_ENV = {
    "molport": "MOLPORT_API_KEY",
    "mcule": "MCULE_API_TOKEN",
    "chemspace": "CHEMSPACE_API_KEY",
}


def _key(name: str) -> str | None:
    env = KEY_ENV[name]
    val = os.environ.get(env, "").strip()
    return val or None


def configured_sources() -> list[str]:
    return [name for name in KEY_ENV if _key(name)]


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT_SEC,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


def _redact(text: str, secret: str | None) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")


def _molport(smiles: str, inchikey: str) -> dict[str, Any]:
    """Best-effort Molport chemical search. Requires MOLPORT_API_KEY."""
    api_key = _key("molport")
    assert api_key
    cache_key = inchikey
    cached = cache_get("molport", cache_key)
    if cached is not None:
        return cached
    url = "https://api.molport.com/api/chemical-search/search"
    payload = {
        "API Key": api_key,
        "Structure": smiles,
        "Search Type": 5,  # exact structure (Molport documented enum)
        "Maximum Result Count": 20,
    }
    try:
        with _client() as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"source": "molport", "ok": False, "error": _redact(str(exc), api_key), "offers": []}

    offers: list[dict[str, Any]] = []
    # Walk a few historically observed shapes without inventing prices.
    blocks = []
    if isinstance(data, dict):
        blocks = (
            data.get("Molecules")
            or data.get("molecules")
            or (data.get("Data") or {}).get("Molecules")
            or []
        )
        if isinstance(blocks, dict):
            blocks = [blocks]
    for mol in blocks or []:
        catalogs = mol.get("Catalogues") or mol.get("catalogues") or mol.get("Offers") or []
        supplier = mol.get("SupplierName") or mol.get("Supplier") or "Molport"
        for item in catalogs or [mol]:
            price = (
                item.get("Price")
                or item.get("PriceUSD")
                or item.get("Price_USD")
                or item.get("price")
            )
            currency = item.get("Currency") or item.get("currency") or ("USD" if price is not None else None)
            amount = item.get("Amount") or item.get("amount") or item.get("PackSize")
            unit = item.get("Unit") or item.get("unit") or item.get("Measure") or "g"
            lead = item.get("LeadTime") or item.get("lead_days") or item.get("DeliveryDays")
            instock = item.get("InStock") or item.get("in_stock")
            if price is None and amount is None and lead is None:
                continue
            offers.append(
                {
                    "source": "molport",
                    "supplier": item.get("SupplierName") or supplier,
                    "price": price,
                    "currency": currency,
                    "amount": amount,
                    "unit": unit,
                    "lead_days": lead,
                    "instock": instock,
                }
            )
    result = {"source": "molport", "ok": True, "offers": offers, "raw_keys": sorted(list(data.keys())) if isinstance(data, dict) else []}
    cache_set("molport", cache_key, result)
    return result


def _mcule(smiles: str, inchikey: str) -> dict[str, Any]:
    token = _key("mcule")
    assert token
    cached = cache_get("mcule", inchikey)
    if cached is not None:
        return cached
    url = "https://mcule.com/api/v1/search/lookup/"
    try:
        with _client() as client:
            resp = client.get(
                url,
                params={"query": smiles},
                headers={"Authorization": f"Token {token}", "User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"source": "mcule", "ok": False, "error": _redact(str(exc), token), "offers": []}
    offers: list[dict[str, Any]] = []
    rows = data if isinstance(data, list) else (data.get("results") or data.get("products") or [])
    for item in rows or []:
        price = item.get("price") or item.get("price_usd")
        if price is None and not item.get("pack_size"):
            continue
        offers.append(
            {
                "source": "mcule",
                "supplier": item.get("supplier") or item.get("seller") or "Mcule",
                "price": price,
                "currency": item.get("currency") or "USD",
                "amount": item.get("amount") or item.get("pack_size"),
                "unit": item.get("unit") or "g",
                "lead_days": item.get("delivery_days") or item.get("lead_days"),
                "instock": item.get("in_stock"),
            }
        )
    result = {"source": "mcule", "ok": True, "offers": offers}
    cache_set("mcule", inchikey, result)
    return result


def _chemspace(smiles: str, inchikey: str) -> dict[str, Any]:
    key = _key("chemspace")
    assert key
    cached = cache_get("chemspace", inchikey)
    if cached is not None:
        return cached
    # Official search APIs vary by account; try a conservative exact-search style endpoint.
    url = "https://api.chem-space.com/v2/search/exact"
    try:
        with _client() as client:
            resp = client.post(
                url,
                json={"SMILES": smiles},
                headers={"apikey": key, "Authorization": key, "User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"source": "chemspace", "ok": False, "error": _redact(str(exc), key), "offers": []}
    offers: list[dict[str, Any]] = []
    rows = data if isinstance(data, list) else (data.get("items") or data.get("data") or data.get("compounds") or [])
    for item in rows or []:
        price = item.get("price") or item.get("priceUsd")
        if price is None:
            continue
        offers.append(
            {
                "source": "chemspace",
                "supplier": item.get("vendor") or item.get("supplier") or "Chemspace",
                "price": price,
                "currency": item.get("currency") or "USD",
                "amount": item.get("amount") or item.get("pack"),
                "unit": item.get("unit") or "g",
                "lead_days": item.get("leadTime") or item.get("lead_days"),
                "instock": item.get("inStock") or item.get("instock"),
            }
        )
    result = {"source": "chemspace", "ok": True, "offers": offers}
    cache_set("chemspace", inchikey, result)
    return result


def query_commercial(smiles: str, inchikey: str) -> dict[str, Any]:
    sources = configured_sources()
    results: list[dict] = []
    offers: list[dict] = []
    errors: list[str] = []
    for name in sources:
        try:
            if name == "molport":
                block = _molport(smiles, inchikey)
            elif name == "mcule":
                block = _mcule(smiles, inchikey)
            elif name == "chemspace":
                block = _chemspace(smiles, inchikey)
            else:
                continue
            results.append({k: v for k, v in block.items() if k != "raw"})
            if block.get("ok"):
                offers.extend(block.get("offers") or [])
            elif block.get("error"):
                errors.append(f"{name}: {block['error']}")
        except Exception as exc:
            logger.warning("optional catalog %s failed: %s", name, exc)
            errors.append(f"{name}: {exc}")
    return {
        "configured": sources,
        "results": results,
        "offers": offers,
        "errors": errors,
        "note_zh": (
            "仅在设置了 MOLPORT_API_KEY / MCULE_API_TOKEN / CHEMSPACE_API_KEY 时查询。"
            "未设置则静默跳过。不会提交询价或订单，也不会在日志中打印密钥。"
        ),
        "note_en": (
            "Queried only when MOLPORT_API_KEY / MCULE_API_TOKEN / CHEMSPACE_API_KEY are set. "
            "Otherwise skipped silently. No quote forms or orders are submitted; secrets are never printed."
        ),
    }
