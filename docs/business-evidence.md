# Illustrative inventory business evidence

This document describes current implemented assumptions, not a customer-approved policy. The [connected local demonstration](connected-demo-experiment.md) is the sole worked scenario here; the [review packet](review-packet/README.md) prepares a future observation. No reviewer has completed this exercise. No measured time savings, validated economics, customer approval or realized recovery is claimed. Preparation checks verify packaging and arithmetic only. Independent-validation work is not a prerequisite or evidence source for this packet.

## Implemented rules and owner decisions

References name current functions/classes so they remain usable when line numbers move. The frozen copies in the original connected-run directory retain the exact historical implementation; packet fingerprints preserve the copied evidence. These are explanations of implementation, not new defaults.

| Area | Current implementation and illustrative assumption | Future owner decision/evidence |
| --- | --- | --- |
| Source scope | `scripts/connected_demo_experiment.py:prepare` freezes 3 documents, 6 catalogue offers, 5 inventory rows, master, labels, baseline and `Policy()`. `agentic.Runtime.enrich_from_supplier_documents` joins exact supplier + source SKU; checks source hashes, duplicate offers and identity conflicts; enriches identity/description only. Catalogue availability and prices do not become on-hand or book cost. Unmatched catalogue offers do not become inventory. | Inventory: system scope, base units, physical count and source completeness; procurement: correct supplier/version and identifiers. |
| Unique physical holdings | `engine.Analysis.retrieve` rejects all rows sharing a physical holding ID; without one uses source system/SKU/warehouse key. Distinct PHYSICAL-1 and PHYSICAL-2 may sum even though their supplier SKU agrees. This key is not proof against an incorrectly assigned mirror ID. | Inventory: certify IDs represent separate holdings, reconcile warehouses and mirrored feeds. |
| Cutoff, freshness, quarantine | Cutoff 2026-10-31; `models.Holding` validates nonnegative quantities/demand/safety/PO and strictly positive finite cost. `retrieve` accepts snapshot age 0–1 days, rejects future/stale snapshots and movement later than snapshot. Quarantined rows cannot affect totals. `agentic` Retrieval allows explicit accepted scope with exclusions; zero usable rows stops. | Inventory: cutoff calendar, approved lateness, exception remediation and scope sign-off. |
| Matching/ambiguity | `matching.match`: supplied MPN requires one normalized MPN/manufacturer candidate; unknown/ambiguous MPN abstains. Otherwise normalized SKU, then description similarity with equal numeric tokens, threshold .86 and margin .08. Crosswalk includes sources/version; unresolved mapping raises review in graph. | Inventory/procurement: approve master/crosswalk and resolve collisions; synthetic scorecard is not production accuracy. |
| Target and classification | `engine.Analysis.calculate`: target = monthly demand × 3 + safety stock, applied once per consolidated SKU. Obsolete if master obsolete, or movement age ≥365 days and zero demand. Excess = max(0, on-hand − obsolete − target); E&O = obsolete + excess. | Inventory: demand horizon, safety methodology, aging and lifecycle rules, seasonality and service risk. |
| Cost/demand conflicts | `calculate` requires identical unit cost, monthly demand and safety stock across matched holdings; conflicting SKU omitted with `conflicting_cost_or_demand`. It does not average costs or sum demand. Graph review stops on inconsistent scope/reconciliation. | Inventory/finance: costing basis, currency consistency, demand scope and allocation. Currency is an invented EUR fixture convention; `Holding` has no currency field or FX conversion. |
| Open purchases | `calculate` sums PO units separately; `result` procurement report calls for review, never cancellation. Five bearing PO units are excluded from current on-hand E&O. | Procurement: supplier commitments, cancellation/return rights and incoming risk; finance: avoid counting avoided spending as recovered cash. |
| Decimal money | `engine.money` uses Decimal, cents, ROUND_HALF_UP. Position E&O/inventory values rounded first; recovery uses rounded position E&O, rate minus per-unit handling, floored at zero and rounded to cents. Percentage undefined at zero denominator. | Finance: currency precision, taxes, transport, disposal/other costs and accounting treatment. |
| Comparable baseline | `engine.reconcile` requires equal cutoff, unions missing/extra SKUs, signed and absolute variance; baseline-zero percentages are null. `calculate` marks cutoff mismatch not comparable; graph blocks non-comparable/nonzero unexplained variance. Scope equality is an operational prerequisite, not automatically proven by equal dates. | Inventory/finance: identical warehouse/SKU scope, approved legacy definition and explanations. This fixture baseline is invented, not independent legacy validation. |
| Eligibility | `recommend`: scrap always; return only returnable; discount for active; transfer for active and transferable. Flags generate candidates, not verified commercial feasibility. CPU is obsolete, so return and scrap only despite transferable flag. | Procurement: supplier acceptance and terms; inventory: destination demand; finance: disposal/legal/commercial costs. |
| Economics | `models.Policy` sample v1: return .85, transfer .75, discount .50, scrap .05; €1 handling per at-risk unit for every option. `recommend` computes max(0, E&O value × rate − E&O units × handling). Transfer benefit is an estimated value proxy, not necessarily cash. | Inventory/procurement/finance jointly: actual rates, destination/supplier feasibility, handling, markdown market and execution costs; validate net economics before approval. |
| Exclusive aggregation | `recommend` ranks descending net, then option name for ties. `result` adds rank 1 per SKU only. Alternatives cover the same risk units; do not sum them or add approved value to estimated opportunity. | Finance: verify one feasible plan per SKU and consistent benefit definitions. |
| Human decisions | `store.Store.decide/get` persists one final approval/rejection per run/SKU with reviewer/reason, marks alternatives not selected and rejects repeats/alternative decisions. Rejection also finalizes that SKU in this demonstrator; no revision workflow is demonstrated. Approval does not execute ERP or change realized cash. | Authorized human reviewer: evidence, approval limits and disposition; finance: execution evidence and accounting before any realized benefit. |

