# Market research

Date written: 2026-10-19. Method: web search snippets only (no vendor page was fetched in full). Every claim is tagged:
- **[S]** = seen in a cited search result (URL given). Search snippets are third-party and can be stale; treat as "reported", not "confirmed".
- **[G]** = general industry knowledge, not sourced here. Verify through customer interviews before relying on it.
- **unverified** = could not confirm.

No interviews with owners have been done. Everything below is desk research and should be validated with 10+ owner conversations per venue type.

## 1. How each venue type operates and what we should measure

| Venue type | How service works [G] | Metrics that matter | Product implication |
|---|---|---|---|
| Full-service / casual | Host seats parties, server owns a section, greet, order, food, check, bus and reset. Revenue depends on turns. | Table turn time, time-to-greet, time-to-first-visit, average check, covers per seat-hour | Core case. Seated-unattended alert, turn analytics. |
| Fine dining | Long courses, frequent subtle visits by several staff (server, sommelier, runners). Dwell of 2h+ is normal. | Pacing between courses, reservation adherence, average check per cover | Visit detection is ambiguous (many staff touch a table). Longer thresholds, gentle alert tone, daily digest rather than live pings. |
| Quick-service / fast casual | Counter order, pay, pickup. Little or no table service. | Queue length, wait time, order-to-pickup, dining-room cleanliness, throughput at peak | "Neglect" means long queue or dirty tables. Queue module, dirty-table detection. |
| Cafes / coffee shops | Queue at counter, long stays, laptop campers. | Queue time at peak, seat occupancy, seat-hour yield | Long dwell must not alert. Occupancy and queue are the useful outputs. |
| Bars / pubs / nightclubs | Bar service, standing crowds, dark, door control with a licensed capacity limit. | Bar queue depth, occupancy against licensed capacity, door counts | Table model does not apply. Occupancy counter and bar-queue are primary. Low light is a hard accuracy risk. |
| Food courts / hotel restaurants / buffets | Shared seating, self-service, tables not owned by a server. Hotel breakfast has a burst peak. | Seat availability, table clearing delay, buffet station depletion, peak throughput | Zone-level (not server-level) metrics. "Dirty table" and "free seat" matter. |
| Patios / outdoor | Layout changes daily, weather and sun glare. | Seat usage, weather impact on covers | Quick re-calibration, glare handling. |

