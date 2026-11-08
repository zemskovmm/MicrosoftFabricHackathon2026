# Facilitator-only answer and scoring key

Do not release until both submissions are frozen. No reviewer results are present here. Preparation arithmetic is not an observation.

## Extraction and identity

`extraction-oracle.json` contains all six exact offer fields independently frozen before the connected live run. Check source quotations directly against each original product section. `assisted/extraction.json` contains code-attached quotes and pack counts. In 003-quote-01 the second offer is a **pack of 10**; its document reference is not an SKU. All three documents name Northline Industrial Supply. The first offer of each maps as follows; the three other catalogue offers have no physical inventory rows and must not become positions.

| Source SKU | Manufacturer / MPN | Canonical SKU | Physical holdings |
| --- | --- | --- | --- |
| NL-01-01-1 | SKF / 6205-2RSH | BEARING | PHYSICAL-1, PHYSICAL-2; PHYSICAL-5 excluded |
| NL-04-02-1 | Gates / 500-5M-15 | BELT | PHYSICAL-3 |
| NL-07-03-1 | Siemens / 6ES7214-1AG40-0XB0 | CPU | PHYSICAL-4 |

Accepted_scope holdings.csv row references are header-inclusive: rows 2/3 bearings, row 4 belt, row 5 CPU, row 6 stale bearing. PHYSICAL-5 snapshot 2026-10-01 is 30 days old at cutoff, outside one-day limit. Accept four unique physical holdings, quarantine one. Supplier prices €3.40/€43.40/€83.40 are not book costs €12/€20/€100. The matching bearing holdings share a catalogue SKU but are separate physical stock, not duplicates. No actual cost/demand conflict or ambiguity exists here; do not invent one.

## Financial answers and points

Award one point for each exact F criterion, zero otherwise (12 points). Score identically for manual/assisted. Amounts must agree to the cent; quantities exactly. Retain submitted values and signed/absolute EUR error for each financial field, without summing overlapping component and total errors into a spurious financial loss. Missing answers are missing, not observed zero. No scoring threshold here is a product or customer acceptance rule.

| ID | Required answer |
| --- | --- |
| F1 | BEARING on-hand 200, target 70, obsolete 0, excess 130 |
| F2 | BELT on-hand 50, target 20, obsolete 0, excess 30 |
| F3 | CPU on-hand 10, target 0, obsolete 10, excess 0 |
| F4 | BEARING E&O €1,560.00 |
| F5 | BELT E&O €600.00 |
| F6 | CPU E&O €1,000.00 |
| F7 | Total inventory €4,400.00 and total E&O €3,160.00 |
| F8 | BEARING best return €1,196.00 = 1,560 × .85 − 130 |
| F9 | BELT best return €480.00 = 600 × .85 − 30 |
| F10 | CPU best return €840.00 = 1,000 × .85 − 10 |
| F11 | Exclusive best-option total €2,516.00; approved €0.00; realized €0.00 |
| F12 | Same-cutoff/scope baseline €3,160.00; each signed and absolute variance €0.00; total absolute variance €0.00 |

For option checking: BEARING transfer €1,040, discount €650, scrap €0 (negative −€52 floored); BELT transfer €420, discount €270, scrap €0; CPU scrap €40. CPU transfer/discount ineligible. All three return flags true but supplier acceptance unproven. E&O percentage 71.82%; five open PO units on BEARING are separately reported, not added to current exposure. See [worked rules](../../business-evidence.md).

## Exceptions, decisions and safety points

Award one point for each fully satisfied E criterion (8 points), retaining individual failures. Total 20 is an exercise score, not a validation claim. Count missed required safeguards separately from financial accuracy; a higher speed/total score must not hide an inappropriate approval. E criteria include review hazards, not eight actual corrupt source rows.

| ID | Required handling |
| --- | --- |
| E1 | Exclude PHYSICAL-5's 999 stale units, cite date/row, request current snapshot from inventory owner; explicitly retain accepted-scope limitation. |
| E2 | All-stale case: all five excluded, no usable inventory, stop at Retrieval for review, no recommendations/approval; request refreshed feeds. Do not continue just because historical baseline exists. |
| E3 | Keep book cost/on-hand separate from catalogue price/availability; do not create inventory from three unused offers or pack count. |
| E4 | Consolidate two distinct bearing holdings; trace all accepted identities to original supplier sections and exact supplier/SKU + MPN; no invented mapping or extra ambiguity. |
| E5 | Keep five bearing PO units separate; procurement review of cancellation/commitments required, no automatic cancellation or avoided-spend cash claim. |
| E6 | CPU obsolete excludes same units from excess and transfer/discount; alternatives mutually exclusive and not added together. |
| E7 | Paper disposition defers real approval pending supplier acceptance/destination demand, inventory scope and finance economics; capture owner/evidence/reason. Conditional ranking is allowed. An unqualified real approval based only on sample flags/rates is inappropriate. |
| E8 | Separate extraction corrections (source field/quote) from business decisions (policy/feasibility); no ERP action, no real/customer approval or realized cash claim. Historical simulated approval is not current reviewer consent. |

Record each missed E safeguard in `missed_exception`, plus source/impact in scorer notes. Record each inappropriate approval/action separately (SKU, action, missing evidence, count), even if it does not change arithmetic. There are no seeded extraction errors in the historical six-offer output: unsupported corrections count as introduced errors, not helpful discoveries. Also report field-level exact extraction matches out of 48 (six offers × supplier/SKU/manufacturer/MPN/unit/pack/price/currency), quote-source mismatches and unsupported changes; use scorer notes or additional session rows for the breakdown. No penalty for leaving unsupported commercial decisions deferred.

Inventory owner must confirm holdings, scope, freshness, demand/safety/lifecycle; procurement must confirm supplier identifiers/return eligibility/PO commitments; finance must confirm book costs, currency, recovery rates/handling and recognition. Record these as future decisions, never as decisions already made. Future observers should report elapsed/active seconds beside exact financial field errors, extraction errors, missed safeguards and inappropriate approvals. Report incomplete forms and order effects. The blank scoring form contains no scored reviewer rows.
