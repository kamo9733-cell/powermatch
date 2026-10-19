# Roadmap and feature scoring

Date: 2026-10-19. Scores are judgement calls by the author, not customer data. Validate with owner interviews (see MARKET_RESEARCH.md).

## Scoring
- **Value** (1-5): benefit to an owner, from hospitality KPI and competitor research. 5 = high.
- **Effort** (1-5): build effort. 5 = largest.
- **Accuracy risk** (1-5): how likely the AI output will be wrong enough to hurt trust. 5 = highest.
- **Priority score** = 2 x Value + (6 - Effort) + (6 - Risk). Max 20. Ties broken by value.

Status key (as of the code in `tablesight/` today): **Built** = exists in code with tests; **Partial** = initial version only; **Documented** = this row only, not built.
Evidence: `tablesight/table.py` (state machine), `templates.py`, `alerts.py`, `health.py`, `roles.py`, `fusion.py`, `geometry.py`, `simulator.py`; `tests/test_scenarios.py`. Built features are validated on simulated scenarios only, not real footage, so accuracy is unproven.

## Ranked table

| Rank | Feature | Value | Effort | Acc. risk | Score | Status |
|---|---|---|---|---|---|---|
| 1 | Venue templates (thresholds per venue type) | 5 | 2 | 1 | 19 | Built (`templates.py`) |
| 2 | Alert fatigue control (spacing, escalation, holds) | 5 | 2 | 1 | 19 | Built (`alerts.py`) |
| 3 | ROI calculator for sales (assumptions shown) | 4 | 1 | 1 | 18 | Documented |
| 4 | Table turn / dwell / time-to-greet analytics reports | 5 | 2 | 2 | 18 | Documented |
| 5 | Camera health and tamper detection (frozen, covered, dark, bumped) | 4 | 2 | 1 | 17 | Built (`health.py`) |
| 6 | POS integration (ground truth plus revenue link) | 5 | 4 | 1 | 17 | Documented |
| 7 | Privacy modes (no faces, blur, staff opt-out info, retention) | 4 | 2 | 1 | 17 | Documented (policy in docs/legal) |
| 8 | Daily/shift digest to manager (email, chat) | 4 | 2 | 1 | 17 | Documented |
| 9 | Arabic / RTL reports and alerts | 4 | 2 | 1 | 17 | Documented |
| 10 | Manager correction loop (mark alert right/wrong, feeds evaluation) | 4 | 2 | 1 | 17 | Partial (role corrections only, `roles.py`) |
| 11 | Seated-unattended alert, table state machine (hero loop) | 5 | 3 | 3 | 16 | Built on simulator (`table.py`) |
| 12 | Queue length and wait time for counter service | 5 | 3 | 3 | 16 | Documented |
| 13 | Multi-location rollups | 4 | 3 | 1 | 16 | Documented |
| 14 | Edge offline buffering with idempotent replay | 4 | 3 | 1 | 16 | Documented |
| 15 | Reservation integration | 4 | 4 | 1 | 15 | Documented |
| 16 | TV mode for back of house | 3 | 2 | 1 | 15 | Documented |
| 17 | Own-baseline benchmarking (venue vs its own history) | 3 | 2 | 1 | 15 | Documented |
| 18 | Staff vs guest role classification (uniform colour, no biometrics) | 5 | 4 | 4 | 14 | Partial (`roles.py`, colour feature only) |
| 19 | Occupancy vs legal capacity | 4 | 3 | 3 | 14 | Documented |
| 20 | Server section workload balance | 4 | 3 | 3 | 14 | Documented |
| 21 | Wait-time quote for waitlist | 4 | 3 | 3 | 14 | Documented |
| 22 | Incident clips (short, retention-limited) | 3 | 3 | 2 | 13 | Documented |
| 23 | Waitlist app integration | 3 | 4 | 1 | 13 | Documented |
| 24 | Natural-language questions over analytics | 3 | 3 | 3 | 12 | Documented |
| 25 | Dirty-table / cleanliness detection | 4 | 4 | 4 | 12 | Documented |
| 26 | Heatmaps of dwell and traffic | 2 | 2 | 2 | 12 | Documented |
| 27 | Buffet / food-court shared-seating mode (zone metrics) | 3 | 3 | 3 | 12 | Documented |
| 28 | Patio quick re-calibration, glare handling | 3 | 3 | 3 | 12 | Documented |
| 29 | Staffing forecast from occupancy and RevPASH | 3 | 4 | 3 | 11 | Documented |
| 30 | Guests trying to get attention (pose-based) | 3 | 4 | 5 | 9 | Documented, experimental, do not ship by default |

## Notes
- Items 1, 2, 5 and 11 are built; item 18 and 10 are partial. CLAUDE.md 4.7 says to build the top items and leave the rest documented. Highest-ranked **not yet built** are 3 (ROI calculator), 4 (turn analytics), 6 (POS), 7-9. The cheapest next builds are 3, 4, 8, 9 (effort 1-2).
- Row 11 scores lower than its importance suggests because it is the product's core and carries real accuracy risk; it is built first regardless of rank (the hero loop).
- Row 12 and 19 map to the quick-service, cafe and bar segments (MARKET_RESEARCH.md section 1); they open markets that table-centric competitors may not address.
- Risk of pose-based attention detection (row 30) is the highest; per CLAUDE.md it must be marked experimental.
- No accuracy figure in this file is measured. Real evaluation needs licensed footage, currently blocked (docs/PROGRESS.md).


> **Status note (lead, after review):** the "Built / Partial / Documented" column above was written before the multi-agent pass. Several rows marked "Documented" now exist in code: ROI calculator (site), queue/capacity/reports/forecast modules, i18n + RTL, edge offline replay, TV mode, camera health. "Built" means unit-tested on synthetic data only; none is validated on real footage.
