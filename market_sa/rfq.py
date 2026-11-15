"""RFQ draft generator. Produces text for the user to send themselves. Never sends."""

from __future__ import annotations

from market_sa.config import DEFAULT_RFQ_AMOUNTS
from market_sa.molecule import MoleculeRecord


def format_amounts(amounts=DEFAULT_RFQ_AMOUNTS) -> str:
    parts = [f"{qty} {unit}" for qty, unit in amounts]
    if len(parts) == 1:
        return parts[0]
    return "、".join(parts[:-1]) + " 以及 " + parts[-1]


def format_amounts_en(amounts=DEFAULT_RFQ_AMOUNTS) -> str:
    parts = [f"{qty} {unit}" for qty, unit in amounts]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def draft_rfq(mol: MoleculeRecord, *, amounts=DEFAULT_RFQ_AMOUNTS) -> dict[str, str]:
    amt_zh = format_amounts(amounts)
    amt_en = format_amounts_en(amounts)
    zh = f"""您好，

我们正在评估一个化合物的定制合成可行性，希望向贵司询价。本邮件仅为询价，不是正式订单。

化合物信息：
- SMILES：{mol.canonical_smiles}
- InChIKey：{mol.inchikey}
- 分子式：{mol.formula}
- 分子量：{mol.mw:.2f}

请就以下规格评估是否可以合成，并提供报价：
- 数量：{amt_zh}（如有其他包装也可一并列出）
- 请告知：1）是否可以合成 / 是否接单；2）价格与币种；3）货期（工作日或自然日）；4）可提供的纯度；5）任何关于可行性、路线难点或限制的说明。

如无法开展，也非常希望知道原因（例如超出业务范围，或化学上难以实现），这对我们非常有帮助。

谢谢。
"""
    en = f"""Hello,

We would like a quotation for custom synthesis of the compound below. This is an inquiry only, not a purchase order.

Compound:
- SMILES: {mol.canonical_smiles}
- InChIKey: {mol.inchikey}
- Formula: {mol.formula}
- Molecular weight: {mol.mw:.2f}

Please evaluate the following amounts: {amt_en} (other pack sizes are welcome).
Kindly include:
1) whether you can synthesize / accept the order;
2) price and currency;
3) lead time (business or calendar days);
4) attainable purity;
5) any comments on feasibility, route difficulty, or limitations.

If you cannot take the work, a brief reason (for example, outside business scope versus chemically infeasible) would be very helpful.

Thank you.
"""
    combined = (
        "===== 中文询价草稿 / Chinese RFQ draft =====\n\n"
        + zh.strip()
        + "\n\n===== English RFQ draft =====\n\n"
        + en.strip()
        + "\n"
    )
    return {"zh": zh.strip() + "\n", "en": en.strip() + "\n", "combined": combined}
