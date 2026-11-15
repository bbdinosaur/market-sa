"""Command-line interface: eval, add-quote, quotes, rfq, serve."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from market_sa import __version__, ledger
from market_sa.evaluate import evaluate_smiles, rfq_for_smiles
from market_sa.molecule import InvalidSmiles, parse_molecule


def _print_json(data: Any) -> int:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _die_invalid(exc: InvalidSmiles) -> int:
    print(f"错误 / Error: {exc}", file=sys.stderr)
    return 2


def cmd_eval(args: argparse.Namespace) -> int:
    try:
        result = evaluate_smiles(args.smiles, include_svg=args.json, include_listings=False)
    except InvalidSmiles as exc:
        return _die_invalid(exc)
    if args.json:
        if not args.include_svg:
            result.get("molecule", {}).pop("structure_svg", None)
        return _print_json(result)
    _print_human(result)
    return 0


def _print_human(result: dict) -> None:
    mol = result["molecule"]
    msa = result["market_sa"]
    rd = result["rdkit_sa"]
    bloom = result.get("bloom") or {}
    pc = result.get("pubchem") or {}
    hq = result.get("human_quotes") or {}
    line = "─" * 56
    print("MarketSA 评估结果")
    print(line)
    print(f"输入 SMILES : {mol.get('input_smiles')}")
    print(f"Canonical   : {mol.get('canonical_smiles')}")
    print(f"InChIKey    : {mol.get('inchikey')}")
    print(f"分子式 / MW : {mol.get('formula')}    {mol.get('mw')}")
    print()
    ev = msa.get("evidence_class")
    print(f"Market SA   : {msa.get('score')}    [{ev}]    置信度 {msa.get('confidence')}")
    print(f"            : {msa.get('direction_zh')}")
    print(f"            : {result.get('honesty', {}).get('disclaimer_zh')}")
    if msa.get("n_quotes_used"):
        print(
            f"            : n={msa['n_quotes_used']}  "
            f"min={msa.get('score_min')}  max={msa.get('score_max')}  "
            f"公司={', '.join(msa.get('companies') or [])}"
        )
    print()
    print(f"RDKit SA    : {rd.get('score')}    （计算启发式，不是市场报价）")
    print()
    hits = bloom.get("hits") or {}
    if hits:
        print("molbloom    :")
        for name, flag in hits.items():
            kind = (bloom.get("kinds") or {}).get(name, "")
            label = "可能可购 True" if flag else "不在目录 False"
            print(f"            - {name} ({kind}): {label}")
        print(f"            {bloom.get('note_zh')}")
    else:
        print("molbloom    : （无结果）")
    print()
    if pc.get("cid"):
        print(f"PubChem     : CID {pc['cid']}  {pc.get('title') or ''}")
        print(f"            : {pc.get('compound_url')}")
        print(f"            : 供应商 {pc.get('vendor_count', 0)} 家，条目 {pc.get('listing_count', 0)} 条")
        print("            : 无价格 / 无货期（不会编造）")
        names = [v["name"] for v in (pc.get("vendors") or [])[:12]]
        if names:
            more = pc.get("vendor_count", 0) - len(names)
            extra = f" … 另有 {more} 家" if more > 0 else ""
            print(f"            : {', '.join(names)}{extra}")
    elif pc.get("error"):
        print(f"PubChem     : 不可用 — {pc.get('error')}")
    else:
        print("PubChem     : 未找到 CID")
    print()
    nq = hq.get("n") or 0
    print(f"人工报价    : {nq} 条（本地账本，非自动询价）")
    for q in hq.get("quotes") or []:
        bits = [
            q.get("company"),
            q.get("decision"),
        ]
        if q.get("price") is not None:
            bits.append(f"{q.get('price')} {q.get('currency') or ''}".strip())
        if q.get("amount") is not None:
            bits.append(f"{q.get('amount')} {q.get('unit') or ''}".strip())
        if q.get("lead_days") is not None:
            bits.append(f"{q.get('lead_days')} 天")
        print(f"            - #{q.get('id')}: " + ", ".join(str(b) for b in bits if b))
    comm = result.get("commercial") or {}
    if comm.get("configured"):
        print(f"商业目录    : 已配置 {', '.join(comm['configured'])}；offers={len(comm.get('offers') or [])}")
    print()
    for w in result.get("warnings") or []:
        print(f"注意        : {w}")


def cmd_add_quote(args: argparse.Namespace) -> int:
    try:
        mol = parse_molecule(args.smiles, with_svg=False)
    except InvalidSmiles as exc:
        return _die_invalid(exc)
    payload = {
        "inchikey": mol.inchikey,
        "canonical_smiles": mol.canonical_smiles,
        "company": args.company,
        "decision": args.decision,
        "reason_code": args.reason_code,
        "price": args.price,
        "currency": args.currency,
        "amount": args.amount,
        "unit": args.unit,
        "purity": args.purity,
        "lead_days": args.lead_days,
        "quoted_date": args.quoted_date,
        "notes": args.notes,
        "raw_reply": args.raw_reply,
    }
    try:
        row = ledger.add_quote(payload)
    except ValueError as exc:
        print(f"错误 / Error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        return _print_json(row)
    print(f"已登记报价 #{row['id']}  {row['company']}  {row['decision']}  ({mol.inchikey})")
    return 0


def cmd_quotes(args: argparse.Namespace) -> int:
    inchikey = None
    if args.smiles:
        try:
            mol = parse_molecule(args.smiles, with_svg=False)
        except InvalidSmiles as exc:
            return _die_invalid(exc)
        inchikey = mol.inchikey
    rows = ledger.list_quotes(inchikey=inchikey)
    if args.json:
        return _print_json(rows)
    if not rows:
        print("没有报价记录。")
        return 0
    for q in rows:
        print(
            f"#{q['id']}  {q['canonical_smiles']}  {q['company']}  {q['decision']}"
            + (f"  {q['price']} {q.get('currency')}" if q.get("price") is not None else "")
            + (f"  {q['amount']} {q.get('unit')}" if q.get("amount") is not None else "")
            + (f"  {q['lead_days']}d" if q.get("lead_days") is not None else "")
        )
    return 0


def cmd_delete_quote(args: argparse.Namespace) -> int:
    ok = ledger.delete_quote(args.id)
    if not ok:
        print(f"未找到报价 #{args.id}", file=sys.stderr)
        return 1
    print(f"已删除报价 #{args.id}")
    return 0


def cmd_rfq(args: argparse.Namespace) -> int:
    try:
        payload = rfq_for_smiles(args.smiles)
    except InvalidSmiles as exc:
        return _die_invalid(exc)
    if args.json:
        return _print_json(payload)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(payload["drafts"]["combined"])
        print(f"已写入 {args.out}（不会自动发送）")
        return 0
    sys.stdout.write(payload["drafts"]["combined"])
    print("\n（以上仅为草稿，本工具不会自动发送给任何公司。）")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn
    from market_sa.web import app

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="market-sa",
        description=(
            "MarketSA：输入 SMILES，得到带证据分级的市场可合成性分数。"
            "本工具不会向任何公司自动发送询价或订单。"
        ),
    )
    p.add_argument("--version", action="version", version=f"MarketSA {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    ev = sub.add_parser("eval", help="评估一个 SMILES")
    ev.add_argument("smiles")
    ev.add_argument("--json", action="store_true")
    ev.add_argument("--include-svg", action="store_true", help="在 JSON 中包含结构 SVG")
    ev.set_defaults(func=cmd_eval)

    aq = sub.add_parser("add-quote", help="向本地账本登记一条人工报价（不会外发）")
    aq.add_argument("--smiles", required=True)
    aq.add_argument("--company", required=True)
    aq.add_argument(
        "--decision",
        required=True,
        choices=["accepted", "declined", "no_response", "conditional"],
    )
    aq.add_argument("--reason-code", choices=["chemically_infeasible", "out_of_scope", "capacity", "other"])
    aq.add_argument("--price", type=float)
    aq.add_argument("--currency", default="USD")
    aq.add_argument("--amount", type=float)
    aq.add_argument("--unit", default="g", choices=["g", "mg", "kg", "ug", "mmol"])
    aq.add_argument("--purity")
    aq.add_argument("--lead-days", type=int)
    aq.add_argument("--quoted-date", help="YYYY-MM-DD")
    aq.add_argument("--notes")
    aq.add_argument("--raw-reply")
    aq.add_argument("--json", action="store_true")
    aq.set_defaults(func=cmd_add_quote)

    lq = sub.add_parser("quotes", help="列出本地人工报价")
    lq.add_argument("--smiles")
    lq.add_argument("--json", action="store_true")
    lq.set_defaults(func=cmd_quotes)

    dq = sub.add_parser("delete-quote", help="删除一条本地报价")
    dq.add_argument("--id", type=int, required=True)
    dq.set_defaults(func=cmd_delete_quote)

    rf = sub.add_parser("rfq", help="生成询价草稿（不发送）")
    rf.add_argument("smiles")
    rf.add_argument("--json", action="store_true")
    rf.add_argument("--out", help="保存到文本文件")
    rf.set_defaults(func=cmd_rfq)

    sv = sub.add_parser("serve", help="启动本地网页界面")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
