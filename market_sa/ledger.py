"""Local SQLite ledger for human-in-the-loop CRO / vendor quotes. Never auto-sends."""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from market_sa.config import AMOUNT_UNITS, DECISIONS, LEDGER_PATH, REASON_CODES, ensure_dirs

_LOCAL = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inchikey TEXT NOT NULL,
    canonical_smiles TEXT NOT NULL,
    company TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason_code TEXT,
    price REAL,
    currency TEXT,
    amount REAL,
    unit TEXT,
    purity TEXT,
    lead_days INTEGER,
    quoted_date TEXT,
    notes TEXT,
    raw_reply TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quotes_inchikey ON quotes(inchikey);
CREATE INDEX IF NOT EXISTS idx_quotes_smiles ON quotes(canonical_smiles);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(path: Path | None = None) -> sqlite3.Connection:
    ensure_dirs()
    p = path or LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    return _connect(path)


def _validate(payload: dict) -> dict:
    data = dict(payload)
    company = (data.get("company") or "").strip()
    if not company:
        raise ValueError("公司名称不能为空 / company is required")
    decision = (data.get("decision") or "").strip().lower()
    if decision not in DECISIONS:
        raise ValueError(f"decision 必须是 {DECISIONS} 之一")
    reason = data.get("reason_code") or None
    if reason is not None:
        reason = str(reason).strip().lower() or None
        if reason and reason not in REASON_CODES:
            raise ValueError(f"reason_code 必须是 {REASON_CODES} 之一，或留空")
    unit = data.get("unit") or None
    if unit:
        unit = str(unit).strip().lower().replace("µg", "ug").replace("μg", "ug")
        if unit not in AMOUNT_UNITS:
            raise ValueError(f"unit 必须是 {AMOUNT_UNITS} 之一")
    currency = data.get("currency") or None
    if currency:
        currency = str(currency).strip().upper()
    lead = data.get("lead_days")
    if lead is not None and lead != "":
        lead = int(lead)
        if lead < 0:
            raise ValueError("lead_days 不能为负")
    else:
        lead = None
    price = data.get("price")
    if price is not None and price != "":
        price = float(price)
        if price < 0:
            raise ValueError("price 不能为负")
    else:
        price = None
    amount = data.get("amount")
    if amount is not None and amount != "":
        amount = float(amount)
        if amount <= 0:
            raise ValueError("amount 必须为正")
    else:
        amount = None
    quoted = data.get("quoted_date") or None
    if quoted:
        quoted = str(quoted).strip()
        # accept YYYY-MM-DD or full ISO
        try:
            date.fromisoformat(quoted[:10])
            quoted = quoted[:10]
        except ValueError as exc:
            raise ValueError("quoted_date 需为 YYYY-MM-DD") from exc
    inchikey = (data.get("inchikey") or "").strip()
    smiles = (data.get("canonical_smiles") or "").strip()
    if not inchikey or not smiles:
        raise ValueError("缺少分子标识（inchikey / canonical_smiles）")
    return {
        "inchikey": inchikey,
        "canonical_smiles": smiles,
        "company": company,
        "decision": decision,
        "reason_code": reason,
        "price": price,
        "currency": currency,
        "amount": amount,
        "unit": unit,
        "purity": (str(data["purity"]).strip() if data.get("purity") not in (None, "") else None),
        "lead_days": lead,
        "quoted_date": quoted,
        "notes": (str(data["notes"]) if data.get("notes") not in (None, "") else None),
        "raw_reply": (str(data["raw_reply"]) if data.get("raw_reply") not in (None, "") else None),
    }


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def add_quote(payload: dict, *, path: Path | None = None) -> dict:
    data = _validate(payload)
    now = _now()
    conn = _connect(path)
    try:
        cur = conn.execute(
            """
            INSERT INTO quotes (
                inchikey, canonical_smiles, company, decision, reason_code,
                price, currency, amount, unit, purity, lead_days, quoted_date,
                notes, raw_reply, created_at, updated_at
            ) VALUES (
                :inchikey, :canonical_smiles, :company, :decision, :reason_code,
                :price, :currency, :amount, :unit, :purity, :lead_days, :quoted_date,
                :notes, :raw_reply, :created_at, :updated_at
            )
            """,
            {**data, "created_at": now, "updated_at": now},
        )
        conn.commit()
        return get_quote(cur.lastrowid, path=path)
    finally:
        conn.close()


def update_quote(quote_id: int, payload: dict, *, path: Path | None = None) -> dict:
    existing = get_quote(quote_id, path=path)
    if existing is None:
        raise KeyError(f"quote {quote_id} not found")
    merged = {**existing, **payload, "id": quote_id}
    data = _validate(merged)
    conn = _connect(path)
    try:
        conn.execute(
            """
            UPDATE quotes SET
                inchikey=:inchikey, canonical_smiles=:canonical_smiles,
                company=:company, decision=:decision, reason_code=:reason_code,
                price=:price, currency=:currency, amount=:amount, unit=:unit,
                purity=:purity, lead_days=:lead_days, quoted_date=:quoted_date,
                notes=:notes, raw_reply=:raw_reply, updated_at=:updated_at
            WHERE id = :id
            """,
            {**data, "updated_at": _now(), "id": int(quote_id)},
        )
        conn.commit()
        return get_quote(quote_id, path=path)
    finally:
        conn.close()


def delete_quote(quote_id: int, *, path: Path | None = None) -> bool:
    conn = _connect(path)
    try:
        cur = conn.execute("DELETE FROM quotes WHERE id = ?", (int(quote_id),))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_quote(quote_id: int, *, path: Path | None = None) -> dict | None:
    conn = _connect(path)
    try:
        row = conn.execute("SELECT * FROM quotes WHERE id = ?", (int(quote_id),)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_quotes(*, inchikey: str | None = None, path: Path | None = None) -> list[dict]:
    conn = _connect(path)
    try:
        if inchikey:
            rows = conn.execute(
                "SELECT * FROM quotes WHERE inchikey = ? ORDER BY quoted_date IS NULL, quoted_date DESC, id DESC",
                (inchikey,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM quotes ORDER BY id DESC"
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()