Capacity rules: a FootfallCam product sheet states that nightclubs are legally required to keep occupancy within licensed capacity [S] (https://www.footfallcam.com/it/Content/data/documents/Download-Page/Info-Pack/[Food-Establishments]-Bar-and-Night-Club-Occupancy-Management-System.pdf). Exact rules vary by jurisdiction; check per market.

## 2. Metrics owners already track

Reported by vendor blogs (Toast, TouchBistro and others) [S]; benchmarks conflict between sources, so no single number is adopted:
- Prime cost = COGS + total labor; a commonly quoted target is about 60-65% of sales [S] (https://pos.toasttab.com/blog/on-the-line/restaurant-kpis).
- Food cost, one source: 28-35% of sales [S] (https://www.touchbistro.com/blog/important-restaurant-benchmarks).
- Labor cost: sources disagree (20-30% vs 25-35%; one cites a 36.5% full-service median) [S] (same TouchBistro and Toast pages).
- RevPASH (revenue per available seat hour, Cornell, Sheryl Kimes): revenue / (seats x open hours); should be trended against the venue's own baseline, no universal benchmark [S] (https://www.katalystos.com/blog/the-restaurant-metrics-that-actually-matter).
- Table turns: sources give different ranges because they define it differently (about 1.5-2 per meal period in one list; 2-5 at peak depending on format in another) [S] (https://loman.ai/blog/key-metrics-every-restaurant-owner-should-track). We should not quote a benchmark; we should show each venue its own baseline.
- Average check by daypart [S] (same sources).

What POS systems do not show (our wedge, [G]): time from seating to first staff contact, idle seated time, queue dwell, and anything that happens between POS events. POS knows when an order was rung, not that guests waited 9 minutes before anyone came over.

## 3. Tools owners already use

| Category | Examples | Price signals (all [S], reported, not vendor-confirmed) |
|---|---|---|
| POS | Toast, Square, Lightspeed, TouchBistro | Toast: Starter $0/mo, Point of Sale $69/mo, custom quote for multi-location; small operators reportedly end up at $300-700/mo with add-ons (https://www.owner.com/blog/toast-pricing, https://www.capterra.com/p/136301/Toast-POS/pricing/) |
| Reservations | OpenTable, Resy, SevenRooms, Tock, Eat App | OpenTable tiers and per-cover fees vary widely by source; Resy about $289-459/mo in one source; SevenRooms unpublished, estimates $700-1,000/mo in one source (https://sevenrooms.com/blog/restaurant-reservation-system-comparison-guide/, https://restaurant.eatapp.co/blog/sevenrooms-competitors) |
| Waitlist | Yelp Guest Manager, Wisely | Yelp about $99-129/mo; Wisely about $150-240 per location per month, stale data (https://sourceforge.net/software/product/Yelp-Guest-Manager/, https://zoftwarehub.com/en-bh/products/wisely/pricing) |
| Security cameras / video | Solink, Verkada, generic NVR/DVR, Hikvision/Dahua-type CCTV [G] | Verkada per camera licence; Solink per location (see PRICING_RESEARCH.md) |

Integration implication: owners already pay $70-700+/mo for software they rely on. We must integrate with it (POS, reservations), not ask them to replace it.

## 4. What would make them pay (hypotheses)

No survey data. Hypotheses to test in interviews, ranked by confidence [G]:
1. Fewer walk-aways and slower-service complaints: direct revenue link, the strongest ROI story.
2. Labor scheduling that matches real demand (labor is the largest controllable cost per the KPI sources above).
3. Occupancy compliance for bars and clubs (a legal need, so willingness to pay is high).
4. Manager time saved (daily digest instead of watching cameras).
5. Multi-location visibility for groups.

Vendor-reported outcomes exist but are marketing: one vendor case study claims 50% shorter seating wait and 20% shorter order wait at a Louisville restaurant [S] (https://dev.to/sciforce/optimizing-multi-zone-restaurant-service-with-computer-vision-for-hospitality-1ha8). Unverified; do not reuse in our ROI story without our own data.

Trust risk: Agot AI was described by some publications as "surveillance" [S] (https://www.cbinsights.com/company/peckish-3/alternatives-competitors). Staff-facing framing and privacy design are a differentiator.

## 5. Existing competitors in AI restaurant floor / camera analytics

| Company | What it does | Focus | Pricing | Source |
|---|---|---|---|---|
| Shire Intelligence | Uses existing CCTV to manage seating, table status, server workloads, wait quotes | Front of house, closest to us | Capterra lists from $250 flat per month, free trial; scope unclear | https://www.capterra.com/p/10048928/Shire/ , https://app.dealroom.co/companies/shire_intelligence |
| Gritsee | Video analytics on existing cameras: kitchen operations, staff productivity, cleanliness | Kitchen and operations | unverified (none found) | https://www.cbinsights.com/company/gritsee |
| Eyezilla (UK) | AI on existing CCTV and POS; customer interactions and staff performance; QSR, casual, cafes, bars | Broad | unverified | https://www.cbinsights.com/company/gritsee/alternatives-competitors |
| Agot AI | Kitchen cameras for order accuracy, waste, labor; QSR | Back of house, enterprise | unverified; raised $10M seed in 2021, Yum! Brands pilot reported | https://techcrunch.com/2022/02/11/agot-ai-gives-restaurants-computer-vision-to-see-where-food-orders-go-wrong |
| PreciTaste | Kitchen task management / prep forecasting with vision | Back of house, enterprise | unverified | https://techcrunch.com/?p=2355842 |
| Satis.ai | Kitchen efficiency and order accuracy | QSR kitchen | unverified | https://www.cbinsights.com/company/agotai/alternatives-competitors |
| V-Count, FootfallCam, Retail Sensing | People counting and occupancy for bars/clubs/retail, mostly overhead sensors | Occupancy compliance | no public pricing found | https://v-count.com/industries/nightclubs/ |
| Solink, Verkada | Cloud video with AI search/alerts, general security | Security, adjacent | see PRICING_RESEARCH.md | see there |

Gaps we can aim at (hypotheses): most listed players target kitchens or enterprise QSR; Shire is the nearest front-of-house rival and starts at a low flat monthly price, so our pricing must be credible against about $250/mo. Few seem to cover bars/cafes/food-court variants or Arabic/RTL markets (unverified; not checked product by product).

## 6. How this shapes priorities

1. Venue templates and alert tone control (already built) are essential, since fine dining and cafes invert the casual-dining logic.
2. Integrations (POS first) are what owners already expect, and give ground truth for evaluation.
3. Queue and occupancy modules open QSR, cafe, bar markets that table-centric rivals ignore.
4. Privacy-by-design messaging counters the "surveillance" reputation.
5. Pricing must sit against Shire (about $250/mo), Verkada (about $17-21 per camera per month at annual licences) and reservation tools ($100-500/mo).

## 7. Open research tasks
- Interview owners per venue type; test willingness to pay at the proposed plan prices.
- Fetch vendor pages directly (Shire, Eyezilla, Gritsee) and request quotes.
- Confirm occupancy-capacity law per launch market.
