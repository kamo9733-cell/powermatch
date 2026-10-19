# Unit economics: cost per camera per month

Date: 2026-10-19. This is a model with explicit inputs. **No throughput benchmark has been run yet**, so cameras-per-device values are assumptions, shown as scenarios, not measurements. Replace them with measured numbers from the benchmark harness when it exists.

Legend: **[S]** price found in a cited search result (retrieved 2026-10-19, third-party snippet) | **[A]** assumption, not verified.

## 1. Inputs

| Input | Value | Tag | Source / reasoning |
|---|---|---|---|
| Jetson Orin Nano Super dev kit price | $399 | [S] | NVIDIA raised it from $249 (reported July 2026): https://cnx-software.com/2026/07/22/nvidia-increases-the-price-of-jetson-modules-and-devkits-by-up-to-101 , https://hwbusters.com/news/nvidia-jetson-prices-jump-up-to-101-the-249-orin-nano-super-is-now-399/ |
| Jetson Orin NX 16GB module (1,000-unit price) | $999 (was $599) | [S] | same CNX article; module only, not a retail unit |
| Enclosure, PSU, NVMe/SD, shipping per box | $100 | [A] | not researched |
| Box amortisation period | 36 months | [A] | assumption; no residual value or failure rate verified |
| Box power draw (average) | 15 W | [A] | not verified for our workload |
| Electricity price | $0.15 per kWh | [A] | varies widely by country |
| Hardware replacement/RMA allowance | 5% of hardware cost per year | [A] | no data |
| Cloud GPU: AWS g4dn.xlarge (1x T4) us-east-1 on-demand | $0.526/hr | [S] | https://calculator.holori.com/aws/ec2/g4dn.xlarge/us-east-1 (updated July 16, 2026 per page); other regions $0.587-$0.894/hr per aggregator tables |
| Cloud GPU spot (same instance) | about $0.2143/hr | [S] | https://compute.doit.com/spot/us-east-1/g4dn.xlarge ; interruptible |
| Hours per month | 730 | [A] | 8,760 / 12 |
| Control-plane cloud cost per camera (database, event storage, API, logs) | $2.00 | [A] | not measured |
| Support and customer success per camera | $3.00 | [A] | not measured |
| Camera stream bandwidth if streamed to cloud | 1 Mbps per camera (sub-stream) | [A] | = about 328 GB per month per camera at 24/7; ingress to AWS is typically free but the customer uplink must carry it; egress cost not modelled |
| Payment processing fee | not modelled | [A] | billing is a no-op interface, per CLAUDE.md |
| Raspberry Pi 5 + Hailo AI HAT+ class box | not modelled | | current prices unverified (search results inconsistent) |

Derived:
- Edge box all-in hardware = $399 + $100 = $499. Amortised over 36 months = **$13.86 per box per month**.
- Replacement allowance: 5% x $499 / 12 = **$2.08 per box per month**.
- Power: 15 W x 730 h = 10.95 kWh x $0.15 = **$1.64 per box per month**.
- Edge box total fixed cost = 13.86 + 2.08 + 1.64 = **$17.58 per box per month**.
- Cloud GPU on-demand = $0.526 x 730 = **$384 per GPU per month**; spot = 0.2143 x 730 = **$156 per GPU per month**.

## 2. Cost per camera, by mode

Formula: cost per camera = fixed device cost / cameras per device + control plane ($2) + support ($3).
Cameras per device is the key unknown. Three scenarios are shown for each mode; none is a measurement.

### Edge box (we ship a Jetson-class box)
| Cameras per box (assumed) | Box cost per camera | + $5 overhead | Total per camera per month |
|---|---|---|---|
| 4 | $4.40 | | **$9.40** |
| 8 | $2.20 | | **$7.20** |
| 12 | $1.47 | | **$6.47** |

Boxes are bought per site, so a 4-camera site with a box built for 8 pays for idle capacity; the per-site floor is the 4-camera row. Motion-gating and adaptive frame rate (CLAUDE.md 5.5) raise cameras per box, but how much is unmeasured.

### Owner PC (software on hardware the owner already has)
Hardware cost to us: $0. Owner's electricity and wear are not our cost.
Cost per camera = $2 control plane + $3 support = **$5.00 per camera per month**, plus an unmodelled risk: unknown hardware quality means more support load (support $3 is optimistic here; assumption). A minimum-spec requirement is needed. Not benchmarked.

### Cloud GPU (we host inference, owner streams video)
| Cameras per GPU (assumed) | On-demand per camera | Spot per camera | Total on-demand per camera (+ $5) |
|---|---|---|---|
| 10 | $38.40 | $15.60 | **$43.40** |
| 20 | $19.20 | $7.80 | **$24.20** |
| 40 | $9.60 | $3.90 | **$14.60** |

Not included (all unmodelled): video egress and NAT/transit charges, storage of clips, GPU idle time outside business hours (a GPU billed 730 h per month may serve a venue open about 12 h a day; consolidating many tenants on a shared pool is the main lever, no data), multi-region latency, and a CPU instance for decoding (T4 g4dn.xlarge includes 4 vCPUs; whether decoding fits is unmeasured). One GPU decoding many 1080p streams is likely decode-bound before inference-bound (unverified).

## 3. Comparison to proposed prices (from PRICING_RESEARCH.md)

| Mode | Cost per camera (mid scenario) | Price per camera at Pro (299/12) | Gross margin per camera |
|---|---|---|---|
| Edge, 8 per box | $7.20 | $24.92 | about 71% (per-camera view; site-level Pro margin about 68% because 12 cameras need 2 boxes) |
| Owner PC | $5.00 | about $19.9 (Pro minus $60 BYO discount) | about 75%, ignoring elevated support risk |
| Cloud GPU, 20 per GPU | $24.20 | $44.92 (edge price + $20) | about 46% |

Conclusions that follow from the model, not from measurements:
1. Edge has the best margin as long as 8 or more cameras per box is achievable; if only 4 per box, margin drops but remains healthy at the proposed prices.
2. Cloud mode is only viable with GPU consolidation of at least about 20 cameras per GPU. Do not sell it before benchmarking.
3. The single biggest uncertainty is cameras per device. The benchmark must report cameras x FPS at the model and resolution we will actually ship, with decode included.
4. The $399 box price is sensitive to supplier increases (it rose 60% in 2026 per the sources above). A cheaper box (Raspberry Pi-class with accelerator) might lower cost but is not priced or benchmarked here.

## 4. Sensitivity (simple)
- Box price +$100: +$2.78 per box per month before the 5% allowance, about +$0.35 per camera at 8 cameras per box.
- Support $3 to $6 per camera: edge total at 8 per box moves from $7.20 to $10.20.
- Cloud at 20 per GPU with spot pricing: $7.80 + $5 = $12.80 per camera, but spot interruptions are not handled.

## 5. To measure next (before trusting any number here)
- Real throughput: cameras x FPS per Jetson Orin Nano Super, and per T4, at our detector and tracker (licences are recorded in docs/LICENSES.md).
- Actual average power draw under load.
- Real control-plane and storage cost per camera at pilot scale.
- Support hours per site from pilots.
- Customer uplink capacity if cloud mode is considered.
