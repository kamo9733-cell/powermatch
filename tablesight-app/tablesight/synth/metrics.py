"""Tracking metrics on synthetic scenes: ID switches, IDF1-lite, HOTA-lite.

"Lite" = single IoU threshold (0.5) with per-frame optimal matching, not the full TrackEval
protocol (no threshold sweep, no localisation term averaging). Good enough to rank trackers on
the same data; not comparable to published MOT leaderboard numbers. Synthetic data only.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass

from ..evaluation import id_switches
from ..perception import Box, hungarian, iou
from .scene import Scene

TrackerFactory = Callable[[], object]


@dataclass(frozen=True)
class TrackMetrics:
    gt_boxes: int
    pred_boxes: int
    tp: int
    fp: int
    fn: int
    id_switches: int
    role_crossing_switches: int  # a track id jumped to a person of the OTHER role
    idf1: float
    deta: float
    assa: float
    hota: float

    @property
    def switch_rate_per_1k(self) -> float:
        """ID switches per 1000 correctly localised ground-truth boxes."""
        return 1000.0 * self.id_switches / self.tp if self.tp else 0.0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["switch_rate_per_1k"] = round(self.switch_rate_per_1k, 3)
        for k in ("idf1", "deta", "assa", "hota"):
            d[k] = round(d[k], 4)
        return d


def run_tracker(factory: TrackerFactory, scene: Scene) -> list[list[tuple[int, Box]]]:
    tr = factory()
    return [tr.update([d.det for d in f.dets]) for f in scene.frames]  # type: ignore[attr-defined]


def _match(gt: list, pred: list[tuple[int, Box]], thr: float) -> list[tuple[int, int]]:
    """Return (gt_index, pred_index) pairs, optimal on IoU, each with IoU >= thr."""
    if not gt or not pred:
        return []
    cost = [[1.0 - iou(g.box, p[1]) for p in pred] for g in gt]
    return [(i, j) for i, j in hungarian(cost) if 1.0 - cost[i][j] >= thr]


def score_tracking(scene: Scene, outputs: list[list[tuple[int, Box]]],
                   iou_thr: float = 0.5) -> TrackMetrics:
    role = {p.pid: p.role for p in scene.people}
    per_frame: list[dict[int, int]] = []
    pair_n: dict[tuple[int, int], int] = {}
    gt_n: dict[int, int] = {}
    pred_n: dict[int, int] = {}
    tp = fp = fn = 0
    last_pid_of_tid: dict[int, int] = {}
    role_cross = 0
    for fr, out in zip(scene.frames, outputs, strict=True):
        for g in fr.gt:
            gt_n[g.pid] = gt_n.get(g.pid, 0) + 1
        for tid, _ in out:
            pred_n[tid] = pred_n.get(tid, 0) + 1
        m = _match(fr.gt, out, iou_thr)
        tp += len(m)
        fn += len(fr.gt) - len(m)
        fp += len(out) - len(m)
        d: dict[int, int] = {}
        for gi, pi in m:
            pid, tid = fr.gt[gi].pid, out[pi][0]
            d[tid] = pid
            pair_n[(tid, pid)] = pair_n.get((tid, pid), 0) + 1
            prev = last_pid_of_tid.get(tid)
            if prev is not None and prev != pid and role.get(prev) != role.get(pid):
                role_cross += 1
            last_pid_of_tid[tid] = pid
        per_frame.append(d)
    sw = id_switches(per_frame)
    # IDF1-lite: one global tid<->pid assignment maximising co-occurring matched frames
    tids, pids = sorted(pred_n), sorted(gt_n)
    idtp = 0
    if tids and pids:
        cost = [[-pair_n.get((t, p), 0) for p in pids] for t in tids]
        idtp = sum(-cost[i][j] for i, j in hungarian(cost))
    total_gt, total_pred = sum(gt_n.values()), sum(pred_n.values())
    idf1 = 2 * idtp / (total_gt + total_pred) if (total_gt + total_pred) else 1.0
    deta = tp / (tp + fn + fp) if (tp + fn + fp) else 1.0
    assa = (sum(n * n / (gt_n[p] + pred_n[t] - n) for (t, p), n in pair_n.items()) / tp) if tp else 0.0
    return TrackMetrics(total_gt, total_pred, tp, fp, fn, sw, role_cross, idf1, deta, assa,
                        math.sqrt(deta * assa))


def aggregate(ms: list[TrackMetrics]) -> TrackMetrics:
    """Pool counts across sequences; average the ratio metrics."""
    n = len(ms)
    return TrackMetrics(
        sum(m.gt_boxes for m in ms), sum(m.pred_boxes for m in ms), sum(m.tp for m in ms),
        sum(m.fp for m in ms), sum(m.fn for m in ms), sum(m.id_switches for m in ms),
        sum(m.role_crossing_switches for m in ms), sum(m.idf1 for m in ms) / n,
        sum(m.deta for m in ms) / n, sum(m.assa for m in ms) / n, sum(m.hota for m in ms) / n)


def evaluate(factory: TrackerFactory, scenario: str, seeds: list[int]) -> TrackMetrics:
    from .scene import generate
    ms = []
    for s in seeds:
        sc = generate(scenario, s)
        ms.append(score_tracking(sc, run_tracker(factory, sc)))
    return aggregate(ms)
