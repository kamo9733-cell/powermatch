# MASTER BUILD PROMPT v2 — "TableSight": AI Floor Intelligence for Any Hospitality Business

> Save this as `CLAUDE.md` in an empty repo and tell the agent: "Read CLAUDE.md and execute it end to end. Resume from docs/PROGRESS.md if it exists."
> This prompt tells you **what must be true** and **what to be careful of**. It deliberately does **not** dictate exact models, thresholds, or libraries. Research, benchmark, and choose the best option yourself, and justify every choice with evidence.

---

## 0. How you work

### 0.1 Your role
You are a founding team in one: product lead, staff engineer, computer-vision/ML researcher, MLOps engineer, QA lead, security engineer, privacy counsel's technical partner, UX designer, data analyst, and a skeptical first customer. Switch hats explicitly and let them argue with each other.

### 0.2 Research protocol (use it for every significant choice)
1. State the question and the constraints (licence, cost per camera, edge hardware, latency, accuracy, maintenance burden).
2. Find **at least 3 candidates** from primary sources: official repos, papers, docs, benchmarks. Note publication dates and prefer actively maintained projects.
3. **Candidates must be open source** (see §2.2). **Verify licences from the actual LICENSE file** (code *and* weights *and* training data can differ). Commercial closed-source SaaS use must be allowed.
4. Where it matters, **benchmark on our own eval clips**, not just published leaderboard numbers. Published numbers come from different data.
5. Record the decision in `docs/DECISIONS.md`: question, options, evidence, choice, what would make you revisit it.
6. Never invent library APIs, model names, or benchmark numbers. If you can't verify something, say so and test it.

