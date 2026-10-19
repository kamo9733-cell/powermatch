"""Eval harness: perception, semantics and outcome metrics. Used to gate CI (see tests/test_eval_gate.py)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AlertScore:
    precision: float
    recall: float
    median_delay_s: float | None
    alerts_per_hour: float


def score_alerts(alerts: list[tuple[str, float]], truth: list[tuple[str, float]],
                 window_s: float = 120, hours: float = 1.0) -> AlertScore:
    """alerts/truth: (table, time). A truth episode is matched by at most one alert,
    which must fire within [truth_t - window, truth_t + window] (truth_t = when a human
    would say the table became neglected)."""
    unmatched = list(truth)
    tp, delays = 0, []
    for tb, t in sorted(alerts, key=lambda a: a[1]):
        m = next((x for x in unmatched if x[0] == tb and abs(t - x[1]) <= window_s), None)
        if m:
            unmatched.remove(m); tp += 1; delays.append(t - m[1])
    p = tp / len(alerts) if alerts else 1.0
    r = tp / len(truth) if truth else 1.0
    delays.sort()
    med = delays[len(delays) // 2] if delays else None
    return AlertScore(p, r, med, len(alerts) / hours)


def occupancy_accuracy(pred: list[int], truth: list[int]) -> float:
    return sum(p == t for p, t in zip(pred, truth)) / max(len(truth), 1)


def id_switches(gt: list[dict[int, int]]) -> int:
    """gt: per frame {track_id: true_person_id}. Counts times a true person changes track id."""
    last: dict[int, int] = {}
    n = 0
    for frame in gt:
        for tid, pid in frame.items():
            if pid in last and last[pid] != tid:
                n += 1
            last[pid] = tid
    return n
