from market_sa.molecule import InvalidSmiles, parse_molecule, rdkit_sa_score, mol_from_smiles


def test_ethanol_properties():
    mol = parse_molecule("CCO", with_svg=True)
    assert mol.canonical_smiles == "CCO"
    assert mol.inchikey == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
    assert mol.formula == "C2H6O"
    assert abs(mol.mw - 46.069) < 0.02
    assert 1.0 <= mol.rdkit_sa < 3.0
    assert mol.structure_svg and "<svg" in mol.structure_svg.lower()


def test_aspirin_canonical_and_sa():
    mol = parse_molecule("CC(=O)Oc1ccccc1C(=O)O", with_svg=False)
    assert mol.inchikey == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    assert mol.formula == "C9H8O4"
    assert mol.rdkit_sa < 3.0


def test_invalid_smiles():
    for bad in ["", "   ", "not-a-smiles", "C(C(C"]:
        try:
            parse_molecule(bad, with_svg=False)
            assert False, f"expected InvalidSmiles for {bad!r}"
        except InvalidSmiles:
            pass


def test_rdkit_sa_direction():
    easy = rdkit_sa_score(mol_from_smiles("CCO"))
    # A more decorated unusual heterocycle should not be easier than ethanol
    odd = rdkit_sa_score(mol_from_smiles("ONN1CCCC1"))
    assert easy < odd
