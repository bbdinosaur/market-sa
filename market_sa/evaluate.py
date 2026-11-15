"""Orchestrate molecule parsing, market lookup, ledger, and Market SA scoring."""

from __future__ import annotations

import logging
from typing import Any

from market_sa import ledger
from market_sa.commercial import query_commercial
from market_sa.market import query_molbloom, query_pubchem
from market_sa.molecule import InvalidSmiles, MoleculeRecord, parse_molecule
from market_sa.rfq import draft_rfq
from market_sa.score import compute_market_sa

logger = logging.getLogger(__name__)


def evaluate_smiles(
    smiles: str,
    *,
    include_svg: bool = True,
    include_listings: bool = False,
    query_remote: bool = True,
) -> dict[str, Any]:
    mol = parse_molecule(smiles, with_svg=include_svg)
    warnings: list[str] = []

    bloom: dict[str, Any]
    try:
        bloom = query_molbloom(mol.canonical_smiles)
        if bloom.get("errors"):
            for name, err in bloom["errors"].items():
                warnings.append(f"molbloom 目录 {name} 失败：{err}")
    except Exception as exc:
        logger.warning("molbloom failed: %s", exc)
        bloom = {
            "hits": {},
            "errors": {"_all": str(exc)},
            "any_purchasability_hit": False,
            "purchasability_hits": [],
            "note_zh": "molbloom 查询失败。",
            "note_en": "molbloom query failed.",
        }
        warnings.append(f"molbloom 不可用：{exc}")

    pubchem: dict[str, Any]
    if query_remote:
        pubchem = query_pubchem(mol.canonical_smiles, inchikey=mol.inchikey)
        warnings.extend(pubchem.get("warnings") or [])
    else:
        pubchem = {
            "ok": False,
            "error": "remote lookups disabled",
            "cid": None,
            "vendors": [],
            "vendor_count": 0,
            "listing_count": 0,
            "prices_available": False,
            "lead_times_available": False,
            "warnings": ["已关闭在线查询。"],
        }
        warnings.append("已关闭在线查询（PubChem）。")

    commercial = query_commercial(mol.canonical_smiles, mol.inchikey)
    if commercial.get("errors"):
        warnings.extend([f"可选商业目录：{e}" for e in commercial["errors"]])

    quotes = ledger.list_quotes(inchikey=mol.inchikey)
    n_vendors = int(pubchem.get("vendor_count") or 0)
    scored = compute_market_sa(
        rdkit_sa=mol.rdkit_sa,
        quotes=quotes,
        mw=mol.mw,
        n_unique_vendors=n_vendors,
        bloom=bloom,
        catalog_prices=commercial.get("offers") or [],
    )

    if scored.evidence_class == "computational":
        warnings.append(
            "Market SA 目前只回退到了 RDKit SA（计算启发式），没有市场证据。请勿把它当作真实报价。"
        )
    elif scored.evidence_class == "catalog_listed":
        warnings.append(
            "目录/供应商名录命中不是报价：PubChem 通常不提供价格或货期，本工具也不会编造。"
        )

    pubchem_out = dict(pubchem)
    if not include_listings:
        pubchem_out.pop("listings", None)
        # keep grouped vendors (unique names); trim very long registry lists for default JSON
        trimmed = []
        for v in pubchem_out.get("vendors") or []:
            item = dict(v)
            ids = item.get("registry_ids") or []
            if len(ids) > 8:
                item["registry_ids"] = ids[:8]
                item["registry_ids_omitted"] = len(ids) - 8
            trimmed.append(item)
        pubchem_out["vendors"] = trimmed

    result = {
        "molecule": mol.to_dict(include_svg=include_svg),
        "rdkit_sa": {
            "score": round(mol.rdkit_sa, 4),
            "kind": "computational_heuristic",
            "label_zh": "RDKit SA Score（计算启发式，不是市场报价）",
            "label_en": "RDKit SA Score (computational heuristic, not a market quote)",
            "direction_zh": "1 = 更易合成，10 = 更难合成",
            "direction_en": "1 = easier to synthesize, 10 = harder",
        },
        "market_sa": scored.to_dict(),
        "bloom": bloom,
        "pubchem": pubchem_out,
        "commercial": {
            "configured": commercial.get("configured") or [],
            "offers": commercial.get("offers") or [],
            "errors": commercial.get("errors") or [],
            "note_zh": commercial.get("note_zh"),
            "note_en": commercial.get("note_en"),
        },
        "human_quotes": {
            "n": len(quotes),
            "quotes": quotes,
        },
        "warnings": warnings,
        "honesty": {
            "is_real_market_quote": scored.is_real_market_quote,
            "is_custom_synthesis_quote": scored.is_custom_synthesis_quote,
            "disclaimer_zh": _disclaimer_zh(scored.evidence_class),
            "disclaimer_en": _disclaimer_en(scored.evidence_class),
        },
    }
    return result


def _disclaimer_zh(evidence_class: str) -> str:
    mapping = {
        "human_quote": "该分数主要来自你登记的外包/供应商回复（是否接单、报价与周期）。请自行核对其真实性与时效。",
        "catalog_priced": "该分数来自可选商业目录的标价/货期，不是你向 CRO 询价后得到的定制合成报价。",
        "catalog_listed": "该分数仅基于公开目录或供应商名录命中，没有价格或货期，不是真实报价。",
        "computational": "该分数回退为 RDKit SA Score，只是计算启发式，不是真实市场可合成性，更不是报价。",
    }
    return mapping.get(evidence_class, "")


def _disclaimer_en(evidence_class: str) -> str:
    mapping = {
        "human_quote": "This score is driven by human ledger replies you recorded (accept/decline, price, lead time). Verify authenticity and freshness yourself.",
        "catalog_priced": "This score uses optional commercial catalog list prices and/or lead times, not a custom CRO synthesis quote.",
        "catalog_listed": "This score is based on a catalog or vendor-list hit without prices or lead times. It is not a real quote.",
        "computational": "This score falls back to RDKit SA Score, a computational heuristic — not real-world market synthesizability, and not a quote.",
    }
    return mapping.get(evidence_class, "")


def rfq_for_smiles(smiles: str) -> dict[str, Any]:
    mol = parse_molecule(smiles, with_svg=False)
    drafts = draft_rfq(mol)
    return {
        "molecule": mol.to_dict(include_svg=False),
        "drafts": drafts,
        "never_sent": True,
        "note_zh": "这只是询价草稿，本工具不会自动发送给任何公司。",
        "note_en": "This is a draft only. The tool never sends it to any company.",
    }


def molecule_only(smiles: str, with_svg: bool = True) -> MoleculeRecord:
    return parse_molecule(smiles, with_svg=with_svg)


# Re-export for callers
InvalidSmiles = InvalidSmiles
