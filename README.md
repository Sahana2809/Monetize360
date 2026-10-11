# Monetize360 — Universal Dynamic Pricing Engine

**Team ShePlusPlus** — Problem 5B

A single, configurable, explainable dynamic pricing engine that prices across
hospitality, ride-hailing, e-commerce and banking from **JSON configuration
alone** — the evaluation engine contains zero domain-specific code. Adding a
new industry means authoring a new config document, not touching Python.

## Why this architecture

The problem statement's hard requirement is: *"Adding a new domain should be
primarily configuration, not a rewrite."* Every design decision here serves
that:

- **What gets priced, and what influences price, is all metadata.** A
  `DomainConfig` names an entity, its attributes, a base-price source, a list
  of condition→adjustment rules, and output constraints. The engine never
  references `occupancy_rate` or `demand_supply_ratio` by name — it only
  knows "attribute", "condition", "adjustment".
- **Rules are data, not code.** A condition is a small JSON boolean-logic
  tree (`all`/`any`/`not`/comparison leaves); an adjustment is one of
  `multiply`, `percent`, `add`, `set`, or `formula` (a tiny sandboxed
  expression evaluator — no `eval()`). This covers markups, discounts,
  tiers, surcharges, caps, and price-matching without new engine code.
- **Explainability is structural, not bolted on.** `compute_price()` returns
  every rule that fired (with before/after price), every rule skipped (and
  why), every constraint that clamped the result, every ML-assist signal
  computed, and the full context used — one object, always, for every price.
- **Conflicts are detected from the config itself.** Two enabled rules that
  can both match, share evaluation priority, and push price in opposite
  directions get flagged automatically — no business rule needed to say
  "these two disagree."

## Repository layout

```
backend/
  app/
    engine/         domain-agnostic core: condition DSL, expression evaluator,
                     rule/strategy evaluator, conflict detector, simulator
    ml/              pluggable ML-assist: demand prediction, anomaly detection,
                     NL-to-rule copilot (heuristic parser, LLM-swappable)
    store/           SQLite-backed versioned config store + audit log
    api/             FastAPI routes: pricing, simulation, config CRUD/
                     versioning/rollback, conflicts, audit, copilot
    data/domains/    hospitality.json, ride_hailing.json, ecommerce.json
                     (seeded at startup)
    data/domains_pending/
                     banking.json — held back to be added **live** through
                     the UI's "+ Add New Domain" button, demonstrating the
                     config-only onboarding claim
    data/sample_contexts/
                     labelled expected-price test cases per domain
  tests/             pytest: correctness against labelled cases, determinism,
                     conflict-detection precision/recall spot checks
frontend/
  index.html / app.js / styles.css
                     no-build static console: config viewer, simulation
                     console, price explainer (waterfall breakdown), audit
                     log, NL copilot — talks to the API, nothing else
```

## Running it

```bash
cd backend
python3.13 -m venv .venv && source .venv/bin/activate   # 3.13; pydantic-core has no 3.14 wheels yet
pip install -r requirements.txt
rm -f app/pricing.db                                      # optional: start from a clean seed
uvicorn app.main:app --port 8077
```

Open `http://127.0.0.1:8077/` — the backend also serves the frontend as
static files, so there's nothing else to start.

Run the correctness/determinism test suite:

```bash
cd backend && source .venv/bin/activate && pytest tests/ -v
```

## Adding a domain (the live-demo path)

`backend/app/data/domains_pending/banking.json` is a complete risk-based loan
APR pricing config (credit-score tiers, LTV/DTI add-ons, term premium,
segment discounts, delinquency penalty, collateral discount) that is
**deliberately not seeded at startup**. In the UI: Config tab → **+ Add New
Domain** → **Load Banking Sample** → **Add & Activate**. This POSTs the raw
JSON to `POST /api/domains/banking/config`, which validates it, runs conflict
detection, stores it as version 1, and activates it — all through the same
code path every other domain uses. No engine file changes. That's the "three
domains plus one added live, no rewrite" KPI, literally.

## Config format (the whole contract)

```jsonc
{
  "domain": "ride_hailing", "version": 1, "currency": "USD",
  "entity": {"name": "trip"},
  "attributes": [{"name": "demand_supply_ratio", "type": "number"}, ...],
  "base_price": {"mode": "attribute", "attribute": "base_fare"},
  "signals": {                              // optional ML-assist, see below
    "anomaly_detection": {"attr": "demand_supply_ratio",
                           "history_attr": "demand_supply_ratio_history",
                           "z_threshold": 3.0, "output_attr": "anomaly_flag"}
  },
  "rules": [{
    "id": "surge_tier_high", "priority": 11,
    "condition": {"attr": "demand_supply_ratio", "op": "between", "value": [1.8, 2.5]},
    "adjustment": {"type": "multiply", "value": 1.6}
  }, ...],
  "constraints": [{"type": "max_increase_pct", "value": 2.0},
                   {"type": "round", "value": 0.5, "rounding": "nearest"}]
}
```

