from market_sa.molecule import parse_molecule
from market_sa.rfq import draft_rfq


def test_rfq_contains_identifiers():
    mol = parse_molecule("CCO", with_svg=False)
    drafts = draft_rfq(mol)
    for key in ("zh", "en", "combined"):
        text = drafts[key]
        assert mol.canonical_smiles in text
        assert mol.inchikey in text
        assert mol.formula in text
        assert "100 mg" in text
        assert "1 g" in text
    assert "不是正式订单" in drafts["zh"]
    assert "not a purchase order" in drafts["en"].lower()
