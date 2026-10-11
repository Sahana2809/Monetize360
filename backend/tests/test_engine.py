"""
Correctness tests: run every domain's labelled test cases through the
engine and assert the computed price matches the expected price, and that
repeated runs are perfectly deterministic (same inputs -> byte-identical
output), independent of the ML-assist signals or conflict detector (which
run every time but must not introduce nondeterminism).
"""
import json
import os

import pytest

from app.engine.loader import load_config
from app.engine.simulate import run_simulation

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "app", "data")

DOMAINS = ["hospitality", "ride_hailing", "ecommerce"]


def _load_domain(domain: str):
    with open(os.path.join(DATA_DIR, "domains", f"{domain}.json")) as f:
        config = load_config(json.load(f))
    with open(os.path.join(DATA_DIR, "sample_contexts", f"{domain}_cases.json")) as f:
        cases = json.load(f)
    return config, cases


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_cases_match_expected_price(domain):
    config, cases = _load_domain(domain)
    report = run_simulation(config, cases)
    failures = [r for r in report["results"] if not r["pass"]]
    assert not failures, f"{domain} failures: {json.dumps(failures, indent=2, default=str)}"
    assert report["accuracy_pct"] == 100.0


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_cases_are_deterministic_across_runs(domain):
    config, cases = _load_domain(domain)
    first = run_simulation(config, cases)
    second = run_simulation(config, cases)
    actual_first = [r["actual_price"] for r in first["results"]]
    actual_second = [r["actual_price"] for r in second["results"]]
    assert actual_first == actual_second


def test_banking_domain_loads_and_prices_deterministically():
    with open(os.path.join(DATA_DIR, "domains_pending", "banking.json")) as f:
        config = load_config(json.load(f))
    context = {
        "base_rate": 6.0,
        "credit_score": 610,
        "loan_to_value_ratio": 0.95,
        "debt_to_income_ratio": 0.5,
        "loan_term_months": 360,
        "customer_segment": "existing_customer",
        "collateral_type": "secured",
        "delinquency_history_count": 2,
    }
    from app.engine.evaluator import compute_price
    r1 = compute_price(config, context)
    r2 = compute_price(config, context)
    assert r1.final_price == r2.final_price
    assert r1.final_price > config.base_price.value if config.base_price.value else True


def test_ride_hailing_conflict_detected_between_surge_addon_and_promo():
    config, _ = _load_domain("ride_hailing")
    from app.engine.evaluator import detect_conflicts
    conflicts = detect_conflicts(config)
    kinds = {c.kind for c in conflicts}
    assert "priority_tie" in kinds
    flagged_pairs = [set(c.rule_ids) for c in conflicts if c.kind == "priority_tie"]
    assert {"demand_based_surge_addon", "first_ride_promo_discount"} in flagged_pairs


def test_hospitality_no_false_conflicts_on_disjoint_segment_rules():
    config, _ = _load_domain("hospitality")
    from app.engine.evaluator import detect_conflicts
    conflicts = detect_conflicts(config)
    flagged_pairs = [set(c.rule_ids) for c in conflicts]
    assert {"loyalty_gold_discount", "corporate_negotiated_rate"} not in flagged_pairs
