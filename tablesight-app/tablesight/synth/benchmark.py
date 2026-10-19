"""Fixed-seed tracker benchmark on SYNTHETIC scenes, a stored baseline, and a markdown report.

    python -m tablesight.synth                  # print the comparison table
    python -m tablesight.synth --write-baseline # re-record baseline.json (only after review!)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..perception import ByteTracker, IouTracker
from .metrics import TrackMetrics, evaluate
from .scene import SCENARIOS

BASELINE_PATH = Path(__file__).with_name("baseline.json")
GATE_SEEDS = list(range(10))  # fixed; changing them invalidates baseline.json
TRACKERS = {
    "greedy_iou": lambda: IouTracker(min_hits=3),
    "bytetrack_style": lambda: ByteTracker(min_hits=3),
}


def run_benchmark(seeds: list[int] = GATE_SEEDS) -> dict[str, dict[str, TrackMetrics]]:
    return {name: {sc: evaluate(f, sc, seeds) for sc in SCENARIOS} for name, f in TRACKERS.items()}


def pooled(by_scenario: dict[str, TrackMetrics]) -> dict:
    ms = list(by_scenario.values())
    tp = sum(m.tp for m in ms)
    sw = sum(m.id_switches for m in ms)
    return {"id_switches": sw, "tp": tp, "switch_rate_per_1k": round(1000 * sw / tp, 3),
            "hota": round(sum(m.hota for m in ms) / len(ms), 4),
            "idf1": round(sum(m.idf1 for m in ms) / len(ms), 4),
            "role_crossing_switches": sum(m.role_crossing_switches for m in ms)}


def to_baseline(res: dict[str, dict[str, TrackMetrics]]) -> dict:
    return {"synthetic": True, "seeds": GATE_SEEDS,
            "note": "Synthetic scenes only; not real-world accuracy.",
            "trackers": {n: {"overall": pooled(r), "scenarios": {s: m.as_dict() for s, m in r.items()}}
                         for n, r in res.items()}}


def load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text())


def markdown(res: dict[str, dict[str, TrackMetrics]]) -> str:
    a, b = res["greedy_iou"], res["bytetrack_style"]
    rows = ["| scenario | tracker | ID sw. | sw./1k | role-crossing sw. | IDF1-lite | HOTA-lite | DetA | AssA |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|"]

    def line(sc, name, m):
        return (f"| {sc} | {name} | {m.id_switches} | {m.switch_rate_per_1k:.1f} | "
                f"{m.role_crossing_switches} | {m.idf1:.3f} | {m.hota:.3f} | {m.deta:.3f} | {m.assa:.3f} |")
    for sc in SCENARIOS:
        rows += [line(sc, "greedy IoU", a[sc]), line(sc, "ByteTrack-style", b[sc])]
    pa, pb = pooled(a), pooled(b)
    for nm, p in (("greedy IoU", pa), ("ByteTrack-style", pb)):
        rows.append(f"| **ALL** | {nm} | {p['id_switches']} | {p['switch_rate_per_1k']:.1f} | "
                    f"{p['role_crossing_switches']} | {p['idf1']:.3f} | {p['hota']:.3f} | | |")
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tablesight.synth")
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args(argv)
    res = run_benchmark()
    print(markdown(res))
    if a.write_baseline:
        BASELINE_PATH.write_text(json.dumps(to_baseline(res), indent=2, sort_keys=True) + "\n")
        print(f"wrote {BASELINE_PATH}")
    return 0
