from market_sa.score import (
    accepted_or_priced_score,
    amount_to_grams,
    catalog_listed_score,
    compute_market_sa,
    declined_score,
    price_term,
    score_human_quote,
    time_term,
    usd_from_currency,
    usd_per_gram,
)


def test_declined_harsher_than_out_of_scope():
    chem = declined_score("chemically_infeasible")
    scope = declined_score("out_of_scope")
    other = declined_score(None)
    assert 8.5 <= scope < chem <= 10
    assert 8.5 <= other <= 10
    assert chem >= 9.5


def test_cheap_fast_vs_expensive_slow():
    cheap = accepted_or_priced_score(1.0, 7)
    mid = accepted_or_priced_score(100.0, 21)
    slow = accepted_or_priced_score(10_000.0, 90)
    assert abs(cheap - 1.0) < 1e-9  # 1 + 1.5*log10(1) + 0
    assert cheap < mid < slow
    assert slow <= 10
    # documented formula checks
    assert abs(price_term(100) - (1 + 1.5 * 2)) < 1e-9  # log10(100)=2 → 4.0
    assert abs(time_term(28) - (0.7 * 2)) < 1e-9  # 28/7=4, log2=2 → 1.4


def test_instock_bonus_makes_easier():
    a = accepted_or_priced_score(50, 14, instock_bonus=False)
    b = accepted_or_priced_score(50, 14, instock_bonus=True)
    assert b == max(1.0, a - 0.5)


def test_fx_and_mmol_conversion():
    usd, note = usd_from_currency(712, "CNY")
    assert abs(usd - 712 * 0.1404) < 1e-9
    assert "2026-11-15" in note
    grams, how = amount_to_grams(100, "mmol", mw=46.069)
    assert abs(grams - 4.6069) < 1e-6
    per, notes = usd_per_gram(46.069, "USD", 100, "mmol", 46.069)
    # 46.069 USD for 4.6069 g ≈ 10 USD/g
    assert abs(per - 10.0) < 1e-6


def test_human_quote_median_and_classes():
    quotes = [
        {
            "id": 1,
            "company": "A",
            "decision": "accepted",
            "price": 120,
            "currency": "USD",
            "amount": 1,
            "unit": "g",
            "lead_days": 21,
        },
        {
            "id": 2,
            "company": "B",
            "decision": "declined",
            "reason_code": "chemically_infeasible",
        },
    ]
    result = compute_market_sa(
        rdkit_sa=2.0,
        quotes=quotes,
        mw=180.16,
        n_unique_vendors=10,
        bloom={"hits": {"zinc-instock": True}},
    )
    assert result.evidence_class == "human_quote"
    assert result.n_quotes_used == 2
    s1 = score_human_quote(quotes[0], 180.16)["score"]
    s2 = score_human_quote(quotes[1], 180.16)["score"]
    import statistics
    assert result.market_sa == statistics.median([s1, s2])
    assert result.is_custom_synthesis_quote is True
    assert {c.lower() for c in result.companies} == {"a", "b"}


def test_no_response_does_not_outrank_catalog():
    result = compute_market_sa(
        rdkit_sa=8.0,
        quotes=[{"id": 1, "company": "X", "decision": "no_response"}],
        mw=46.07,
        n_unique_vendors=20,
        bloom={"hits": {"zinc-instock": True}},
    )
    assert result.evidence_class == "catalog_listed"
    assert 2.5 <= result.market_sa <= 3.5


def test_catalog_listed_more_vendors_easier_and_bloom_only_lower_confidence():
    many = catalog_listed_score(80, {"hits": {"zinc-instock": True}})
    few = catalog_listed_score(1, {"hits": {"zinc-instock": True}})
    bloom = catalog_listed_score(0, {"hits": {"zinc-instock": True}})
    mini = catalog_listed_score(0, {"hits": {"zinc-instock-mini": True}})
    none = catalog_listed_score(0, {"hits": {}})
    assert many[0] < few[0]
    assert many[1] > few[1]
    assert bloom[1] < few[1]
    assert mini[1] < bloom[1]
    assert none[0] is None


def test_computational_fallback_is_rdkit_and_labeled():
    result = compute_market_sa(
        rdkit_sa=4.321,
        quotes=[],
        mw=100,
        n_unique_vendors=0,
        bloom={"hits": {}},
    )
    assert result.evidence_class == "computational"
    assert abs(result.market_sa - 4.321) < 1e-9
    assert result.is_real_market_quote is False
    assert result.confidence < 0.5
