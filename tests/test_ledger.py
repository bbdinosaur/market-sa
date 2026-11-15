from market_sa.ledger import add_quote, delete_quote, get_quote, list_quotes, update_quote
from market_sa.molecule import parse_molecule


def _base(tmp_ledger, smiles="CCO", **kwargs):
    mol = parse_molecule(smiles, with_svg=False)
    payload = {
        "inchikey": mol.inchikey,
        "canonical_smiles": mol.canonical_smiles,
        "company": "Test CRO",
        "decision": "accepted",
        "price": 120,
        "currency": "USD",
        "amount": 1,
        "unit": "g",
        "lead_days": 21,
        "purity": "98%",
        "quoted_date": "2026-11-15",
        "notes": "demo",
    }
    payload.update(kwargs)
    return add_quote(payload, path=tmp_ledger)


def test_ledger_round_trip(tmp_ledger):
    row = _base(tmp_ledger)
    assert row["id"] >= 1
    assert row["company"] == "Test CRO"
    fetched = get_quote(row["id"], path=tmp_ledger)
    assert fetched["price"] == 120
    listed = list_quotes(inchikey=row["inchikey"], path=tmp_ledger)
    assert len(listed) == 1
    updated = update_quote(row["id"], {**fetched, "lead_days": 30, "decision": "conditional"}, path=tmp_ledger)
    assert updated["lead_days"] == 30
    assert updated["decision"] == "conditional"
    assert delete_quote(row["id"], path=tmp_ledger) is True
    assert list_quotes(inchikey=row["inchikey"], path=tmp_ledger) == []


def test_ledger_rejects_bad_decision(tmp_ledger):
    try:
        _base(tmp_ledger, decision="maybe")
        assert False, "expected ValueError"
    except ValueError:
        pass