### 0.3 Discipline
- **Vertical slices.** Each phase ends with something that runs and passes tests. No half-built modules lying around.
- **Hero loop first.** Nothing else matters until "camera → tables → neglected-table alert a manager trusts" works well. Resist breadth before depth.
- **Evidence over claims.** Never mark something done because the code exists; it's done when a test or metric proves it.
- **No fake functionality** outside an explicit, clearly labelled Demo Mode.
- **Logs for resumption:** keep `docs/PROGRESS.md` (done / next / blocked), `docs/RED_TEAM.md` (what breaks in real life, ranked), `docs/OPEN_QUESTIONS.md` (things only the founder can answer; make a sensible default and keep moving).
- **Time-box research.** If a sub-problem eats too long, ship the simplest robust version, log it, and move on.
- **Stop and flag** (don't silently push through) if: a licence blocks commercial use, a legal requirement can't be met technically, or a core metric can't reach a usable level.

### 0.4 Safety limits for you as an agent
- Don't deploy anything to a public URL, send real emails/SMS, or spend money. Build deploy scripts and docs; I'll run them.
- Never commit secrets. Use `.env.example`.
- Only use video/datasets whose licence permits commercial use and which don't contain covertly captured footage. Document provenance in `docs/DATA.md`.

---

## 1. Who this is for (design for all of them)

The product must work for **any hospitality business owner**, from a single café to a franchise group. Research how each of these venue types actually operates and make the product adapt via **venue templates** set during onboarding:

| Venue type | What "service" means there | What to be careful of |
|---|---|---|
| Full-service / casual dining | Table visits, greet time, turns | The core case |
| Fine dining | Very frequent, subtle visits; long dwell is normal | Thresholds and alert tone must differ |
| Quick-service / counter / fast casual | Queue length, wait time, order-to-pickup, dining-room cleanliness | There may be no table service at all, so "neglect" means dirty tables or long queues |
| Cafés / coffee shops | Queue, seat occupancy, laptop campers | Long stays are normal, not a problem |
| Bars / pubs / nightclubs | Bar queue depth, occupancy vs licensed capacity | Dark, crowded, standing guests, no tables |
| Food courts / hotel restaurants / buffets | Shared seating, self-service | Tables aren't owned by one server |
| Patios / outdoor | Weather, sun glare, variable layouts | Layout changes daily |

Also research: what metrics owners already track, what tools they already use (POS, reservations, waitlist apps), and what would make them pay. Put findings in `docs/MARKET_RESEARCH.md` and let them shape priorities.

---

## 2. Non-negotiables

### 2.1 Privacy & law (a selling point, not an afterthought)
- **No facial recognition or biometric identification** of guests or staff by default. Research whether any tracking feature you build (e.g. appearance re-identification across cameras) could count as biometric processing under GDPR, Illinois BIPA, Texas CUBI, and similar laws; design so it doesn't, and document the reasoning.
- **Employee monitoring** rules differ by country (e.g. works councils in Germany, notice requirements in several US states, union agreements). Build per-location settings for staff analytics (on / anonymized / off) and generate the right notices. Don't give legal advice in the product; give templates and tell owners to check locally.
- Prefer **on-premise processing** with metadata-only cloud sync; make cloud video viewing opt-in.
- Blurring for non-privileged roles, configurable retention, audit log of feed access, data export and deletion per tenant.
- Treat children as a special category: no individual-level analytics on anyone who appears to be a minor.
- Produce a legal pack: privacy policy draft, DPA template, signage template, staff notice template, sub-processor list. Mark them as drafts needing lawyer review.

### 2.2 Open source only, with the right licences
- **Build the entire stack from open-source components:** models and weights, ML frameworks, inference runtimes, tracking, streaming server, database, queue, auth, UI libraries, fonts, monitoring, and deployment tooling. Use only OSI-approved licences.
- **No paid or proprietary dependencies in the core product**: no closed APIs for detection, tracking, auth, analytics, maps, or notifications. Where an external service is unavoidable (e.g. SMS delivery, push notifications), put it behind an interface with at least one open-source or self-hostable implementation.
- **The product must be fully self-hostable.** It must run on our own servers or an owner's hardware with no required calls to third-party clouds, and with no vendor lock-in.
- **Prefer permissive licences** (Apache-2.0, MIT, BSD) for anything linked into or shipped with the product, because we will sell it as a closed-source SaaS. Copyleft licences need care:
  - AGPL can force us to publish our source code if we offer the product over a network.
  - GPL affects anything we ship to customers, including the edge agent.
  - LGPL and MPL are usually workable when used as separate libraries.
  
  Research each case, avoid copyleft where a strong permissive alternative exists, and document any exception. Watch especially for popular AGPL detectors.
- **Check weights and datasets separately from code.** A model's code can be Apache-2.0 while its weights are non-commercial or its training data is restricted. Avoid "open" models with research-only or custom restrictive licences.
- **Prefer healthy projects.** Favour active maintainers, recent releases, a real community, and a good security record. A dead repo is a liability even if its licence is perfect.
- Keep `docs/LICENSES.md` complete (component, version, licence, where it's used, obligations such as attribution notices), and generate a third-party notices file automatically in CI. Make the detector and other key components pluggable interfaces so they can be swapped.

### 2.3 Honesty in the product
The system will be wrong sometimes. The UI must show **confidence**, mark **stale** data, and never present a guess as a fact. A manager who catches one confident wrong alert stops trusting all of them.

---

## 3. The hero loop (build and perfect this first)

**Camera feed → people detected and tracked → staff vs guests distinguished → people mapped to tables/zones → table states and visit events → a timely, correct "this table needs attention" alert on the right person's phone.**

Success for this loop is defined by metrics you establish in §5 (e.g. alert precision, time-to-detect, occupancy accuracy). Research what "good enough to trust" means for a manager on a busy night and set targets in `docs/QUALITY_TARGETS.md`.

---

## 4. Product modules

For each module: a goal, what to be careful of, and what to research. You decide the implementation.

### 4.1 Setup & onboarding
- **Goal:** a non-technical owner gets from signup to a useful live view on their own, fast.
- **Careful of:** cameras behind NAT, unknown RTSP URLs, existing NVR/DVR systems (most restaurants already have one, so research integrating with common NVR brands and ONVIF instead of requiring new cameras), bad camera angles, owners who won't buy new hardware.
- **Research:** how to auto-discover cameras on a LAN, which deployment options to offer (existing PC, small edge box, cloud-only for owners with good upload), how to rate a camera angle's usefulness automatically and suggest repositioning.

### 4.2 Floor calibration
- **Goal:** map camera pixels to real tables and zones with minimal effort.
- **Careful of:** tables moved or merged nightly, overlapping cameras, wide-angle/fisheye distortion, occluded tables, upstairs/multi-room layouts.
- **Research:** semi-automatic table detection to pre-draw polygons, homography/floor-plan mapping, how to handle layout presets ("lunch layout", "event layout").

### 4.3 Live floor
- **Goal:** one glance tells a manager where the problems are.
- **Careful of:** latency between video and overlays (sync matters), bandwidth on restaurant Wi-Fi, small phone screens, too much visual noise.
- **Research:** low-latency streaming options, drawing overlays client-side from metadata, a floor-plan view that's more useful than raw video.

### 4.4 Table & guest intelligence
- **Goal:** accurate table states, party sizes, turn times, wait times, walk-aways, and visit history.
- **Careful of:** everything in §5.3. Model states as explicit state machines with hysteresis and grace periods, all configurable per venue template.
- **Research:** what the industry already uses to define "turn time", "greet time", and "check time", so our numbers match owners' language.

### 4.5 Alerts
- **Goal:** the right person gets the right nudge at the right time, and doesn't learn to ignore us.
- **Careful of:** alert fatigue, duplicate alerts, alerts during rushes when everyone is already busy, alerts going to staff who are off shift, notification reliability on iOS/Android.
- **Research:** escalation patterns, adaptive thresholds by daypart and busyness, acknowledgement workflows, delivery channels owners actually use in each region (SMS, WhatsApp, Slack, push, smartwatch).

### 4.6 Analytics & reports
- **Goal:** turn tracking data into decisions: staffing, layout, training, revenue.
- **Careful of:** vanity metrics, misleading averages, comparing incomparable days, blaming individual staff for systemic understaffing.
- **Research and pick the strongest:** forecasting covers by hour, table-ready predictions for the host, section balancing, heatmaps and flow, revenue-per-seat-hour (with future POS data), shift reports, benchmarking across locations.

### 4.7 More features to evaluate
Brainstorm widely, then score each by value to owners vs. build effort vs. accuracy risk, and record the ranking in `docs/ROADMAP.md`. Build the top items; leave the rest documented. Starting candidates: queue length & wait for counter service, occupancy vs legal capacity, cleanliness/dirty-table detection, guests trying to get attention (pose-based, marked experimental), incident clips, camera health and tamper detection, natural-language questions over analytics, POS and reservation integrations, multi-location rollups, a TV mode for back-of-house, an ROI calculator for sales.

---

## 5. The AI system

### 5.1 Principles
- Choose detection, tracking, pose, and classification models through the research protocol. Optimise for **robustness in crowded, dim, occluded indoor scenes on modest hardware**, not leaderboard scores.
- Separate perception (detections, tracks) from reasoning (state machines, events). Most real-world reliability comes from the reasoning layer.
- Every output carries a confidence. Downstream logic must handle "uncertain" explicitly.
- Design for **per-venue adaptation**: each restaurant is a different domain (lighting, uniforms, layout).

### 5.2 Data strategy (the hardest part — take it seriously)
- There is little public, commercially licensed footage of restaurants with staff/guest labels. Research what exists, check licences, and document gaps.
- Plan a mix of: licensed public data, **synthetic data** (research rendering/simulation options), and **consented customer data with owner opt-in**.
- Build a **human-in-the-loop correction tool**: managers can tap "that's a waiter", "table is empty", "wrong alert". Corrections feed per-venue tuning and a labelled dataset (only with consent).
- Build a **labelling tool** for internal annotation of eval clips.
- Never train on customer data without explicit opt-in. Keep a data lineage record.

### 5.3 Real-world failure catalogue
Treat this as a starting list. Expand it through your own red-teaming and research, and for every item write a mitigation **and** a test.

**Counting & identity**
- Same person counted twice by overlapping cameras.
- Track IDs switching or fragmenting when people cross, lean, or are occluded by staff.
- One person split into two detections, or two close people merged into one (couples, parents holding children).
- People seen in mirrors, glass, windows, TVs, posters, artwork, or reflective menus.
- People outside the window or on the street counted as guests.

**Roles**
- Staff counted as guests and vice versa; staff without uniforms; managers in plain clothes; delivery drivers; cleaners; musicians; owners sitting with friends.
- Staff eating a shift meal at a table.
- Guests who look like staff (black clothing in a black-uniform venue).

**Table semantics**
- Walk-bys vs real visits; bussers vs servers (both are staff but mean different things); food runners; a manager's table touch.
- Guests visiting a friend's table; guests standing to leave or to greet someone.
- Bags, coats, phones holding a table; guest in the restroom or outside smoking.
- Tables pushed together, split, removed, or added; bar seating; communal tables.
- Children in high chairs, babies in arms, guests in wheelchairs, pets.

**Environment**
- Dim evenings, candlelight, sunlight sweeping across the room, IR/night mode, flickering lights, steam from kitchen, smoke.
- Camera bumped, re-angled, covered, dirty lens, frozen frame, low bitrate compression artefacts.
- Seasonal layout changes, Christmas decorations, events, private bookings.

**Systems**
- Network outages, edge reboots, power cuts, clock drift, camera reconnect storms.
- Rush-hour load where every camera is crowded at once.
- Time zones, daylight saving changes, venues open past midnight (which "day" does that belong to?).

### 5.4 Evaluation
- Build an eval harness with metrics at three levels: **perception** (detection, tracking, role classification), **semantics** (occupancy, party size, visit detection, turn time), and **outcomes** (alert precision/recall, time-to-alert, alerts per hour on busy nights).
- Build a **scenario simulator** that generates event streams for edge cases, so state machines can be tested without video.
- Gate CI on key metrics. Publish results in `docs/MODEL_CARD.md`, including known weaknesses and the conditions where accuracy drops.

### 5.5 Performance & cost
- Research edge hardware options at different price points and benchmark real throughput (cameras × FPS) on each target you can simulate.
- Compute **cost per camera per month** for every deployment mode (edge box, owner's PC, cloud GPU). Pricing must leave healthy margins. Put the model in `docs/UNIT_ECONOMICS.md`.
- Use adaptive frame rates and motion-gating so idle cameras cost almost nothing.

---

## 6. SaaS platform

You choose the stack via the research protocol, but it must deliver:
- **Multi-tenancy** (organisation → locations → devices/cameras → layouts/zones) with isolation proven by automated tests.
- **Auth:** email/password with verification and reset, passwordless option, social sign-in, 2FA, secure sessions, rate limiting, lockout.
- **Roles & permissions** suited to hospitality: owner, area manager, GM, host, server (own section only), viewer, plus invite flows. Research what permission needs real groups have.
- **Edge agent:** one-command install, pairing code, signed auto-updates, remote config, offline buffering with idempotent replay, health reporting.
- **Billing interface only:** plans, trials, usage limits enforced (locations, cameras, retention), and a provider interface with a no-op implementation. **Payment processing is the only thing left out.**
- **Internationalisation:** multi-language UI, currencies, date/time formats, time zones, right-to-left support (Arabic is a key market). Store all timestamps in UTC.
- **Observability, security, and operations:** structured logs, tracing, metrics, error reporting, OWASP review, CSP, dependency scanning, encrypted camera credentials, backups with tested restore, an internal admin/fleet console, and a support view that can see device health without seeing video.
- **Data export & API:** CSV export and a documented public API/webhooks so owners can connect their own tools.

---

## 7. UX & UI

- Research what managers do during a rush and design for **two-second glances** on a phone held in one hand.
- Distinct modes: manager mobile, host stand tablet, back-of-house TV, owner desktop analytics.
- Dark mode for in-service screens; colour-blind-safe status indicators; WCAG 2.1 AA.
- Every number is explorable down to the events behind it. Every screen has designed empty, loading, error, stale, and low-confidence states.
- Tone of staff features: **coaching and support, not surveillance.** Test copy with that lens.
- **Marketing site:** a clear value proposition, an interactive demo with a bundled licensed sample video, venue-type landing pages, pricing (checkout disabled), an ROI calculator, privacy and security pages, FAQ, and signup.
- Run a heuristic usability review of every primary flow and fix the top issues.

---

## 8. Business readiness

- `docs/PRICING_RESEARCH.md`: competitor research and a proposed pricing model tied to unit economics.
- Help centre articles for setup, calibration, alerts, and troubleshooting cameras.
- Sales assets: one-page product summary, ROI story with assumptions stated, a demo script.
- A customer feedback loop in-app.

---

## 9. Phases & gates

Order is a guide; adjust with justification. Each gate needs passing tests and updated docs.

1. **Research sprint:** market, venue types, models, licences, hardware, streaming, legal landscape. Gate: decisions recorded, quality targets set.
2. **Foundation:** stack, tenancy, auth, CI, design system. Gate: tenant isolation tests pass.
3. **Video in:** camera discovery/add, NVR/ONVIF, file upload, live playback. Gate: measured latency documented.
4. **Perception + eval harness.** Gate: baseline metrics published.
5. **Calibration, state machines, visit detection.** Gate: scenario simulator suite passes.
6. **Role classification + per-venue adaptation + correction tool.**
7. **Alerts (hero loop complete).** Gate: alert precision and time-to-alert meet quality targets on eval clips.
8. **Analytics, reports, predictions.**
9. **Multi-camera fusion, camera health, offline resilience.**
10. **Venue templates, i18n, marketing site, onboarding polish, demo mode.**
11. **Hardening:** load tests, security review, privacy review, full red-team pass, `docs/LAUNCH_CHECKLIST.md`.

---

## 10. Questions to keep asking yourself

- Would I trust this alert enough to walk across a busy dining room because of it?
- What does the product do with one bad camera angle, and does it say so honestly?
- What does the manager see when the internet drops at 8:45 pm on a Saturday?
- Would a server feel helped or spied on? Would a works council approve it?
- How many alerts per hour does a busy venue get, and would the manager mute us?
- Can an owner with no IT skills install this alone? Where exactly would they get stuck?
- Does this work for a café with no table service, a dark bar, and a fine-dining room?
- Does each feature earn its complexity, or is it a demo trick?
- What will break after six months: model drift, layout changes, staff turnover, new uniforms?
- What's our cost per camera, and does the price still make sense?
- What would a competitor demo better, and what can we demo that they can't?

---

## 11. Definition of done

A brand-new owner of any supported venue type can sign up, connect existing cameras or an NVR (or upload a video), calibrate their floor with assistance, see live tracking with honest confidence, receive accurate and well-timed alerts, correct the system when it's wrong, view analytics and shift reports, invite staff with the right permissions, and export their data. All of this runs from documented deployment scripts with tests green, metrics published, legal drafts ready for review, and **only payment processing left to connect.** The whole stack is built on open-source components and can be fully self-hosted.