Current code references: [inventory calculation and ranking](../inventorypulse/engine.py), [matching](../inventorypulse/matching.py), [schema and sample policy](../inventorypulse/models.py), [graph scope and source enrichment](../inventorypulse/agentic.py), [human decision storage](../inventorypulse/store.py), [connected fixture construction](../scripts/connected_demo_experiment.py). The preparation verifier independently recalculates from frozen input quantities and policy before comparing archived/current outputs; it does not reuse the engine as its financial oracle.

## Worked connected-demo EUR position

| SKU | On-hand | Target | Obsolete | Excess | Unit cost | E&O | Inventory value | Open PO |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BEARING | 120 + 80 = 200 | 20 × 3 + 10 = 70 | 0 | 130 | €12 | €1,560 | €2,400 | 5 |
| BELT | 50 | 5 × 3 + 5 = 20 | 0 | 30 | €20 | €600 | €1,000 | 0 |
| CPU | 10 | 0 | 10 | 0 | €100 | €1,000 | €1,000 | 0 |
| Total | 260 | 90 | 10 | 160 | — | €3,160 | €4,400 | 5 |

The stale PHYSICAL-5/Depot-5 999 units are excluded, not treated as zero physical inventory. Their potential €11,988 inventory cost is outside accepted scope and is not added to a confirmed exposure. E&O ratio is 71.82%; same-cutoff baseline €3,160, signed/absolute SKU and total variances €0. No ambiguous identity, conflicting cost/demand, duplicate holding, zero-baseline or rounding-boundary case is present; this exercise cannot measure ability to detect those cases.

| SKU | Return | Transfer | Discount | Scrap | Highest-ranked net |
| --- | ---: | ---: | ---: | ---: | ---: |
| BEARING (130 units) | €1,196 | €1,040 | €650 | €0 | Return €1,196 |
| BELT (30 units) | €480 | €420 | €270 | €0 | Return €480 |
| CPU (10 units) | €840 | Ineligible | Ineligible | €40 | Return €840 |

Ten pending alternatives represent only three mutually exclusive SKU decisions. Highest-ranked total €2,516 = €1,196 + €480 + €840, conditional on feasibility. The separate historical **SIMULATED-DEMO-REVIEWER** bearing-return approval was €1,196 with €0 realized cash; it is not part of the packet's pending assisted evidence and is not customer approval.

The repository's 24-SKU `data/sample` generator and other retrieval/agent experiments use different scopes and figures. Never combine their totals, currencies, outcomes or timings with these EUR connected-demo numbers. Recorded model-call durations measure software execution, not human review effort or saved time.
