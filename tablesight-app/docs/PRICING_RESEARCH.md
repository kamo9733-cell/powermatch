# Pricing research

Date retrieved: 2026-10-19 for every row below. All figures came from web search snippets (third-party aggregators and vendor blogs), none from fetching the vendor's own pricing page, so each is "reported". Where sources disagreed, the range is shown. Currency is USD unless noted. Prices change; re-verify before publishing any comparison.

## 1. Competitor and adjacent-tool pricing

### AI floor / camera analytics
| Vendor | Reported price | Notes | Source (retrieved 2026-10-19) |
|---|---|---|---|
| Shire | From $250 flat per month, free trial | Capterra listing; scope (cameras, locations) not stated | https://www.capterra.com/p/10048928/Shire/ |
| Gritsee | unverified | No price found | https://www.cbinsights.com/company/gritsee |
| Eyezilla | unverified | No price found | https://www.cbinsights.com/company/gritsee/alternatives-competitors |
| Agot AI, PreciTaste, Satis.ai | unverified | Enterprise kitchen systems, no public price found | https://techcrunch.com/2022/02/11/agot-ai-gives-restaurants-computer-vision-to-see-where-food-orders-go-wrong |
| V-Count / FootfallCam / Retail Sensing (occupancy) | unverified | No pricing published; quote by sensor and entrance count | https://v-count.com/industries/nightclubs/ |

### Cloud video (per-camera reference points)
| Vendor | Reported price | Notes | Source |
|---|---|---|---|
| Verkada | Camera licence: $199 per camera per year (one directory) to $249 for a 1-year licence (MSRP cited elsewhere); multi-year cited at $659 / 3y, $1,099 / 5y, $2,199 / 10y | Hardware extra; 30-day cloud backup included, longer retention extra | https://www.coram.ai/post/verkada-pricing , https://www.spot.ai/blog/verkada-pricing-2026 |
| Solink | Per location, not per camera; directories list from about $175 per location per month; vendor pricing is quote-only | Scales with cameras, retention, add-ons | https://www.spot.ai/blog/solink-review-2026 , https://www.capterra.ca/software/148731/solink-loss-prevention-system |

### Restaurant software owners already pay for
| Tool | Reported price | Source |
|---|---|---|
| Toast POS | Starter $0/mo; Point of Sale $69/mo; custom for multi-location; small operators reportedly $300-700/mo all-in | https://www.owner.com/blog/toast-pricing , https://www.capterra.com/p/136301/Toast-POS/pricing/ |
| OpenTable | Sources conflict: one lists $149 / $299 / $499 per month plus $1.50 per network cover; others list $39 and $179 tiers | https://www.servmeco.com/resources/opentable-competitors |
| Resy | One source: $289 and $459 per month tiers; another: roughly $199-389. Unclear | https://restaurant.eatapp.co/blog/management/buying-a-restaurant-reservation-system |
| SevenRooms | Unpublished; one source estimates $700-1,000/mo plus setup | https://sevenrooms.com/blog/restaurant-reservation-system-comparison-guide/ |
| Yelp Guest Manager | About $99-129/mo | https://sourceforge.net/software/product/Yelp-Guest-Manager/ |
| Wisely | About $150-240 per location per month (stale, data dated 2021 in one source) | https://zoftwarehub.com/en-bh/products/wisely/pricing |

## 2. What the market tells us
- Per-camera cloud video licences sit around $17-21 per camera per month at annual terms (Verkada, derived from $199-249 per year). That is a ceiling reference for "a camera that is only recorded and searched", not for analytics.
- The nearest front-of-house rival lists from $250 per month flat. A location plan priced far above that needs a clear ROI argument.
- Restaurant software commonly costs $70-500 per month per location. An owner will compare us to those.
- Competitors mostly hide pricing behind quotes (enterprise sales). Published, simple pricing is itself a differentiator for single-site owners.

## 3. Proposed pricing model (draft, to validate)

Principles: price per location with included camera count (owners think per venue), cameras beyond the bundle billed per camera, and the price must clear the cost per camera in UNIT_ECONOMICS.md with at least about 70% gross margin in the edge-box mode. All plan prices are proposals, not market-verified willingness to pay.

Cost inputs used (all assumptions, defined in UNIT_ECONOMICS.md): edge box about $17.58 per box per month (amortisation, replacement allowance, power); variable overhead and support $5 per camera per month; 8 cameras per box. Cloud GPU instance $384 per month (g4dn.xlarge, us-east-1 on-demand).

| Plan | Included | Proposed price | Extra camera | Mode | Est. cost to serve | Est. gross margin |
|---|---|---|---|---|---|---|
| Essential | 1 location, up to 4 cameras, 30-day event history, core alerts (table, queue/occupancy where template applies) | $149/mo | $25/mo | Edge box (1 box, 4 cameras) | $17.58 + 4 x $5 = $37.58 | about 75% |
| Pro | 1 location, up to 12 cameras, POS integration, API/webhooks, 90-day history | $299/mo | $22/mo | Edge boxes (2 boxes) | 2 x $17.58 + 12 x $5 = $95.16 | about 68% |
| Group | 3+ locations, rollups, SSO-style roles, priority support | from $249 per location/mo, 12 cameras each, volume discount by quote | $20/mo | Edge | same as Pro per location | about 65-70% after discount (assumption) |
| Bring-your-own-PC | Same features, runs on owner's hardware | Essential price minus $30, Pro minus $60 (proposal) | same | Owner PC | no hardware cost; support $5 per camera | higher than edge, but support risk higher (unverified) |
| Cloud GPU (add-on mode) | Only when a site cannot host a box | +$20 per camera per month over edge price | | Cloud | see below | see below |

Cloud GPU mode check (12 cameras at one location, price $299 + 12 x $20 = $539):
- If 20 cameras share a GPU (assumption): GPU share 12/20 x $384 = $230 + $60 overhead = $290, margin about 46%.
- If 40 cameras share a GPU (assumption, needs motion-gating and low frame rates): $115 + $60 = $175, margin about 68%.
- If only 10 cameras fit per GPU (pessimistic assumption): $461 + $60 = $521, margin about 3%. Cloud mode should not be offered until measured throughput confirms at least 20 cameras per GPU.

Other rules:
- Trial: 14 days, one location (assumption, matches common SaaS practice, not market-verified).
- Usage limits enforced by plan: locations, cameras, retention (per CLAUDE.md section 6).
- Annual prepay discount around 15%: assumption. One CostBench page reports 15-20% annual savings for Toast; single source.
- Price against: Shire from $250, Verkada about $17-21 per camera per month, POS at $69+.
- Currency and local pricing for non-USD markets are not researched. unverified.

## 4. Open items
- Obtain actual quotes from Shire, Eyezilla, Gritsee.
- Run price-sensitivity interviews (Van Westendorp style) with owners.
- Replace every throughput assumption with measured numbers from the benchmark harness.
