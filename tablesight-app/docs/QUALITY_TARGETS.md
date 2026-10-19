# Quality targets (initial, to be validated with managers)
- Neglect-alert precision >= 90% on eval clips (one confident wrong alert erodes trust).
- Time-to-alert within +/- 60 s of the template threshold.
- <= 6 alerts/hour per manager on a busy night; hard per-table cap.
- Zero alerts or state changes while a camera is stale or confidence < 0.5 (enforced by tests today).
- Occupancy accuracy and role-classification targets: TBD after first benchmark.