Rules execute in ascending `priority` order (ties keep config order —
deterministic, but worth flagging, see conflicts below). Supported condition
ops: `==, !=, >, >=, <, <=, in, not_in, between, contains, exists`, composed
with `all`/`any`/`not`. Adjustment types: `multiply`, `percent`, `add`,
`set`, `formula` (sandboxed arithmetic over context + running `price` +
original `base`). Constraints: `min_price`, `max_price`,
`max_increase_pct`, `max_decrease_pct`, `round` (`nearest`/`up`/`down`/
`charm` i.e. `x.99`).

## ML-assist signals

Two small, transparent models — not black boxes — run before rules and
inject derived attributes back into context, with every number they produce
shown in the explanation:

- **Demand prediction**: a declarative weighted-feature score (feature →
  weight, with optional `match`/`min_threshold`/`max_threshold` gates). Used
  by hospitality (`demand_index` from occupancy + day type + lead time) and
  e-commerce (`demand_index` from sales velocity + inventory scarcity).
- **Anomaly detection**: a z-score outlier test against a supplied history
  list. Ride-hailing uses it as a guardrail — `ride_hailing.json`'s
  `anomaly_guard_cap` rule caps surge to 1.5× base fare whenever the
  demand/supply signal looks statistically anomalous, visible in the
  `signals` block of the explanation.

Both are swap-in points: replace the function body with a trained model and
every config/rule keeps working unchanged.

## Conflict detection (and a deliberate example)

`detect_conflicts()` runs pairwise over enabled rules and flags:
`contradictory_override` (two "set" rules can both fire with different
values), `priority_tie` (two same-priority rules can both fire and push
price in opposite directions), and `duplicate_condition_conflicting_adjustment`.
Disjointness is proven conservatively — only via identical-attribute `==`
constraints inside `all` blocks — so it favors flagging a possible conflict
over silently mis-ordering rules.

`ride_hailing.json` ships one **deliberate** example:
`demand_based_surge_addon` (percent +20%, multiplicative) and
`first_ride_promo_discount` (flat -$5) both sit at priority 40. Because one
is multiplicative and the other additive, **order changes the actual
dollar result** (surge-then-credit vs. credit-then-surge differ by $1 on the
`first_ride_promo_during_surge_order_sensitive` test case — see
`backend/app/data/sample_contexts/ride_hailing_cases.json`). The Config tab's
Conflict Detection panel flags this live; it's resolved by giving the rules
distinct priorities once the business decides which should win.

## Audit & versioning

Every `POST /api/price/{domain}` call writes an audit row (full request
context + full response explanation + config version + timestamp). Config
changes never overwrite — `POST /api/domains/{domain}/config` always creates
a new immutable version (validated, conflict-checked, optionally activated);
`POST /api/domains/{domain}/rollback/{version}` just flips which version is
active. The Versions table in the UI drives this directly.

## KPI → implementation map

| KPI | Where |
|---|---|
| 3+ domains via config only, 1 added live | `data/domains/*.json` (3) + `data/domains_pending/banking.json` added through the running UI with no code change |
| Pricing correctness, deterministic/reproducible | `tests/test_engine.py`: 10 labelled cases across 4 domains, 100% match, verified identical across repeated runs |
| Config UX time-to-configure | No-code JSON authoring + `/api/copilot/nl-to-rule` turns one English sentence into a draft rule in one request |
| Explainability / audit | `PricingResult.to_dict()` on every price; `audit_log` table on every request |
| Rule-conflict detection | `detect_conflicts()`; precision/recall spot-checked in tests (flags the real conflict, doesn't flag disjoint same-attribute rules) |
| Flexibility (rule types, tiers, constraints) | 5 adjustment types incl. formulas, 10 condition ops, 5 constraint types, per-domain rounding strategies (whole-dollar / half-dollar / charm pricing) all exercised across the 4 configs |
| AI value | Weighted-feature demand index, z-score anomaly guardrail, NL→rule copilot — all pluggable for a trained model or a live LLM call later |

## What's intentionally out of scope

No real-time feature store, no approval-workflow UI beyond draft/activate/
rollback, no load-testing harness for the throughput KPI, and the NL copilot
is a transparent heuristic parser rather than a live LLM call (kept the demo
deterministic and offline; the output contract is designed so swapping in an
Anthropic API call is a drop-in change, not a redesign).
