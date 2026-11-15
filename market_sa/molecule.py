"""SMILES parsing, descriptors, 2D structure, and RDKit SA Score."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from rdkit import Chem
from rdkit import RDLogger
from rdkit.Chem import Descriptors, RDConfig, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D

RDLogger.DisableLog("rdApp.error")
RDLogger.DisableLog("rdApp.warning")

_SA_DIR = os.path.join(RDConfig.RDContribDir, "SA_Score")
if _SA_DIR not in sys.path:
    sys.path.append(_SA_DIR)

import sascorer  # noqa: E402  (RDKit contrib; path patched above)


class InvalidSmiles(ValueError):
    """Raised when a SMILES string cannot be parsed or sanitized."""


@dataclass(frozen=True)
class MoleculeRecord:
    input_smiles: str
    canonical_smiles: str
    inchikey: str
    formula: str
    mw: float
    rdkit_sa: float
    structure_svg: str | None = None

    def to_dict(self, *, include_svg: bool = True) -> dict:
        data = {
            "input_smiles": self.input_smiles,
            "canonical_smiles": self.canonical_smiles,
            "inchikey": self.inchikey,
            "formula": self.formula,
            "mw": round(self.mw, 4),
            "rdkit_sa": round(self.rdkit_sa, 4),
        }
        if include_svg:
            data["structure_svg"] = self.structure_svg
        return data


def mol_from_smiles(smiles: str) -> Chem.Mol:
    if smiles is None or not str(smiles).strip():
        raise InvalidSmiles("SMILES 为空 / SMILES is empty")
    raw = str(smiles).strip()
    mol = Chem.MolFromSmiles(raw)
    if mol is None:
        raise InvalidSmiles(f"无法解析 SMILES / cannot parse SMILES: {raw}")
    try:
        Chem.SanitizeMol(mol)
    except Exception as exc:  # rdkit can raise various sanitize errors
        raise InvalidSmiles(f"SMILES 无法通过化学卫生检查 / sanitization failed: {raw}") from exc
    return mol


def canonical_smiles(mol: Chem.Mol) -> str:
    return Chem.MolToSmiles(mol, canonical=True)


def rdkit_sa_score(mol: Chem.Mol) -> float:
    return float(sascorer.calculateScore(mol))


def structure_svg(mol: Chem.Mol, width: int = 360, height: int = 280) -> str:
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    opts = drawer.drawOptions()
    opts.clearBackground = False
    opts.bondLineWidth = 1.6
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def parse_molecule(smiles: str, *, with_svg: bool = True) -> MoleculeRecord:
    mol = mol_from_smiles(smiles)
    canon = canonical_smiles(mol)
    try:
        key = Chem.inchi.MolToInchiKey(mol)
    except Exception as exc:
        raise InvalidSmiles(f"无法计算 InChIKey / InChIKey failed: {smiles}") from exc
    if not key:
        raise InvalidSmiles(f"InChIKey 为空 / empty InChIKey: {smiles}")
    return MoleculeRecord(
        input_smiles=str(smiles).strip(),
        canonical_smiles=canon,
        inchikey=key,
        formula=rdMolDescriptors.CalcMolFormula(mol),
        mw=float(Descriptors.MolWt(mol)),
        rdkit_sa=rdkit_sa_score(mol),
        structure_svg=structure_svg(mol) if with_svg else None,
    )
