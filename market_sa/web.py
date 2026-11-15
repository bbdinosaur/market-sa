"""Local FastAPI app. Never sends RFQs or orders."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from market_sa import __version__, ledger
from market_sa.config import AMOUNT_UNITS, DECISIONS, REASON_CODES, SCORE_DIRECTION_ZH
from market_sa.evaluate import evaluate_smiles, rfq_for_smiles
from market_sa.molecule import InvalidSmiles, parse_molecule

TEMPLATE = Path(__file__).parent / "templates" / "index.html"

app = FastAPI(
    title="MarketSA",
    version=__version__,
    description="Market-informed synthetic accessibility. Does not send inquiries or orders.",
)


class EvalRequest(BaseModel):
    smiles: str


class QuoteRequest(BaseModel):
    smiles: str
    company: str
    decision: str
    reason_code: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = "USD"
    amount: Optional[float] = None
    unit: Optional[str] = "g"
    purity: Optional[str] = None
    lead_days: Optional[int] = None
    quoted_date: Optional[str] = None
    notes: Optional[str] = None
    raw_reply: Optional[str] = None


class QuoteUpdate(BaseModel):
    company: Optional[str] = None
    decision: Optional[str] = None
    reason_code: Optional[str] = Field(default=None)
    price: Optional[float] = None
    currency: Optional[str] = None
    amount: Optional[float] = None
    unit: Optional[str] = None
    purity: Optional[str] = None
    lead_days: Optional[int] = None
    quoted_date: Optional[str] = None
    notes: Optional[str] = None
    raw_reply: Optional[str] = None
    smiles: Optional[str] = None


def _eval_or_400(smiles: str, include_svg: bool = True) -> dict[str, Any]:
    try:
        return evaluate_smiles(smiles, include_svg=include_svg)
    except InvalidSmiles as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


@app.get("/api/meta")
def meta() -> dict:
    return {
        "name": "MarketSA",
        "version": __version__,
        "direction_zh": SCORE_DIRECTION_ZH,
        "decisions": DECISIONS,
        "reason_codes": REASON_CODES,
        "units": AMOUNT_UNITS,
        "never_auto_sends": True,
    }


@app.post("/api/eval")
def api_eval(body: EvalRequest) -> dict:
    return _eval_or_400(body.smiles, include_svg=True)


@app.get("/api/eval")
def api_eval_get(smiles: str = Query(..., min_length=1)) -> dict:
    return _eval_or_400(smiles, include_svg=True)


@app.get("/api/structure.svg")
def api_structure(smiles: str = Query(..., min_length=1)) -> Response:
    try:
        mol = parse_molecule(smiles, with_svg=True)
    except InvalidSmiles as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=mol.structure_svg or "", media_type="image/svg+xml")


@app.get("/api/quotes")
def api_quotes(smiles: Optional[str] = None) -> dict:
    inchikey = None
    if smiles:
        try:
            mol = parse_molecule(smiles, with_svg=False)
        except InvalidSmiles as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        inchikey = mol.inchikey
    return {"quotes": ledger.list_quotes(inchikey=inchikey)}


@app.post("/api/quotes")
def api_add_quote(body: QuoteRequest) -> dict:
    try:
        mol = parse_molecule(body.smiles, with_svg=False)
        row = ledger.add_quote(
            {
                **body.model_dump(),
                "inchikey": mol.inchikey,
                "canonical_smiles": mol.canonical_smiles,
            }
        )
    except InvalidSmiles as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"quote": row, "evaluation": evaluate_smiles(body.smiles, include_svg=True)}


@app.put("/api/quotes/{quote_id}")
def api_update_quote(quote_id: int, body: QuoteUpdate) -> dict:
    existing = ledger.get_quote(quote_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"quote {quote_id} not found")
    payload = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if body.smiles:
        try:
            mol = parse_molecule(body.smiles, with_svg=False)
        except InvalidSmiles as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload["inchikey"] = mol.inchikey
        payload["canonical_smiles"] = mol.canonical_smiles
    try:
        row = ledger.update_quote(quote_id, payload)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"quote": row}


@app.delete("/api/quotes/{quote_id}")
def api_delete_quote(quote_id: int) -> dict:
    if not ledger.delete_quote(quote_id):
        raise HTTPException(status_code=404, detail=f"quote {quote_id} not found")
    return {"deleted": quote_id}


@app.get("/api/rfq")
def api_rfq(smiles: str = Query(..., min_length=1), download: bool = False):
    try:
        payload = rfq_for_smiles(smiles)
    except InvalidSmiles as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if download:
        filename = f"MarketSA-RFQ-{payload['molecule']['inchikey']}.txt"
        return PlainTextResponse(
            content=payload["drafts"]["combined"],
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return payload
