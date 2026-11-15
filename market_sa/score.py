"""Market SA scoring. 1 = easier, 10 = harder. Documented and conservative."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable

from market_sa.config import (
    ACCEPTED_NO_PRICE_BASE,
    BLOOM_ONLY_INSTOCK_SCORE,
    BLOOM_ONLY_MINI_SCORE,
    CATALOG_LISTED_SCORE_MAX,
    CATALOG_LISTED_SCORE_MIN,
    CONDITIONAL_PENALTY,
    DECLINED_SCORES,
    FX_NOTE_EN,
    FX_NOTE_ZH,
    FX_TABLE_DATE,
    FX_USD_PER_UNIT,
    INSTOCK_PRICE_BONUS,
    NO_RESPONSE_SCORE,
    SCORE_DIRECTION_EN,
    SCORE_DIRECTION_ZH,
)

EVIDENCE_CLASSES = ("human_quote", "catalog_priced", "catalog_listed", "computational")


def clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def round2(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


class ConversionError(ValueError):
    pass


def usd_from_currency(amount: float, currency: str) -> tuple[float, str]:
    if currency is None or not str(currency).strip():
        raise ConversionError("缺少货币 / currency is missing")
    cur = str(currency).strip().upper()
    if cur not in FX_USD_PER_UNIT:
        known = ", ".join(sorted(set(FX_USD_PER_UNIT)))
        raise ConversionError(f"未知货币 {cur} / unknown currency {cur}. Known: {known}")
    rate = FX_USD_PER_UNIT[cur]
    usd = float(amount) * rate
    note = (
        f"{amount} {cur} ≈ {usd:.4f} USD "
        f"(frozen FX {FX_TABLE_DATE}: 1 {cur} = {rate} USD)"
    )
    return usd, note


def amount_to_grams(amount: float, unit: str, mw: float | None) -> tuple[float, str]:
    if amount is None:
        raise ConversionError("缺少数量 / amount is missing")
    if float(amount) <= 0:
        raise ConversionError("数量必须为正 / amount must be positive")
    if unit is None or not str(unit).strip():
        raise ConversionError("缺少单位 / unit is missing")
    u = str(unit).strip().lower().replace("µg", "ug").replace("μg", "ug")
    qty = float(amount)
    if u == "g":
        grams, how = qty, f"{qty} g"
    elif u == "mg":
        grams, how = qty / 1000.0, f"{qty} mg = {qty / 1000.0} g"
    elif u == "kg":
        grams, how = qty * 1000.0, f"{qty} kg = {qty * 1000.0} g"
    elif u in {"ug", "mcg"}:
        grams, how = qty / 1_000_000.0, f"{qty} ug = {qty / 1_000_000.0} g"
    elif u == "mmol":
        if mw is None or float(mw) <= 0:
            raise ConversionError("摩尔单位需要分子量 / mmol conversion requires MW")
        grams = qty * float(mw) / 1000.0
        how = f"{qty} mmol × MW {mw} / 1000 = {grams:.6f} g"
    else:
        raise ConversionError(f"未知单位 {unit} / unknown unit {unit}")
    if grams <= 0:
        raise ConversionError("折合克数为非正 / non-positive gram amount")
    return grams, how


def usd_per_gram(
    price: float,
    currency: str,
    amount: float,
    unit: str,
    mw: float | None,
) -> tuple[float, list[str]]:
    notes: list[str] = []
    usd, fx_note = usd_from_currency(price, currency)
    notes.append(fx_note)
    grams, unit_note = amount_to_grams(amount, unit, mw)
    notes.append(unit_note)
    per = usd / grams
    notes.append(f"{per:.6f} USD/g")
    return per, notes


def price_term(usd_per_g: float) -> float:
    """clip(1 + 1.5*log10(max(usd_per_g, 0.1)), 1, 9)"""
    return clip(1.0 + 1.5 * math.log10(max(float(usd_per_g), 0.1)), 1.0, 9.0)


def time_term(lead_days: float | None) -> float:
    """clip(0.7*log2(max(lead_days, 1)/7), 0, 2.5). Missing lead time → 0 (not invented)."""
    if lead_days is None:
        return 0.0
    return clip(0.7 * math.log2(max(float(lead_days), 1.0) / 7.0), 0.0, 2.5)


def accepted_or_priced_score(
    usd_per_g: float | None,
    lead_days: float | None,
    *,
    instock_bonus: bool = False,
) -> float:
    if usd_per_g is None:
        base = ACCEPTED_NO_PRICE_BASE + time_term(lead_days)
    else:
        base = price_term(usd_per_g) + time_term(lead_days)
    if instock_bonus:
        base += INSTOCK_PRICE_BONUS
    return clip(base, 1.0, 10.0)


def declined_score(reason_code: str | None) -> float:
    if reason_code in DECLINED_SCORES:
        return float(DECLINED_SCORES[reason_code])
    return float(DECLINED_SCORES[None])


def score_human_quote(quote: dict, mw: float | None) -> dict:
    """Return {score, components, notes, included_in_median, weight_class}."""
    decision = (quote.get("decision") or "").strip().lower()
    reason = quote.get("reason_code") or None
    if reason:
        reason = str(reason).strip().lower()
    notes: list[str] = []
    components: dict[str, Any] = {"decision": decision, "reason_code": reason}
    included = True
    weight_class = decision

    if decision == "declined":
        score = declined_score(reason)
        components["declined_score"] = score
        notes.append("拒绝接单按高分（更难）计入；化学上不可行严于业务范围外。")
    elif decision == "no_response":
        score = NO_RESPONSE_SCORE
        components["no_response_score"] = score
        notes.append("无回复是弱信号，若存在接单/拒单记录则不进入中位数。")
        weight_class = "no_response"
    elif decision in {"accepted", "conditional"}:
        usd_g = None
        if quote.get("price") is not None and quote.get("amount") is not None:
            try:
                usd_g, conv_notes = usd_per_gram(
                    float(quote["price"]),
                    quote.get("currency") or "USD",
                    float(quote["amount"]),
                    quote.get("unit") or "g",
                    mw,
                )
                notes.extend(conv_notes)
            except ConversionError as exc:
                notes.append(f"价格未能换算：{exc}")
        components["usd_per_g"] = round(usd_g, 6) if usd_g is not None else None
        components["lead_days"] = quote.get("lead_days")
        score = accepted_or_priced_score(usd_g, quote.get("lead_days"), instock_bonus=False)
        if decision == "conditional":
            score = clip(score + CONDITIONAL_PENALTY, 1.0, 10.0)
            components["conditional_penalty"] = CONDITIONAL_PENALTY
            notes.append(f"有条件接单在可计算分数上加罚 {CONDITIONAL_PENALTY}。")
        components["price_term"] = round2(price_term(usd_g)) if usd_g is not None else None
        components["time_term"] = round2(time_term(quote.get("lead_days")))
    else:
        raise ValueError(f"未知决策 / unknown decision: {decision}")

    return {
        "quote_id": quote.get("id"),
        "company": quote.get("company"),
        "decision": decision,
        "score": round2(score),
        "components": components,
        "notes": notes,
        "included_in_median": included,
        "weight_class": weight_class,
    }


def catalog_listed_score(n_unique_vendors: int, bloom: dict) -> tuple[float, float, str]:
    """Return (score, confidence, rationale). No prices involved."""
    hits = (bloom or {}).get("hits") or {}
    instock = bool(hits.get("zinc-instock"))
    mini = bool(hits.get("zinc-instock-mini"))
    zinc20 = bool(hits.get("zinc20"))
    purchasable_hit = instock or zinc20 or mini

    if n_unique_vendors > 0:
        # 1 vendor → near 3.5; 100+ vendors → 2.5
        ease = clip(math.log10(n_unique_vendors + 1) / math.log10(101), 0.0, 1.0)
        score = CATALOG_LISTED_SCORE_MAX - (CATALOG_LISTED_SCORE_MAX - CATALOG_LISTED_SCORE_MIN) * ease
        confidence = clip(0.45 + 0.30 * ease, 0.45, 0.75)
        if instock:
            confidence = clip(confidence + 0.04, 0.0, 0.80)
        why = (
            f"{n_unique_vendors} unique PubChem chemical vendors, no prices; "
            f"score in the {CATALOG_LISTED_SCORE_MIN}–{CATALOG_LISTED_SCORE_MAX} band "
            "(more vendors → slightly easier / higher confidence)."
        )
        return round2(score), round(confidence, 3), why

    if instock or zinc20:
        why = "molbloom purchasability hit (zinc-instock or zinc20) without a PubChem vendor list; lower confidence than a named vendor list."
        return BLOOM_ONLY_INSTOCK_SCORE, 0.32, why
    if mini:
        why = "only zinc-instock-mini bloom hit (higher false-positive rate), no vendor list."
        return BLOOM_ONLY_MINI_SCORE, 0.22, why
    if purchasable_hit:
        return BLOOM_ONLY_INSTOCK_SCORE, 0.30, "bloom purchasability hit without vendors"
    # surechembl alone is not treated as catalog-listed purchasability
    return None, None, "no catalog listing evidence"  # type: ignore[return-value]


def human_confidence(scored: list[dict], used: list[dict]) -> float:
    if not used:
        if scored:
            return 0.35  # only no_response
        return 0.0
    n = len(used)
    decisions = {s["decision"] for s in used}
    base = 0.78
    if n >= 3:
        base = 0.92
    elif n == 2:
        base = 0.86
    if decisions == {"accepted"}:
        with_price = sum(
            1 for s in used if (s.get("components") or {}).get("usd_per_g") is not None
        )
        if with_price == 0:
            base -= 0.12
    if "declined" in decisions and "accepted" in decisions:
        base = max(base, 0.84)
    if decisions == {"conditional"}:
        base -= 0.08
    return clip(base, 0.50, 0.95)


def median(values: Iterable[float]) -> float:
    seq = [float(v) for v in values]
    if not seq:
        raise ValueError("median of empty")
    return float(statistics.median(seq))


@dataclass
class ScoreResult:
    market_sa: float
    confidence: float
    evidence_class: str
    rationale_zh: str
    rationale_en: str
    is_real_market_quote: bool
    is_custom_synthesis_quote: bool
    quote_scores: list[dict] = field(default_factory=list)
    n_quotes_used: int = 0
    score_min: float | None = None
    score_max: float | None = None
    companies: list[str] = field(default_factory=list)
    fx_applied: bool = False
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "score": round2(self.market_sa),
            "confidence": round(self.confidence, 3),
            "evidence_class": self.evidence_class,
            "rationale_zh": self.rationale_zh,
            "rationale_en": self.rationale_en,
            "is_real_market_quote": self.is_real_market_quote,
            "is_custom_synthesis_quote": self.is_custom_synthesis_quote,
            "n_quotes_used": self.n_quotes_used,
            "score_min": round2(self.score_min),
            "score_max": round2(self.score_max),
            "companies": self.companies,
            "quote_scores": self.quote_scores,
            "fx_note_zh": FX_NOTE_ZH if self.fx_applied else None,
            "fx_note_en": FX_NOTE_EN if self.fx_applied else None,
            "direction_zh": SCORE_DIRECTION_ZH,
            "direction_en": SCORE_DIRECTION_EN,
            "details": self.details,
        }


def compute_market_sa(
    *,
    rdkit_sa: float,
    quotes: list[dict],
    mw: float | None,
    n_unique_vendors: int,
    bloom: dict,
    catalog_prices: list[dict] | None = None,
) -> ScoreResult:
    """Pick the strongest honest evidence class and map it to a 1–10 score."""
    scored_quotes = [score_human_quote(q, mw) for q in (quotes or [])]
    strong = [s for s in scored_quotes if s["weight_class"] != "no_response"]
    weak_only = scored_quotes and not strong

    if strong:
        vals = [s["score"] for s in strong]
        companies = [s["company"] for s in strong if s.get("company")]
        fx = any("USD/g" in n for s in strong for n in (s.get("notes") or []))
        conf = human_confidence(scored_quotes, strong)
        result = ScoreResult(
            market_sa=median(vals),
            confidence=conf,
            evidence_class="human_quote",
            rationale_zh=(
                f"以本分子人工报价账本中的 {len(strong)} 条有效记录（接单/拒单/有条件）的分数中位数作为 Market SA。"
                "这是最接近「外包是否愿意做、报价与周期」的信号。"
            ),
            rationale_en=(
                f"Market SA is the median of {len(strong)} human ledger quote score(s) "
                "(accepted / declined / conditional) for this exact molecule."
            ),
            is_real_market_quote=True,
            is_custom_synthesis_quote=True,
            quote_scores=scored_quotes,
            n_quotes_used=len(strong),
            score_min=min(vals),
            score_max=max(vals),
            companies=companies,
            fx_applied=fx,
        )
        return result

    # Priced catalog offers from optional commercial APIs (never invented).
    priced = list(catalog_prices or [])
    priced_scores: list[float] = []
    priced_details: list[dict] = []
    fx = False
    for offer in priced:
        try:
            usd_g = offer.get("usd_per_g")
            notes = []
            if usd_g is None and offer.get("price") is not None:
                usd_g, notes = usd_per_gram(
                    float(offer["price"]),
                    offer.get("currency") or "USD",
                    float(offer.get("amount") or 1),
                    offer.get("unit") or "g",
                    mw,
                )
                fx = True
            instock = bool(offer.get("instock") or offer.get("in_stock"))
            sc = accepted_or_priced_score(usd_g, offer.get("lead_days"), instock_bonus=instock)
            priced_scores.append(sc)
            priced_details.append(
                {
                    "source": offer.get("source"),
                    "supplier": offer.get("supplier") or offer.get("company"),
                    "usd_per_g": round(usd_g, 6) if usd_g is not None else None,
                    "lead_days": offer.get("lead_days"),
                    "instock_bonus": instock,
                    "score": round2(sc),
                    "notes": notes,
                }
            )
        except (ConversionError, TypeError, ValueError) as exc:
            priced_details.append({"source": offer.get("source"), "error": str(exc)})

    if priced_scores:
        conf = clip(0.62 + 0.04 * min(len(priced_scores), 4), 0.62, 0.80)
        return ScoreResult(
            market_sa=median(priced_scores),
            confidence=conf,
            evidence_class="catalog_priced",
            rationale_zh=(
                "使用可选商业目录返回的真实标价/货期，按与接单报价相同的价格-周期公式映射。"
                "这是目录标价，不是用户向 CRO 询价后得到的定制合成报价。"
            ),
            rationale_en=(
                "Mapped from catalog list prices and/or lead times using the same "
                "price/time formula as accepted quotes. This is a catalog list price, "
                "not a custom CRO synthesis quote."
            ),
            is_real_market_quote=True,
            is_custom_synthesis_quote=False,
            quote_scores=scored_quotes,
            n_quotes_used=0,
            score_min=min(priced_scores),
            score_max=max(priced_scores),
            companies=[d.get("supplier") or d.get("source") for d in priced_details if "score" in d],
            fx_applied=fx,
            details={"catalog_price_scores": priced_details},
        )

    listed = catalog_listed_score(n_unique_vendors, bloom)
    if listed[0] is not None:
        score, conf, why = listed
        extra = ""
        if weak_only:
            extra = " 账本中仅有无回复记录，信号弱，因此仍以目录命中为主，并把无回复附在明细中。"
        return ScoreResult(
            market_sa=score,
            confidence=conf,
            evidence_class="catalog_listed",
            rationale_zh=(
                "公开目录或供应商名录中出现了该分子，但没有价格或货期。"
                "给出偏易合成的中间分数，并明确这不是报价。" + extra
            ),
            rationale_en=(
                "The molecule appears in a public catalog or vendor list, but no price "
                "or lead time is available. A mid-easy default is used. This is not a quote. "
                + why
            ),
            is_real_market_quote=False,
            is_custom_synthesis_quote=False,
            quote_scores=scored_quotes,
            details={"catalog_listed_reason": why},
        )

    # Fallback: RDKit SA, clearly labeled computational.
    conf = 0.35
    rationale_zh = (
        "没有目录命中、供应商名录或有效人工报价，Market SA 回退为 RDKit SA Score。"
        "这只是计算启发式，不是真实市场可合成性或报价。"
    )
    rationale_en = (
        "No catalog, vendor, or usable human-quote evidence. Market SA falls back to "
        "the RDKit SA Score, labeled computational. This is a heuristic, not a market quote."
    )
    if weak_only:
        # Only no_response quotes and no catalog: still computational? Spec says
        # human_quote if ledger has entries. Use human_quote with low confidence
        # and the no_response score, since the user did record a market attempt.
        vals = [s["score"] for s in scored_quotes]
        return ScoreResult(
            market_sa=median(vals),
            confidence=0.35,
            evidence_class="human_quote",
            rationale_zh=(
                "账本中仅有无回复记录，没有目录证据。分数按无回复弱信号（偏中高，表示不确定性），"
                "置信度低，不能当作拒单。"
            ),
            rationale_en=(
                "Ledger contains only no-response entries and there is no catalog evidence. "
                "The no-response weak-signal score is used with low confidence; it is not a decline."
            ),
            is_real_market_quote=False,
            is_custom_synthesis_quote=False,
            quote_scores=scored_quotes,
            n_quotes_used=len(scored_quotes),
            score_min=min(vals),
            score_max=max(vals),
            companies=[s["company"] for s in scored_quotes if s.get("company")],
        )

    return ScoreResult(
        market_sa=float(rdkit_sa),
        confidence=conf,
        evidence_class="computational",
        rationale_zh=rationale_zh,
        rationale_en=rationale_en,
        is_real_market_quote=False,
        is_custom_synthesis_quote=False,
        quote_scores=scored_quotes,
        details={"fallback": "rdkit_sa"},
    )
