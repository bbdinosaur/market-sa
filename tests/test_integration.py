from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_sa.evaluate import evaluate_smiles
from market_sa.molecule import InvalidSmiles

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
MOLECULES = {
    "ethanol": "CCO",
    "aspirin": "CC(=O)Oc1ccccc1C(=O)O",
    "unusual": "ONN1CCCC1",
}


def _compact(result: dict) -> dict:
    data = json.loads(json.dumps(result))
    if "molecule" in data:
        data["molecule"].pop("structure_svg", None)
    if "pubchem" in data:
        data["pubchem"].pop("listings", None)
        vendors = data["pubchem"].get("vendors") or []
        # keep a short vendor preview in the saved example
        data["pubchem"]["vendors_preview"] = vendors[:15]
        data["pubchem"]["vendors"] = vendors[:15]
    return data


@pytest.mark.parametrize("name,smiles", list(MOLECULES.items()))
def test_live_or_cached_eval(name, smiles):
    EXAMPLES.mkdir(exist_ok=True)
    result = evaluate_smiles(smiles, include_svg=True, include_listings=False)
    assert "market_sa" in result
    assert "rdkit_sa" in result
    assert result["rdkit_sa"]["kind"] == "computational_heuristic"
    ev = result["market_sa"]["evidence_class"]
    assert ev in {"human_quote", "catalog_priced", "catalog_listed", "computational"}

    if name in {"ethanol", "aspirin"}:
        bloom = result.get("bloom") or {}
        assert bloom.get("any_purchasability_hit") is True
        # Widely sold compounds should have catalog evidence unless PubChem is down
        if result.get("pubchem", {}).get("ok"):
            assert ev in {"catalog_listed", "catalog_priced", "human_quote"}
            if ev == "catalog_listed":
                assert result["pubchem"]["vendor_count"] >= 1 or bloom.get("any_purchasability_hit")
        # Must not invent prices
        assert result["pubchem"].get("prices_available") in (False, None)
    else:
        # Unusual structure: do not invent vendors/prices
        assert result["pubchem"].get("prices_available") in (False, None)
        if result.get("pubchem", {}).get("ok") and result["pubchem"].get("cid"):
            # If CID exists, vendor list must be whatever PubChem actually returned (may be zero)
            assert result["pubchem"]["vendor_count"] == len(result["pubchem"].get("vendors") or [])
        if ev == "computational":
            assert result["honesty"]["is_real_market_quote"] is False
            assert abs(result["market_sa"]["score"] - result["rdkit_sa"]["score"]) < 0.02

    out = EXAMPLES / f"{name}.json"
    out.write_text(json.dumps(_compact(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert out.exists()


def test_invalid_smiles_raises():
    with pytest.raises(InvalidSmiles):
        evaluate_smiles("this-is-not-smiles", include_svg=False)
